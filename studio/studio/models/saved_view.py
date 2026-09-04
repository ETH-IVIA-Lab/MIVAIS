"""Per-admin saved filter presets on the sessions index.

A SavedView captures the query string of a /admin/sessions filter combo
(study slug, status, tags, etc.) so an admin can hop between common views
without re-typing filters.
"""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SavedView(Document):
    owner_username: str
    name: str
    query: str                       # raw query string, e.g. "study=x&status=running&tag=woz"
    surface: str = "sessions"        # which page the view applies to
    created_at: datetime = Field(default_factory=_utcnow)

    class Settings:
        name = "saved_views"
        indexes = [
            IndexModel([("owner_username", ASCENDING), ("surface", ASCENDING)]),
        ]
