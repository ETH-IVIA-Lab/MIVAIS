"""Async aggregation layer over the pure metrics engine.

Computes a study's declared metrics per participant (and per session) from
the persisted event stream. Evaluated lazily — no schema migration, old
sessions get metrics retroactively, and edited definitions re-compute on the
next call. Used by both the admin analytics endpoint and the public v1 API.
"""
from __future__ import annotations

import statistics
from typing import Any

from beanie import PydanticObjectId

from studio.metrics import compute_metrics
from studio.models import Event, Participant, Session, Study


def _event_dict(ev: Event) -> dict[str, Any]:
    return {
        "type": ev.type,
        "source": ev.source,
        "t_ms": ev.t_ms,
        "task_id": ev.task_id,
        "meta": ev.meta or {},
        "participant_id": str(ev.participant_id) if ev.participant_id else None,
    }


def _events_for_participant(session_events: list[dict[str, Any]], pid: str) -> list[dict[str, Any]]:
    """A participant's view of the session: their own events plus every event
    not attributed to any participant (VA/agent/system activity). In
    singleplayer that is the whole session; in multiplayer, shared unattributed
    events count for each member (documented approximation)."""
    return [ev for ev in session_events if ev["participant_id"] in (None, pid)]


async def compute_session_metrics(study: Study, session: Session) -> list[dict[str, Any]]:
    """Per-participant metric values for one session."""
    if not study.metrics:
        return []
    events = [
        _event_dict(ev)
        for ev in await Event.find(Event.session_id == session.id).sort("t_ms").to_list()
    ]
    participants = await Participant.find(Participant.session_id == session.id).to_list()
    out: list[dict[str, Any]] = []
    for p in participants:
        results = compute_metrics(study.metrics, _events_for_participant(events, str(p.id)))
        out.append({
            "participant_id": str(p.id),
            "anon_id": p.anon_id,
            "session_id": str(session.id),
            "metrics": results,
        })
    return out


async def compute_study_metrics(study: Study, session_id: PydanticObjectId | None = None) -> dict[str, Any]:
    """All sessions' per-participant values + per-metric aggregates."""
    if not study.metrics:
        return {"metrics": [], "participants": []}

    query = Session.find(Session.study_id == study.id)
    if session_id is not None:
        query = Session.find(Session.study_id == study.id, Session.id == session_id)
    sessions = await query.to_list()

    rows: list[dict[str, Any]] = []
    for session in sessions:
        rows.extend(await compute_session_metrics(study, session))

    # Aggregate per metric across participants (only non-null values).
    aggregates: list[dict[str, Any]] = []
    for defn in study.metrics:
        mid = defn.get("id")
        values = [
            m["value"]
            for row in rows
            for m in row["metrics"]
            if m["id"] == mid and m["value"] is not None
        ]
        first = next((m for row in rows for m in row["metrics"] if m["id"] == mid), None)
        aggregates.append({
            "id": mid,
            "label": (first or {}).get("label") or defn.get("label") or mid,
            "kind": defn.get("kind"),
            "unit": (first or {}).get("unit", ""),
            "n_participants": len(values),
            "mean": round(statistics.fmean(values), 3) if values else None,
            "median": round(statistics.median(values), 3) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        })

    return {"metrics": aggregates, "participants": rows}
