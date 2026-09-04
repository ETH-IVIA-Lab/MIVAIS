"""One persisted audio chunk produced by a participant's MediaRecorder."""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AudioChunk(Document):
    session_id: PydanticObjectId
    participant_id: PydanticObjectId

    chunk_seq: int                                 # monotonic per participant
    recorder_started_wall: datetime | None = None  # wall clock the MediaRecorder began
    chunk_started_wall: datetime                   # wall clock for this chunk's first sample
    duration_ms: int = 0

    # Session-relative timestamps (computed on receipt; see DESIGN §6.3).
    t_ms_start: int = 0
    t_ms_end: int = 0

    file_path: str = ""
    size_bytes: int = 0
    mime: str = "audio/webm;codecs=opus"

    transcribed: bool = False
    transcribe_error: str | None = None

    # RMS energy per ~100 ms window, normalised to [0, 1]. Captured by the
    # Whisper worker once it has decoded the audio. Used to draw the level
    # strip in the replay viewer (no playback — DESIGN §13 forbids that).
    envelope: list[float] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "audio_chunks"
        indexes = [
            IndexModel([("participant_id", ASCENDING), ("chunk_seq", ASCENDING)], unique=True),
            IndexModel([("session_id", ASCENDING), ("t_ms_start", ASCENDING)]),
            IndexModel([("transcribed", ASCENDING), ("transcribe_error", ASCENDING)]),
        ]
