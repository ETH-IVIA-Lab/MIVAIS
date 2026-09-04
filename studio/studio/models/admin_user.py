from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminUser(Document):
    username: str
    pw_hash: str
    created_at: datetime = Field(default_factory=_utcnow)
    last_login: datetime | None = None

    class Settings:
        name = "admin_users"
        indexes = [IndexModel([("username", ASCENDING)], unique=True)]
