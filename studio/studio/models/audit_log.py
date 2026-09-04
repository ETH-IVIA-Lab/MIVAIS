"""Append-only log of admin actions.

Every state-changing admin route writes one entry. Read-only views (listing,
showing a session) do not emit entries — the log is for *changes*, not
inspection. This is what your supervisor or a future you will look at when
asking "who archived study X" or "who minted that code on Monday".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditEntry(Document):
    actor_username: str | None = None   # None → system (bootstrap, lifespan)
    action: str                          # e.g. "study.register", "code.toggle", "session.note"
    target_type: str | None = None       # "study", "code", "session", "admin_user", ...
    target_id: str | None = None         # stringified ObjectId or slug
    meta: dict[str, Any] = Field(default_factory=dict)

    ts: datetime = Field(default_factory=_utcnow)
    ip_hash: str | None = None
    request_id: PydanticObjectId | None = None  # optional correlation key

    class Settings:
        name = "audit_log"
        indexes = [
            IndexModel([("ts", DESCENDING)]),
            IndexModel([("actor_username", ASCENDING), ("ts", DESCENDING)]),
            IndexModel([("target_type", ASCENDING), ("target_id", ASCENDING), ("ts", DESCENDING)]),
            IndexModel([("action", ASCENDING), ("ts", DESCENDING)]),
        ]
