"""One persisted batch of heart-rate samples from a participant's BLE strap."""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class HRSample(BaseModel):
    t_ms: int   # session-relative timestamp (see DESIGN §6.3)
    bpm: int


class BiometricChunk(Document):
    session_id: PydanticObjectId
    participant_id: PydanticObjectId

    chunk_seq: int                     # monotonic per participant
    batch_started_wall: datetime       # wall clock the client began this batch

    # Session-relative bounds (min/max of `samples[].t_ms`).
    t_ms_start: int = 0
    t_ms_end: int = 0

    samples: list[HRSample] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "biometric_chunks"
        indexes = [
            IndexModel([("participant_id", ASCENDING), ("chunk_seq", ASCENDING)], unique=True),
            IndexModel([("session_id", ASCENDING), ("t_ms_start", ASCENDING)]),
        ]
