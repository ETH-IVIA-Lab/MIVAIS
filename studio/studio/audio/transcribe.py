"""Asynchronous Whisper worker that drains the audio-chunk queue.

A single in-process worker is started in the FastAPI lifespan. It pulls
``AudioChunk.id`` values off an asyncio.Queue, runs faster-whisper in a thread
pool (CTranslate2 calls release the GIL but still want a thread), and writes a
``Transcript`` document plus a ``transcript_segment`` Studio Event. On error the
chunk is marked with ``transcribe_error`` and skipped — the worker stays alive.

The Whisper model is loaded lazily on first use so app startup stays fast and
studies with ``recording.transcribe: false`` never pay the model-load cost.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from beanie import PydanticObjectId

from studio.models import AudioChunk, Event, Session, Study, Transcript
from studio.models.event import SOURCE_STUDIO
from studio.settings import get_settings

log = logging.getLogger("studio.whisper")


class WhisperWorker:
    """Single-instance worker; instantiated once at module import time."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[PydanticObjectId] | None = None
        self._task: asyncio.Task | None = None
        self._model = None
        self._model_name: str | None = None
        self._stopping = False

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        settings = get_settings()
        if not settings.whisper_worker_enabled:
            log.info("whisper worker disabled via settings")
            return
        if self._task is not None and not self._task.done():
            return
        self._queue = asyncio.Queue()
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="whisper-worker")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        # Wake the loop if it's blocked on the queue.
        if self._queue is not None:
            try:
                self._queue.put_nowait(None)  # sentinel
            except Exception:
                pass
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        self._task = None

    def enqueue(self, chunk_id: PydanticObjectId) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(chunk_id)
        except asyncio.QueueFull:
            log.warning("whisper queue full; dropping chunk %s", chunk_id)

    # ── main loop ────────────────────────────────────────────────────

    async def _run(self) -> None:
        assert self._queue is not None
        while not self._stopping:
            try:
                chunk_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            if chunk_id is None:  # sentinel from stop()
                continue
            try:
                await self._transcribe_one(chunk_id)
            except Exception as exc:
                log.exception("whisper worker: failed for chunk %s: %s", chunk_id, exc)

    async def _transcribe_one(self, chunk_id: PydanticObjectId) -> None:
        chunk = await AudioChunk.get(chunk_id)
        if chunk is None:
            return
        if chunk.transcribed:
            return  # already done (idempotent on duplicate enqueues)

        session = await Session.get(chunk.session_id)
        study = await Study.get(session.study_id) if session is not None else None
        if session is None or study is None:
            return

        rec = study.recording or {}
        if not rec.get("transcribe", False):
            return
        model_name = rec.get("whisper_model") or get_settings().whisper_default_model
        lang = rec.get("whisper_language") or get_settings().whisper_default_language
        lang_arg = None if lang == "auto" else lang

        try:
            model = await self._ensure_model(model_name)
        except Exception as exc:
            chunk.transcribe_error = f"model-load-failed: {exc!r}"
            await chunk.save()
            return

        # Run the CPU-bound transcription off the event loop.
        loop = asyncio.get_event_loop()
        try:
            text, segments, info, conf, envelope = await loop.run_in_executor(
                None, _do_transcribe, model, chunk.file_path, lang_arg,
            )
        except Exception as exc:
            chunk.transcribe_error = f"transcribe-failed: {exc!r}"
            await chunk.save()
            log.warning("whisper failed for chunk %s: %s", chunk_id, exc)
            return

        # Convert segments → flat word list with chunk-anchored timestamps.
        words: list[dict[str, Any]] = []
        for seg in segments:
            for w in (seg.get("words") or []):
                words.append({
                    "w": w["w"],
                    "t_start_ms": chunk.t_ms_start + int(w["t_start_s"] * 1000),
                    "t_end_ms":   chunk.t_ms_start + int(w["t_end_s"]   * 1000),
                })
        # Update duration from the model's audio info if available.
        duration_ms = int(info.get("duration_s", 0) * 1000) if info else chunk.duration_ms
        if duration_ms > 0:
            chunk.duration_ms = duration_ms
            chunk.t_ms_end = chunk.t_ms_start + duration_ms

        transcript = Transcript(
            session_id=chunk.session_id,
            participant_id=chunk.participant_id,
            audio_chunk_id=chunk.id,
            t_ms_start=chunk.t_ms_start,
            t_ms_end=chunk.t_ms_end,
            text=text,
            words=words,
            language=(info or {}).get("language"),
            whisper_model=model_name,
            confidence=conf,
        )
        await transcript.insert()

        chunk.transcribed = True
        chunk.transcribe_error = None
        chunk.envelope = envelope
        await chunk.save()

        await Event(
            study_id=chunk.session_id and study.id,
            session_id=chunk.session_id,
            participant_id=chunk.participant_id,
            t_ms=max(chunk.t_ms_start, 0),
            source=SOURCE_STUDIO,
            type="transcript_segment",
            meta={
                "transcript_id": str(transcript.id),
                "text": text,
                "n_words": len(words),
                "language": transcript.language,
            },
        ).insert()

    # ── model loading ───────────────────────────────────────────────

    async def _ensure_model(self, model_name: str):
        if self._model is not None and self._model_name == model_name:
            return self._model
        settings = get_settings()
        log.info(
            "loading faster-whisper model %s (device=%s, compute=%s)",
            model_name, settings.whisper_device, settings.whisper_compute_type,
        )
        loop = asyncio.get_event_loop()
        from faster_whisper import WhisperModel  # lazy import
        self._model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                model_name,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            ),
        )
        self._model_name = model_name
        return self._model


def _do_transcribe(model, file_path: str, language: str | None):
    """Run faster-whisper synchronously (called inside a thread executor).

    Returns ``(text, segments, info, mean_confidence, envelope)`` where each
    segment is a plain dict with a ``words`` list of ``{w, t_start_s, t_end_s}``,
    and ``envelope`` is a list of normalised RMS levels (one per 100 ms bin).
    """
    segments_iter, info = model.transcribe(
        file_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )
    out_segments: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    all_probs: list[float] = []
    for s in segments_iter:
        words_out: list[dict[str, Any]] = []
        for w in (s.words or []):
            if w.start is None or w.end is None:
                continue
            words_out.append({"w": w.word, "t_start_s": float(w.start), "t_end_s": float(w.end)})
            if w.probability is not None:
                all_probs.append(float(w.probability))
        full_text_parts.append(s.text)
        out_segments.append({"text": s.text, "words": words_out})
    mean_conf = sum(all_probs) / len(all_probs) if all_probs else None

    # Envelope: 100 ms RMS bins, normalised to [0, 1]. We re-read with soundfile
    # (cheap on the local filesystem) so we don't depend on Whisper's internal
    # frame buffer. Never let the envelope fail the transcription.
    envelope: list[float] = []
    try:
        import math as _math
        import soundfile as _sf
        data, sample_rate = _sf.read(file_path, dtype="float32", always_2d=True)
        if data.size:
            samples = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
            bin_n = max(1, int(sample_rate * 0.1))  # 100 ms windows
            for i in range(0, len(samples), bin_n):
                chunk = samples[i:i + bin_n]
                if len(chunk) == 0:
                    continue
                rms = _math.sqrt(float((chunk ** 2).mean()))
                envelope.append(rms)
            peak = max(envelope) if envelope else 0.0
            if peak > 0:
                envelope = [round(v / peak, 3) for v in envelope]
    except Exception:
        envelope = []

    return (
        "".join(full_text_parts).strip(),
        out_segments,
        {"language": info.language, "duration_s": float(info.duration)},
        mean_conf,
        envelope,
    )


whisper_worker = WhisperWorker()
