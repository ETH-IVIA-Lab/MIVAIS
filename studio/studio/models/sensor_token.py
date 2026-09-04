"""Session/participant-scoped bearer tokens for the external sensor ingest API.

Unlike ``ApiKey`` (global, read-only, for pulling data out via ``/api/v1``),
a ``SensorIngestToken`` is scoped to exactly one participant within one
session and only grants write access to ``POST /ingest/sensor-chunk`` — for
pushing data in from a non-browser device (lab rig, vendor SDK) that has no
access to the participant's browser cookie.

The raw token is shown ONCE at mint time; only its SHA-256 lands in the DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SensorIngestToken(Document):
    session_id: PydanticObjectId
    participant_id: PydanticObjectId

    label: str                         # human label, e.g. "Empatica E4 rig"
    token_hash: str                    # sha256 of the raw token
    prefix: str                        # first 12 chars, for display/identification
    created_by: str                    # admin username
    created_at: datetime = Field(default_factory=_utcnow)
    last_used_at: datetime | None = None
    revoked: bool = False

    class Settings:
        name = "sensor_ingest_tokens"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
            IndexModel([("session_id", ASCENDING), ("participant_id", ASCENDING)]),
        ]
