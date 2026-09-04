"""API keys for the public read-only v1 API (external tool integration).

The raw token is shown ONCE at mint time; only its SHA-256 lands in the DB.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_token(prefix: str = "mvs_") -> str:
    """Format: ``<prefix><43 url-safe chars>`` — greppable, never logged in full.

    ``prefix`` distinguishes token kinds at a glance (e.g. ``mvs_`` for the
    global read-only API, ``mvss_`` for session-scoped sensor ingest tokens)
    so one can't be pasted where the other is expected.
    """
    return prefix + secrets.token_urlsafe(32)


class ApiKey(Document):
    name: str                          # human label ("R pipeline", "dashboard")
    token_hash: str                    # sha256 of the raw token
    prefix: str                        # first 12 chars, for display/identification
    created_by: str                    # admin username
    created_at: datetime = Field(default_factory=_utcnow)
    last_used_at: datetime | None = None
    revoked: bool = False

    class Settings:
        name = "api_keys"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
        ]
