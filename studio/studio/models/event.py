"""Unified timeline event. Stores both MIVAIS-sourced and Studio-sourced events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# source values
SOURCE_MIVAIS = "mivais"
SOURCE_STUDIO = "studio"


class Event(Document):
    study_id: PydanticObjectId
    session_id: PydanticObjectId
    participant_id: PydanticObjectId | None = None
    task_id: str | None = None
    block_id: str | None = None
    logging_id: str | None = None
    # Which VA system produced this event. None for Studio-emitted events
    # that aren't tied to a specific VA (session_created, task_start, ...).
    va_system_id: str | None = None

    t_ms: int                          # session-relative
    wall_clock: datetime = Field(default_factory=_utcnow)

    source: str                        # "mivais" | "studio"
    type: str
    meta: dict[str, Any] = Field(default_factory=dict)

    class Settings:
        name = "events"
        indexes = [
            IndexModel([("session_id", ASCENDING), ("t_ms", ASCENDING)]),
            IndexModel([("study_id", ASCENDING), ("source", ASCENDING), ("type", ASCENDING)]),
            IndexModel([("study_id", ASCENDING), ("logging_id", ASCENDING)]),
            IndexModel([("session_id", ASCENDING), ("va_system_id", ASCENDING), ("t_ms", ASCENDING)]),
        ]
