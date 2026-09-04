"""
AuditLog — Immutable provenance record for MIVAIS.

Every state write and every bus message is recorded here.
No clear() method exists — once written, entries are permanent.
The gateway pushes the tail of this log to connected clients on every update.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


class AuditEntry:
    __slots__ = ("id", "timestamp", "actor", "key", "value_repr", "accepted", "event_type")

    def __init__(
        self,
        actor: str,
        key: str,
        value_repr: str,
        accepted: bool,
        event_type: str,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.actor = actor
        self.key = key
        self.value_repr = value_repr
        self.accepted = accepted
        self.event_type = event_type  # "write" | "denied" | "bus_message" | "user_input"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "key": self.key,
            "value_repr": self.value_repr,
            "accepted": self.accepted,
            "event_type": self.event_type,
        }


class AuditLog:
    """
    Append-only provenance log.

    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(
        self,
        actor: str,
        key: str,
        value: Any = None,
        accepted: bool = True,
        event_type: str = "write",
    ) -> AuditEntry:
        """Record a world-state write attempt (accepted or denied)."""
        entry = AuditEntry(
            actor=actor,
            key=key,
            value_repr=_truncate(repr(value)),
            accepted=accepted,
            event_type=event_type,
        )
        self._entries.append(entry)
        return entry

    def record_bus_message(
        self,
        sender: str,
        topic: str,
        payload: Any = None,
    ) -> AuditEntry:
        """Record an inter-agent message passing through the MessageBus."""
        entry = AuditEntry(
            actor=sender,
            key=f"bus:{topic}",
            value_repr=_truncate(repr(payload)),
            accepted=True,
            event_type="bus_message",
        )
        self._entries.append(entry)
        return entry

    def get_entries(self, limit: int = 100) -> list[dict]:
        """Return the last `limit` entries as JSON-serialisable dicts."""
        return [e.to_dict() for e in self._entries[-limit:]]

    def get_all(self) -> list[dict]:
        """Return every entry as JSON-serialisable dicts."""
        return [e.to_dict() for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)


def _truncate(s: str, max_len: int = 150) -> str:
    return s if len(s) <= max_len else s[:max_len] + "…"
