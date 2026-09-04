"""One persisted batch of samples from an external, non-browser sensor source."""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SensorSample(BaseModel):
    t_ms: int   # session-relative timestamp (see DESIGN §6.3)
    value: float


class SensorChunk(Document):
    session_id: PydanticObjectId
    participant_id: PydanticObjectId

    channel: str                       # free-form, developer-chosen (e.g. "eda", "resp_rate")
    unit: str | None = None            # informational, e.g. "uS", "breaths/min"

    chunk_seq: int                     # monotonic per (participant, channel)
    batch_started_wall: datetime       # wall clock the client began this batch

    # Session-relative bounds (min/max of `samples[].t_ms`).
    t_ms_start: int = 0
    t_ms_end: int = 0

    samples: list[SensorSample] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "sensor_chunks"
        indexes = [
            IndexModel(
                [("participant_id", ASCENDING), ("channel", ASCENDING), ("chunk_seq", ASCENDING)],
                unique=True,
            ),
            IndexModel([("session_id", ASCENDING), ("channel", ASCENDING), ("t_ms_start", ASCENDING)]),
        ]
