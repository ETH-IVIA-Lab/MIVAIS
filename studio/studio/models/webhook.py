"""Webhook endpoints registered against a study.

When configured events fire (session_completed / session_failed / participant_finished),
Studio POSTs a JSON envelope to ``url`` with an ``X-Studio-Signature: sha256=...``
HMAC over the body keyed on ``secret``. Receivers verify the signature to
reject spoofed deliveries.
"""
from __future__ import annotations

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Recognised event names. Adding here is the only contract for receivers.
WEBHOOK_EVENTS = frozenset({
    "session_completed",
    "session_failed",
    "session_started",
    "participant_finished",
    "code_minted",
})


class WebhookEndpoint(Document):
    study_id: PydanticObjectId
    url: str
    secret: str                              # HMAC signing key
    events: list[str] = Field(default_factory=lambda: ["session_completed"])
    # Delivery format. "studio" → the signed Studio JSON envelope (verify the
    # HMAC). "discord" → Studio formats a Discord message and POSTs it directly
    # to a Discord channel webhook URL (no signature; Discord doesn't verify).
    kind: str = "studio"
    active: bool = True

    description: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    last_delivery_at: datetime | None = None
    last_delivery_status: int | None = None  # HTTP status code returned by receiver
    delivery_count: int = 0
    failure_count: int = 0

    class Settings:
        name = "webhooks"
        indexes = [
            IndexModel([("study_id", ASCENDING)]),
            IndexModel([("active", ASCENDING)]),
        ]
