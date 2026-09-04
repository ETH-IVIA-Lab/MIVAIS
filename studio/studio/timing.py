"""Shared session-relative timing helpers.

Three clocks need to agree (wall clock, MIVAIS recording clock, chunk
clock). Every ingest pipeline (audio, biometric, external sensor) normalizes 
wall-clock timestamps to session-relative ``t_ms`` the same way; 

"""
from __future__ import annotations

from datetime import datetime, timezone

from studio.models.session import Session


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def session_anchor(session: Session) -> datetime:
    """Wall-clock anchor session-relative t_ms is computed against."""
    return to_naive(session.va_started_at) or to_naive(session.created_at) or utcnow_naive()


def wall_to_session_ms(session: Session, wall: datetime) -> int:
    """Convert a wall-clock timestamp to session-relative t_ms, per DESIGN.md §6.3."""
    anchor = session_anchor(session)
    offset_ms = int(session.va_jsonl_offset_ms or 0)
    naive = to_naive(wall) or utcnow_naive()
    t_ms = int((naive - anchor).total_seconds() * 1000) - offset_ms
    return max(t_ms, 0)
