"""Server-side screen+mic video chunk ingest.

The participant's recorder shell POSTs ~5 second WebM chunks to
/ingest/video-chunk. This module mirrors ``studio.audio.recorder``:
  1. Persists the chunk under
     data/video/<study>/<session>/<participant>/<run>/chunk_<seq>.webm
  2. Inserts a VideoChunk doc with session-relative timestamps,
     so the admin replay scrubber drives the video + the event timeline together.
  3. Inserts a Studio Event row (type=video_chunk_received).

"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId

from studio.models import Event, Participant, Session, Study, VideoChunk
from studio.models.event import SOURCE_STUDIO
from studio.settings import get_settings

log = logging.getLogger("studio.video")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


CHUNK_NOMINAL_MS = 5000


def _to_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def run_id_for(recorder_started_wall: datetime) -> str:
    """Stable, filesystem-safe id for one MediaRecorder run.

    A recorder-shell refresh starts a fresh recorder (seq resets to 0); keying
    files + the unique index on this run id keeps those runs from colliding.
    """
    anchor = _to_naive(recorder_started_wall) or _utcnow_naive()
    return anchor.strftime("run_%Y%m%dT%H%M%S_%f")


async def ingest_video_chunk(
    session_id: PydanticObjectId,
    participant_id: PydanticObjectId,
    chunk_seq: int,
    recorder_started_wall: datetime,
    chunk_started_wall: datetime,
    blob: bytes,
    mime: str = "video/webm",
) -> VideoChunk:
    """Persist one video chunk and return the inserted VideoChunk document.

    The caller (HTTP route) verifies the participant cookie and reads the body.
    """
    settings = get_settings()

    if len(blob) > settings.video_max_chunk_bytes:
        raise ValueError(f"chunk size {len(blob)} exceeds cap {settings.video_max_chunk_bytes}")

    session = await Session.get(session_id)
    if session is None:
        raise ValueError("session not found")
    participant = await Participant.get(participant_id)
    if participant is None or participant.session_id != session_id:
        raise ValueError("participant not part of this session")
    study = await Study.get(session.study_id)
    if study is None:
        raise ValueError("study gone")
    if (study.recording or {}).get("video", "none") == "none":
        raise ValueError("video recording is disabled for this study")

    run = run_id_for(recorder_started_wall)
    out_dir = (
        settings.data_dir / "video"
        / str(session.study_id) / str(session.id) / str(participant.id) / run
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"chunk_{chunk_seq:06d}.webm"
    out_path.write_bytes(blob)

  
    anchor = _to_naive(session.va_started_at) or _to_naive(session.created_at) or _utcnow_naive()
    chunk_start = _to_naive(chunk_started_wall) or _utcnow_naive()
    t_ms_start = int((chunk_start - anchor).total_seconds() * 1000) - int(session.va_jsonl_offset_ms or 0)
    duration_seed = CHUNK_NOMINAL_MS
    t_ms_end = t_ms_start + duration_seed

    chunk = VideoChunk(
        session_id=session.id,
        participant_id=participant.id,
        run_id=run,
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

    # Backfill the PREVIOUS chunk's true duration: it ran until this one began.
    if chunk_seq > 0:
        prev = await VideoChunk.find_one(
            VideoChunk.session_id == session.id,
            VideoChunk.participant_id == participant.id,
            VideoChunk.run_id == run,
            VideoChunk.chunk_seq == chunk_seq - 1,
        )
        if prev is not None:
            real = min(t_ms_start - prev.t_ms_start, CHUNK_NOMINAL_MS)
            if 0 < real <= CHUNK_NOMINAL_MS:
                prev.duration_ms = real
                prev.t_ms_end = prev.t_ms_start + real
                await prev.save()

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
        type="video_chunk_received",
        meta={"chunk_id": str(chunk.id), "seq": chunk_seq, "run_id": run, "size_bytes": len(blob)},
    ).insert()

    return chunk
