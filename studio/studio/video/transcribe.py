"""On-demand transcription of a session's combined recording → WebVTT + JSON.

Reuses the audio pipeline's Whisper model loader + decode helper, but runs on the
single combined.webm (its opus track) rather than per-chunk, since video chunks
aren't independently decodable. Produces, next to combined.webm:
  - subtitles.vtt  → a native <track> the <video> renders as subtitles
  - transcript.json → {full_text, segments:[{start,end,text}]} for the side panel

Times are video-relative seconds (combined.webm starts at 0), so they line up
with the <video> element directly. Transcription runs in a background task and is
cached on disk; the replay page polls until it's ready.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("studio.video.transcribe")

_inflight: set[str] = set()

VTT_NAME = "subtitles.vtt"
JSON_NAME = "transcript.json"


def paths_for(combined_dir: Path) -> tuple[Path, Path]:
    return combined_dir / VTT_NAME, combined_dir / JSON_NAME


def _fmt_vtt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def segments_to_vtt(segments: list[dict[str, Any]]) -> str:
    out = ["WEBVTT", ""]
    for i, seg in enumerate(segments, 1):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append(str(i))
        out.append(f"{_fmt_vtt_time(seg['start'])} --> {_fmt_vtt_time(seg['end'])}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def status(combined_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    """Return ('ready', segments) | ('transcribing', []) | ('none', [])."""
    _vtt, jpath = paths_for(combined_dir)
    if jpath.exists():
        try:
            data = json.loads(jpath.read_text(encoding="utf-8"))
            return "ready", data.get("segments", [])
        except Exception:
            return "none", []
    if str(combined_dir) in _inflight:
        return "transcribing", []
    return "none", []


def ensure_started(combined_dir: Path, combined_path: Path, model_name: str, language: str) -> None:
    """Kick off background transcription if not already done / running."""
    key = str(combined_dir)
    _vtt, jpath = paths_for(combined_dir)
    if jpath.exists() or key in _inflight:
        return
    _inflight.add(key)
    asyncio.create_task(
        _run(combined_dir, combined_path, model_name, language),
        name=f"video-transcribe:{key}",
    )


async def _run(combined_dir: Path, combined_path: Path, model_name: str, language: str) -> None:
    key = str(combined_dir)
    vtt_path, json_path = paths_for(combined_dir)
    try:
        # Reuse the audio worker's model cache + synchronous decode helper.
        from studio.audio.transcribe import whisper_worker, _do_transcribe
        model = await whisper_worker._ensure_model(model_name)
        lang_arg = None if (language or "auto") == "auto" else language
        loop = asyncio.get_event_loop()
        text, raw_segments, info, _conf, _env = await loop.run_in_executor(
            None, _do_transcribe, model, str(combined_path), lang_arg,
        )
        MAX_CUE_S = 6.0
        MAX_CUE_WORDS = 12
        segments: list[dict[str, Any]] = []
        cur: list[dict[str, Any]] = []

        def _flush() -> None:
            if cur:
                segments.append({
                    "start": float(cur[0]["t_start_s"]),
                    "end": float(cur[-1]["t_end_s"]),
                    "text": " ".join((w.get("w") or "").strip() for w in cur).strip(),
                })

        for seg in raw_segments:
            words = seg.get("words") or []
            if not words:
                txt = (seg.get("text") or "").strip()
                if txt:
                    start = segments[-1]["end"] if segments else 0.0
                    segments.append({"start": start, "end": start + 2.0, "text": txt})
                continue
            for w in words:
                if cur and (float(w["t_end_s"]) - float(cur[0]["t_start_s"]) > MAX_CUE_S
                            or len(cur) >= MAX_CUE_WORDS):
                    _flush()
                    cur = []
                cur.append(w)
        _flush()
        segments = [s for s in segments if s["text"]]

        tmp_json = json_path.with_suffix(".json.tmp")
        tmp_json.write_text(
            json.dumps({"full_text": text, "language": (info or {}).get("language"), "segments": segments}),
            encoding="utf-8",
        )
        tmp_json.replace(json_path)
        tmp_vtt = vtt_path.with_suffix(".vtt.tmp")
        tmp_vtt.write_text(segments_to_vtt(segments), encoding="utf-8")
        tmp_vtt.replace(vtt_path)
        log.info("video transcript ready: %s (%d segments)", key, len(segments))
    except Exception as exc:
        log.warning("video transcription failed for %s: %s", key, exc)
    finally:
        _inflight.discard(key)
