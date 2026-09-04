"""Server-side audio chunk ingest.

The participant's browser POSTs ~5 second WebM/Opus chunks to /ingest/audio-chunk.
This module:
  1. Validates the chunk + persists it under data/audio/<study>/<session>/<participant>/chunk_<seq>.webm
  2. Inserts an AudioChunk doc with session-relative timestamps
  3. Inserts a Studio Event row (source=audio, type=audio_chunk_received)
  4. Enqueues the chunk id for the Whisper worker (if transcription is enabled)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from beanie import PydanticObjectId

from studio.models import AudioChunk, Event, Participant, Session, Study
from studio.models.event import SOURCE_STUDIO
from studio.settings import get_settings

log = logging.getLogger("studio.audio")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def ingest_chunk(
    session_id: PydanticObjectId,
    participant_id: PydanticObjectId,
    chunk_seq: int,
    recorder_started_wall: datetime,
    chunk_started_wall: datetime,
    blob: bytes,
    mime: str = "audio/webm;codecs=opus",
) -> AudioChunk:
    """Persist one chunk and return the inserted AudioChunk document.

    The caller (HTTP route) is responsible for verifying the participant token
    and reading the multipart body. We trust the IDs we receive here.
    """
    settings = get_settings()

    if len(blob) > settings.audio_max_chunk_bytes:
        raise ValueError(f"chunk size {len(blob)} exceeds cap {settings.audio_max_chunk_bytes}")

    session = await Session.get(session_id)
    if session is None:
        raise ValueError("session not found")
    participant = await Participant.get(participant_id)
    if participant is None or participant.session_id != session_id:
        raise ValueError("participant not part of this session")
    study = await Study.get(session.study_id)
    if study is None:
        raise ValueError("study gone")
    # Quick refusal when audio is off for this study.
    if (study.recording or {}).get("audio", "none") == "none":
        raise ValueError("audio is disabled for this study")

    out_dir = (
        settings.data_dir / "audio"
        / str(session.study_id) / str(session.id) / str(participant.id)
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"chunk_{chunk_seq:06d}.webm"
    out_path.write_bytes(blob)

    # Session-relative timing per DESIGN §6.3:
    #   t_ms = (chunk_started_wall - session.va_started_at) - session.va_jsonl_offset_ms
    anchor = _to_naive(session.va_started_at) or _to_naive(session.created_at) or _utcnow_naive()
    chunk_start = _to_naive(chunk_started_wall) or _utcnow_naive()
    t_ms_start = int((chunk_start - anchor).total_seconds() * 1000) - int(session.va_jsonl_offset_ms or 0)
    # Duration is unknown until Whisper decodes; the participant sends ~5s chunks,
    # so seed with 5000 ms and let the worker correct on success.
    duration_seed = 5000
    t_ms_end = t_ms_start + duration_seed

    chunk = AudioChunk(
        session_id=session.id,
        participant_id=participant.id,
        chunk_seq=chunk_seq,
        recorder_started_wall=_to_naive(recorder_started_wall),
        chunk_started_wall=chunk_start,
        duration_ms=duration_seed,
        t_ms_start=t_ms_start,
        t_ms_end=t_ms_end,
        file_path=str(out_path),
        size_bytes=len(blob),
        mime=mime,
    )
    await chunk.insert()

    task_id = None
    if participant.task_runs and participant.task_runs[-1].ended_at is None:
        task_id = participant.task_runs[-1].task_id

    await Event(
        study_id=session.study_id,
        session_id=session.id,
        participant_id=participant.id,
        task_id=task_id,
        t_ms=max(t_ms_start, 0),
        source=SOURCE_STUDIO,
        type="audio_chunk_received",
        meta={"chunk_id": str(chunk.id), "seq": chunk_seq, "size_bytes": len(blob)},
    ).insert()

    # Hand off to the whisper worker if it's running.
    if (study.recording or {}).get("transcribe", False):
        from studio.audio.transcribe import whisper_worker
        whisper_worker.enqueue(chunk.id)

    return chunk
