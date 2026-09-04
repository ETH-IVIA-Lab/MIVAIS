"""One persisted screen+mic recording chunk produced by a participant's MediaRecorder.

Mirrors :class:`AudioChunk` but for the session screen recording (video/webm with
an opus mic track). No transcription / envelope — these chunks are for visual
playback in the admin replay, time-synced to the event timeline via ``t_ms_start``.

Chunks are namespaced by ``run_id`` (derived from the recorder's start wall-clock):
a recorder-shell refresh starts a fresh MediaRecorder run, so its ``chunk_seq``
counter resets to 0 — ``run_id`` keeps those files (and the unique index) distinct.
"""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VideoChunk(Document):
    session_id: PydanticObjectId
    participant_id: PydanticObjectId

    run_id: str = ""                               # one MediaRecorder run (recorder start)
    chunk_seq: int                                 # monotonic per (participant, run)
    recorder_started_wall: datetime | None = None  # wall clock the MediaRecorder began
    chunk_started_wall: datetime                   # wall clock for this chunk's first frame
    duration_ms: int = 0

    # Session-relative timestamps (computed on receipt; see DESIGN §6.3) — shared
    # clock with Events, so the replay scrubber drives video + timeline together.
    t_ms_start: int = 0
    t_ms_end: int = 0

    file_path: str = ""
    size_bytes: int = 0
    mime: str = "video/webm"

    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "video_chunks"
        indexes = [
            IndexModel(
                [("participant_id", ASCENDING), ("run_id", ASCENDING), ("chunk_seq", ASCENDING)],
                unique=True,
            ),
            IndexModel([("session_id", ASCENDING), ("t_ms_start", ASCENDING)]),
        ]
