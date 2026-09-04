"""One transcript segment derived from an AudioChunk by the Whisper worker."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Transcript(Document):
    session_id: PydanticObjectId
    participant_id: PydanticObjectId
    audio_chunk_id: PydanticObjectId

    # Session-relative times (the audio chunk's t_ms_start is the anchor).
    t_ms_start: int = 0
    t_ms_end: int = 0

    text: str = ""
    # Each entry: { w: "word", t_start_ms: int, t_end_ms: int }
    words: list[dict[str, Any]] = Field(default_factory=list)

    language: str | None = None
    whisper_model: str = ""
    confidence: float | None = None  # average word probability when available

    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "transcripts"
        indexes = [
            IndexModel([("participant_id", ASCENDING), ("t_ms_start", ASCENDING)]),
            IndexModel([("session_id", ASCENDING), ("t_ms_start", ASCENDING)]),
            IndexModel([("audio_chunk_id", ASCENDING)], unique=True),
        ]
