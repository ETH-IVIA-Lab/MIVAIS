"""Pure aggregation helpers for the admin pages.

Each function takes already-loaded documents (or queries Mongo through Beanie)
and returns plain dicts ready to serialize as JSON.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from beanie import PydanticObjectId
from beanie.operators import In

from studio.metrics import _matches as _taxonomy_matches
from studio.models import Event, Participant, Session, Study, Transcript
from studio.video.recorder import CHUNK_NOMINAL_MS as VIDEO_CHUNK_NOMINAL_MS


# ── overall (for /admin/) ─────────────────────────────────────────────────

async def overview_stats() -> dict[str, Any]:
    """Top-of-page counters for the studies list page."""
    n_studies = await Study.find(Study.archived == False).count()  # noqa: E712
    n_sessions = await Session.find().count()
    n_completed = await Session.find(Session.status == "completed").count()
    n_participants = await Participant.find().count()
    n_finished = await Participant.find(Participant.status == "finished").count()
    n_events = await Event.find().count()
    return {
        "n_studies": n_studies,
        "n_sessions": n_sessions,
        "n_sessions_completed": n_completed,
        "n_participants": n_participants,
        "n_participants_finished": n_finished,
        "n_events": n_events,
        "completion_rate": (n_finished / n_participants) if n_participants else 0.0,
    }


async def sessions_timeseries(days: int = 14) -> list[dict[str, Any]]:
    """Daily session counts for the last `days` days (for the dashboard chart).

    Returns one entry per day (oldest → newest), each:
        {"date": "YYYY-MM-DD", "label": "DD/MM", "total": int, "completed": int}
    Days with no sessions are included as zeros so the line chart is continuous.
    """
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    buckets: dict[str, dict[str, int]] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        buckets[d.isoformat()] = {"total": 0, "completed": 0}

    sessions = await Session.find().to_list()
    for s in sessions:
        created = s.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        key = created.date().isoformat()
        if key in buckets:
            buckets[key]["total"] += 1
            if s.status == "completed":
                buckets[key]["completed"] += 1

    out: list[dict[str, Any]] = []
    for key in sorted(buckets):
        y, m, d = key.split("-")
        out.append({
            "date": key,
            "label": f"{d}/{m}",
            "total": buckets[key]["total"],
            "completed": buckets[key]["completed"],
        })
    return out


async def session_status_breakdown() -> list[dict[str, Any]]:
    """Count sessions by status, ordered for a donut chart. Empty buckets dropped."""
    sessions = await Session.find().to_list()
    counts = Counter(s.status for s in sessions)
    # Stable, meaningful order; only emit statuses that actually occur.
    order = ["completed", "running", "lobby", "spawning", "pending", "interrupted", "failed"]
    out = [{"status": st, "count": counts[st]} for st in order if counts.get(st)]
    # Any unexpected statuses appended at the end.
    for st, n in counts.items():
        if st not in order and n:
            out.append({"status": st, "count": n})
    return out


def _fmt_duration(seconds: float) -> str:
    """Human-friendly compact duration, e.g. '4m 12s', '1h 03m', '0s'."""
    s = int(round(seconds))
    if s <= 0:
        return "0s"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


async def dashboard_extras() -> dict[str, Any]:
    """Extra at-a-glance dashboard metrics, computed from one sessions load.

    Complements :func:`overview_stats` with operational + research-flavoured
    numbers: how many sessions are live right now, recent volume, mean session
    length, the singleplayer/multiplayer split, dropped sessions, and how many
    reviewer annotations (markers + notes) have been left.
    """
    from datetime import timedelta

    sessions = await Session.find().to_list()
    now = datetime.now(timezone.utc)
    today = now.date()
    week_ago = today - timedelta(days=6)

    active_states = {"running", "spawning", "lobby"}
    dead_states = {"abandoned", "failed", "interrupted"}

    active_now = today_count = week_count = n_abandoned = 0
    n_markers = n_notes = 0
    by_mode: dict[str, int] = {"singleplayer": 0, "multiplayer": 0}
    durations: list[float] = []

    for s in sessions:
        if s.status in active_states:
            active_now += 1
        if s.status in dead_states:
            n_abandoned += 1
        by_mode[s.mode] = by_mode.get(s.mode, 0) + 1

        created = s.created_at
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        d = created.date()
        if d == today:
            today_count += 1
        if d >= week_ago:
            week_count += 1

        n_markers += len(s.markers or [])
        n_notes += len(s.notes or [])

        if s.va_started_at and s.ended_at:
            a = s.va_started_at.replace(tzinfo=None) if s.va_started_at.tzinfo else s.va_started_at
            b = s.ended_at.replace(tzinfo=None) if s.ended_at.tzinfo else s.ended_at
            secs = (b - a).total_seconds()
            if secs > 0:
                durations.append(secs)

    avg_duration_s = (sum(durations) / len(durations)) if durations else 0.0
    return {
        "active_now": active_now,
        "sessions_today": today_count,
        "sessions_7d": week_count,
        "n_abandoned": n_abandoned,
        "by_mode": by_mode,
        "n_markers": n_markers,
        "n_notes": n_notes,
        "n_annotations": n_markers + n_notes,
        "avg_duration_s": avg_duration_s,
        "avg_duration_human": _fmt_duration(avg_duration_s),
        "n_with_duration": len(durations),
    }


# ── per-study (for /admin/studies/<slug>) ─────────────────────────────────

async def study_stats(study: Study) -> dict[str, Any]:
    sessions = await Session.find(Session.study_id == study.id).to_list()
    participants = await Participant.find(Participant.study_id == study.id).to_list()
    n_events = await Event.find(Event.study_id == study.id).count()
    n_mivais = await Event.find(Event.study_id == study.id, Event.source == "mivais").count()
    n_studio = await Event.find(Event.study_id == study.id, Event.source == "studio").count()

    completed_sessions = [s for s in sessions if s.status == "completed" and s.ended_at and s.va_started_at]
    durations = []
    for s in completed_sessions:
        started = s.va_started_at.replace(tzinfo=None) if s.va_started_at.tzinfo else s.va_started_at
        ended = s.ended_at.replace(tzinfo=None) if s.ended_at.tzinfo else s.ended_at
        durations.append((ended - started).total_seconds())

    n_finished = sum(1 for p in participants if p.status == "finished")

    return {
        "n_sessions": len(sessions),
        "n_sessions_completed": len(completed_sessions),
        "n_sessions_in_progress": sum(1 for s in sessions if s.status in ("running", "spawning")),
        "n_sessions_failed": sum(1 for s in sessions if s.status == "failed"),
        "n_participants": len(participants),
        "n_participants_finished": n_finished,
        "completion_rate": (n_finished / len(participants)) if participants else 0.0,
        "mean_duration_s": statistics.mean(durations) if durations else 0.0,
        "median_duration_s": statistics.median(durations) if durations else 0.0,
        "n_events": n_events,
        "n_events_mivais": n_mivais,
        "n_events_studio": n_studio,
        "last_session_at": max((s.created_at for s in sessions), default=None),
    }


async def per_task_summary(study: Study) -> list[dict[str, Any]]:
    """Aggregate over every participant's task_runs for this study.

    Returns one row per task in the study YAML, even if no one has reached it.
    """
    # Flatten the study's tasks for the schema
    tasks_in_order: list[tuple[str, str, str, dict]] = []  # (task_id, type, block_id, task_dict)
    for block in study.blocks:
        for task in block.get("tasks", []):
            tasks_in_order.append((task["id"], task["type"], block.get("id", ""), task))

    # Pull every participant's task_runs
    participants = await Participant.find(Participant.study_id == study.id).to_list()
    runs_by_task: dict[str, list[Any]] = defaultdict(list)
    for p in participants:
        for r in p.task_runs:
            runs_by_task[r.task_id].append(r)

    rows: list[dict[str, Any]] = []
    for task_id, task_type, block_id, task_dict in tasks_in_order:
        runs = [r for r in runs_by_task.get(task_id, []) if r.ended_at is not None]
        durations_ms = [r.duration_ms for r in runs if r.duration_ms is not None]
        gt = task_dict.get("ground_truth")
        with_score = [r for r in runs if r.score is not None]
        correct_count = sum(1 for r in with_score if r.correct)

        rows.append({
            "task_id": task_id,
            "type": task_type,
            "block_id": block_id,
            "n_runs": len(runs),
            "n_timed_out": sum(1 for r in runs if r.timed_out),
            "n_skipped": sum(1 for r in runs if r.skipped),
            "mean_duration_ms": int(statistics.mean(durations_ms)) if durations_ms else 0,
            "median_duration_ms": int(statistics.median(durations_ms)) if durations_ms else 0,
            "has_ground_truth": gt is not None,
            "n_with_score": len(with_score),
            "correct_rate": (correct_count / len(with_score)) if with_score else 0.0,
            "mean_score": statistics.mean(r.score for r in with_score) if with_score else 0.0,
            "answer_distribution": _answer_distribution(task_dict, runs),
        })
    return rows


def _answer_distribution(task: dict[str, Any], runs: list[Any]) -> list[dict[str, Any]]:
    """Build a small distribution suitable for an inline bar chart.

    Returns a list of {label, count, percent}. Empty list when distribution is
    not meaningful for the task type.
    """
    if not runs:
        return []
    ttype = task["type"]
    if ttype == "single_choice":
        counter = Counter(r.answer for r in runs if r.answer is not None)
        total = sum(counter.values()) or 1
        options = task.get("options", [])
        if options:
            return [
                {"label": opt.get("label", opt.get("id", "")),
                 "count": counter.get(opt.get("id"), 0),
                 "percent": round(counter.get(opt.get("id"), 0) / total * 100, 1)}
                for opt in options
            ]
        return [{"label": str(v), "count": c, "percent": round(c / total * 100, 1)}
                for v, c in counter.most_common()]
    if ttype == "multi_choice":
        counter: Counter[str] = Counter()
        for r in runs:
            if isinstance(r.answer, list):
                counter.update(r.answer)
        options = task.get("options", [])
        if options:
            return [
                {"label": opt.get("label", opt.get("id", "")),
                 "count": counter.get(opt.get("id"), 0),
                 "percent": round(counter.get(opt.get("id"), 0) / max(len(runs), 1) * 100, 1)}
                for opt in options
            ]
        return []
    if ttype == "likert":
        # Show mean per item, scaled
        out = []
        scale_min = task.get("scale", {}).get("min", 1)
        scale_max = task.get("scale", {}).get("max", 7)
        for item in task.get("items", []):
            values = [r.answer[item["id"]] for r in runs
                      if isinstance(r.answer, dict) and item["id"] in r.answer]
            if values:
                mean = statistics.mean(values)
                pct = (mean - scale_min) / (scale_max - scale_min) * 100
                out.append({"label": item.get("label", item["id"]),
                            "count": round(mean, 2),
                            "percent": round(pct, 1)})
        return out
    if ttype in ("slider", "number_input"):
        values = [float(r.answer) for r in runs if isinstance(r.answer, (int, float))]
        if not values:
            return []
        mean = statistics.mean(values)
        lo, hi = task.get("min"), task.get("max")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > lo:
            pct = (mean - lo) / (hi - lo) * 100
        else:
            top = max(abs(v) for v in values)
            pct = (abs(mean) / top * 100) if top else 0.0
        return [{"label": f"mean of {len(values)} answers",
                 "count": round(mean, 2),
                 "percent": round(max(0.0, min(100.0, pct)), 1)}]
    return []


# ── per-session (for /admin/sessions/<id>) ────────────────────────────────

async def session_recording(session: Session) -> dict[str, Any]:
    """Everything the session detail page needs to render the full recording."""
    participants = await Participant.find(Participant.session_id == session.id).to_list()

    # All events for this session in chronological order, with no row cap.
    events = await Event.find(Event.session_id == session.id).sort("+t_ms").to_list()

    # Group events by task_id (events without a task_id go into "session" bucket)
    events_by_task: dict[str | None, list[Event]] = defaultdict(list)
    for e in events:
        events_by_task[e.task_id].append(e)

    # Source/type breakdowns
    source_counts = Counter(e.source for e in events)
    type_counts = Counter(e.type for e in events).most_common(12)

    final_state = None
    for e in reversed(events):
        if e.source == "mivais" and e.type in ("state_update", "snapshot"):
            payload = e.meta or {}
            if "world_state" in payload:
                final_state = payload["world_state"]
                break

    # Duration
    duration_s = None
    if session.va_started_at and session.ended_at:
        s = session.va_started_at.replace(tzinfo=None) if session.va_started_at.tzinfo else session.va_started_at
        e = session.ended_at.replace(tzinfo=None) if session.ended_at.tzinfo else session.ended_at
        duration_s = (e - s).total_seconds()


    per_task: list[dict[str, Any]] = []
    for p in participants:
        for r in p.task_runs:
            task_events = events_by_task.get(r.task_id, [])
            n_mivais = sum(1 for ev in task_events if ev.source == "mivais")
            n_studio = sum(1 for ev in task_events if ev.source == "studio")
            per_task.append({
                "participant_id": str(p.id),
                "participant_anon": p.anon_id,
                "task_id": r.task_id,
                "task_index": r.task_index,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "duration_ms": r.duration_ms,
                "answer": r.answer,
                "score": r.score,
                "correct": r.correct,
                "timed_out": r.timed_out,
                "skipped": r.skipped,
                "n_events_total": len(task_events),
                "n_events_mivais": n_mivais,
                "n_events_studio": n_studio,
            })
    per_task.sort(key=lambda row: (row["participant_anon"], row["task_index"]))

    return {
        "events": events,
        "events_by_task": dict(events_by_task),
        "source_counts": source_counts,
        "type_counts": type_counts,
        "final_state": final_state,
        "duration_s": duration_s,
        "n_events_total": len(events),
        "per_task": per_task,
        "participants": participants,
    }


def timeline_density(events: list[Event], n_buckets: int = 60) -> list[dict[str, int]]:
    """Return a small list of {t_ms, n} buckets for an SVG density strip."""
    if not events:
        return []
    t_max = max(e.t_ms for e in events)
    if t_max <= 0:
        return [{"t_ms": 0, "n": len(events)}]
    bucket_size = max(1, t_max // n_buckets)
    counts: dict[int, int] = defaultdict(int)
    for e in events:
        counts[e.t_ms // bucket_size] += 1
    return [{"t_ms": k * bucket_size, "n": v} for k, v in sorted(counts.items())]


# ── replay payload (for /admin/replay/<id>) ──────────────────────────────

async def participant_journey(participant: Participant) -> dict[str, Any]:
    """Full per-participant deep-dive: every task they touched, every event."""
    session = await Session.find_one(Session.id == participant.session_id)
    study = await Study.find_one(Study.id == participant.study_id)
    events = await Event.find(Event.participant_id == participant.id).sort("+t_ms").to_list()
    # Bucket events by task_id so the timeline groups tightly.
    by_task: dict[str | None, list[Event]] = defaultdict(list)
    for e in events:
        by_task[e.task_id].append(e)

    # Walk task_runs in the participant's applied order; attach events.
    rows: list[dict[str, Any]] = []
    for run in participant.task_runs:
        rows.append({
            "task_index": run.task_index,
            "task_id": run.task_id,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "duration_ms": run.duration_ms,
            "answer": run.answer,
            "score": run.score,
            "correct": run.correct,
            "timed_out": run.timed_out,
            "skipped": run.skipped,
            "checked_steps": list(run.checked_steps or []),
            "n_events": len(by_task.get(run.task_id, [])),
            "n_mivais": sum(1 for e in by_task.get(run.task_id, []) if e.source == "mivais"),
            "n_studio": sum(1 for e in by_task.get(run.task_id, []) if e.source == "studio"),
        })

    # Final WorldState participant saw (best-effort from latest snapshot).
    final_state = None
    for e in reversed(events):
        if e.source == "mivais" and e.type in ("state_update", "snapshot"):
            payload = e.meta or {}
            if "world_state" in payload:
                final_state = payload["world_state"]
                break

    # Transcript: roll up to text-only for compactness.
    transcripts = await Transcript.find(
        Transcript.participant_id == participant.id
    ).sort("+t_ms_start").to_list()

    return {
        "participant": participant,
        "session": session,
        "study": study,
        "task_runs": rows,
        "events": events,
        "transcripts": transcripts,
        "final_state": final_state,
        "n_events": len(events),
    }


async def study_funnel(study: Study) -> list[dict[str, Any]]:
    """Drop-off funnel: how many participants reached each milestone.

    Stages: joined → consented → role_assigned → in_session → finished.
    `dropped` is reported as a side count, not a stage.
    """
    participants = await Participant.find(Participant.study_id == study.id).to_list()
    n = len(participants)
    n_consented = sum(1 for p in participants if p.consented_at is not None)
    n_role     = sum(1 for p in participants if p.role)
    n_in_sess  = sum(1 for p in participants if p.status in ("in_session", "finished"))
    n_finished = sum(1 for p in participants if p.status == "finished")
    n_dropped  = sum(1 for p in participants if p.status == "dropped")
    stages = [
        {"name": "Joined",       "count": n,           "pct": 100.0},
        {"name": "Consented",    "count": n_consented, "pct": (n_consented / n * 100) if n else 0},
        {"name": "Role assigned","count": n_role,      "pct": (n_role / n * 100) if n else 0},
        {"name": "In session",   "count": n_in_sess,   "pct": (n_in_sess / n * 100) if n else 0},
        {"name": "Finished",     "count": n_finished,  "pct": (n_finished / n * 100) if n else 0},
    ]
    # Avoid impossible upward drift if status math underflows.
    for i in range(1, len(stages)):
        if stages[i]["count"] > stages[i - 1]["count"]:
            stages[i]["count"] = stages[i - 1]["count"]
            stages[i]["pct"] = stages[i - 1]["pct"]
    return [*stages, {"name": "Dropped (any stage)", "count": n_dropped,
                       "pct": (n_dropped / n * 100) if n else 0, "_alt": True}]


async def per_task_drilldown(study: Study, task_id: str) -> dict[str, Any]:
    """Detailed breakdown for one task across every participant in a study.

    Returns:
      - task: the resolved task dict (or None if it's gone)
      - n_runs, durations: list of duration_ms across completed runs
      - answers: list of raw answers
      - distribution: precomputed for single/multi/likert (see _answer_distribution)
      - duration_buckets: histogram (10 buckets) over duration_ms
      - likert_heatmap: per-item × per-step counts (for likert tasks)
    """
    task = None
    for block in study.blocks or []:
        for t in block.get("tasks", []):
            if t.get("id") == task_id:
                task = t
                break
        if task:
            break

    participants = await Participant.find(Participant.study_id == study.id).to_list()
    runs = [r for p in participants for r in p.task_runs
            if r.task_id == task_id and r.ended_at is not None]

    durations = [r.duration_ms for r in runs if r.duration_ms is not None and r.duration_ms > 0]
    answers = [r.answer for r in runs if r.answer is not None]
    scores = [r.score for r in runs if r.score is not None]
    correct_n = sum(1 for r in runs if r.correct)

    # Duration histogram (10 buckets between min and max).
    dur_buckets: list[dict[str, Any]] = []
    if durations:
        dmin, dmax = min(durations), max(durations)
        span = max(dmax - dmin, 1)
        n_bins = min(10, max(1, len(durations)))
        bin_w = span / n_bins
        counts = [0] * n_bins
        for d in durations:
            idx = min(int((d - dmin) // max(bin_w, 1)), n_bins - 1)
            counts[idx] += 1
        for i, c in enumerate(counts):
            dur_buckets.append({
                "lo_ms": int(dmin + i * bin_w),
                "hi_ms": int(dmin + (i + 1) * bin_w),
                "count": c,
            })

    distribution = _answer_distribution(task or {}, runs) if task else []

    # Likert heatmap: rows = items, cols = scale values, cells = counts.
    likert_heatmap: dict[str, Any] | None = None
    if task and task.get("type") == "likert":
        scale = task.get("scale", {})
        s_min = int(scale.get("min", 1))
        s_max = int(scale.get("max", 7))
        items = task.get("items", [])
        cells: list[list[int]] = [[0] * (s_max - s_min + 1) for _ in items]
        for r in runs:
            if not isinstance(r.answer, dict):
                continue
            for ii, item in enumerate(items):
                v = r.answer.get(item.get("id"))
                if isinstance(v, (int, float)) and s_min <= v <= s_max:
                    cells[ii][int(v) - s_min] += 1
        likert_heatmap = {
            "items": [{"id": it.get("id"), "label": it.get("label", it.get("id", ""))} for it in items],
            "scale_min": s_min,
            "scale_max": s_max,
            "cells": cells,
            "row_max": [max(row) if row else 0 for row in cells],
        }

    return {
        "task": task,
        "n_runs": len(runs),
        "n_timed_out": sum(1 for r in runs if r.timed_out),
        "n_skipped": sum(1 for r in runs if r.skipped),
        "n_correct": correct_n,
        "n_with_score": len(scores),
        "correct_rate": (correct_n / len(scores)) if scores else 0.0,
        "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
        "mean_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
        "median_duration_ms": (sorted(durations)[len(durations)//2]) if durations else 0,
        "distribution": distribution,
        "duration_buckets": dur_buckets,
        "likert_heatmap": likert_heatmap,
        "answers": answers,
        "runs": runs,
        "participants_by_run": [
            next((p for p in participants if any(r.task_id == task_id for r in p.task_runs)), None)
            for _ in runs
        ],
    }


async def compare_studies(study_slugs: list[str], task_id: str | None = None) -> dict[str, Any]:
    """Side-by-side metrics for the same task across multiple studies.

    Either pin to a specific task_id (recommended — needs the task to exist in
    every study) or, when task_id is None, return per-study summary rows.

    When **exactly two** studies are compared on a specific task, also returns
    inferential statistics (Welch's t-test, Cohen's d, Mann–Whitney U) on the
    duration distributions in ``inference``.
    """
    from studio import stats as stats_mod

    studies = []
    for slug in study_slugs:
        s = await Study.find_one(Study.slug == slug)
        if s is not None:
            studies.append(s)
    rows: list[dict[str, Any]] = []
    raw_durations: list[list[float]] = []
    for s in studies:
        if task_id:
            d = await per_task_drilldown(s, task_id)
            durations = [r.duration_ms for r in (d.get("runs") or [])
                         if r.duration_ms is not None and r.duration_ms > 0]
            raw_durations.append(durations)
            rows.append({
                "study": s,
                "task_id": task_id,
                "task_found": d["task"] is not None,
                "n_runs": d["n_runs"],
                "mean_duration_ms": d["mean_duration_ms"],
                "median_duration_ms": d["median_duration_ms"],
                "correct_rate": d["correct_rate"],
                "n_timed_out": d["n_timed_out"],
                "n_skipped": d["n_skipped"],
                "distribution": d["distribution"],
            })
        else:
            stats = await study_stats(s)
            rows.append({
                "study": s,
                "task_id": None,
                "n_sessions": stats["n_sessions"],
                "n_sessions_completed": stats["n_sessions_completed"],
                "n_participants": stats["n_participants"],
                "n_participants_finished": stats["n_participants_finished"],
                "completion_rate": stats["completion_rate"],
                "mean_duration_s": stats["mean_duration_s"],
                "n_events": stats["n_events"],
            })

    inference = None
    if task_id and len(studies) == 2:
        a, b = raw_durations[0], raw_durations[1]
        if len(a) >= 2 and len(b) >= 2:
            inference = {
                "metric": "duration_ms",
                "label_a": studies[0].name,
                "label_b": studies[1].name,
                "welch": stats_mod.welch_t_test(a, b),
                "cohens_d": stats_mod.cohens_d(a, b),
                "mann_whitney": stats_mod.mann_whitney_u(a, b),
                "n_a": len(a),
                "n_b": len(b),
            }

    return {
        "studies": studies, "rows": rows, "task_id": task_id,
        "inference": inference,
    }


async def replay_payload(session: Session) -> dict[str, Any]:
    """Build a single JSON blob the replay viewer streams events from.

    Compact by design: every WorldState snapshot is shipped exactly once,
    indexed by its position in the event timeline; smaller events
    (cursor_update, task_*) are shipped without modification.
    """
    events = await Event.find(Event.session_id == session.id).sort("+t_ms").to_list()

   
    _participants = await Participant.find(Participant.session_id == session.id).to_list()
    participants = {str(p.id): {"anon_id": p.anon_id, "role": p.role} for p in _participants}

    
    study = await Study.get(session.study_id)
    task_va: dict[str, str | None] = {}
    if study is not None:
        primary = study.primary_va_system
        for block in (study.blocks or []):
            for t in block.get("tasks", []):
                wants_va = t.get("type") == "va_interaction" or t.get("with_va", False)
                task_va[t["id"]] = (t.get("va_system") or primary) if wants_va else None

    
    replay_cfg = (study.replay or {}) if study is not None else {}
    event_type_rules: list[dict[str, Any]] = replay_cfg.get("event_types") or []

    EXCLUDE = {"dataset"}

    timeline: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []  # index → world_state

    for ev in events:
        item: dict[str, Any] = {
            "t_ms": ev.t_ms,
            "source": ev.source,
            "type": ev.type,
            "task_id": ev.task_id,
            "participant_id": str(ev.participant_id) if ev.participant_id else None,
        }
        if ev.va_system_id:
            item["va"] = ev.va_system_id
        meta = ev.meta or {}

        if event_type_rules:
            match_target = {"type": ev.type, "source": ev.source, "meta": meta}
            for rule in event_type_rules:
                if _taxonomy_matches(rule.get("match"), match_target):
                    item["taxonomy_category"] = rule.get("category")
                    if rule.get("label"):
                        item["taxonomy_label"] = rule["label"]
                    break

        if ev.source == "mivais" and ev.type in ("snapshot", "state_update") and "world_state" in meta:
            ws = {k: v for k, v in meta["world_state"].items() if k not in EXCLUDE}
            # Audit tail is large; drop here, the participant's event log shows it.
            snapshots.append(ws)
            item["snapshot_index"] = len(snapshots) - 1
        elif ev.source == "mivais" and ev.type == "cursor_update":
            item["cursors"] = meta.get("cursors") or {}
        elif ev.source == "mivais" and ev.type == "user_action":
            item["meta"] = {
                "actor": meta.get("actor"),
                "action": meta.get("action"),
                "data": meta.get("data"),
            }
        elif ev.source == "mivais" and ev.type == "agent_action":
            
            item["meta"] = {
                "actor": meta.get("actor"),
                "key": meta.get("key"),
                "event_type": meta.get("event_type"),
                "value_repr": meta.get("value_repr"),
                "accepted": meta.get("accepted"),
            }
        elif ev.source == "mivais" and ev.type == "bus_message":
            
            import json as _json
            payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
            try:
                pretty = _json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            except Exception:
                pretty = str(payload)
            item["meta"] = {
                "sender": meta.get("sender"),
                "topic": meta.get("topic"),
                "text": payload.get("text"),
                "payload_preview": pretty[:4000],
            }
        elif ev.source == "studio":
            item["meta"] = meta

        timeline.append(item)


    t_max = max((e.t_ms for e in events), default=0)


    from studio.models import AudioChunk
    chunks = await AudioChunk.find(AudioChunk.session_id == session.id).sort("+t_ms_start").to_list()
    audio_strip = [
        {
            "participant_id": str(c.participant_id),
            "t_ms_start": c.t_ms_start,
            "t_ms_end": c.t_ms_end,
            "envelope": list(c.envelope or []),
        }
        for c in chunks if c.envelope
    ]

    from studio.models import VideoChunk
    vchunks = await VideoChunk.find(VideoChunk.session_id == session.id).to_list()
    video = None
    videos: list[dict[str, Any]] = []
    if vchunks:
        by_run: dict[str, list[VideoChunk]] = defaultdict(list)
        for c in vchunks:
            by_run[c.run_id].append(c)
        rec = (study.recording or {}) if study else {}

        transcribe = bool(rec.get("transcribe")) and rec.get("audio", "none") != "none"
        # Label each POV by its participant (anon id + role) for the switcher.
        p_by_id = {p.id: p for p in _participants}

        for run_id, chunks in sorted(by_run.items(), key=lambda kv: len(kv[1]), reverse=True):
            pid = chunks[0].participant_id
            p = p_by_id.get(pid)
            label = (p.anon_id if p else "participant")
            if p and p.role:
                label += f" · {p.role}"
            ordered = sorted(chunks, key=lambda c: (c.chunk_seq, c.t_ms_start))
            segments: list[dict[str, int]] = []
            video_t = 0
            for i, c in enumerate(ordered):
                own = int(c.duration_ms or 0) or max(0, c.t_ms_end - c.t_ms_start)
                if i + 1 < len(ordered):
                    delta = ordered[i + 1].t_ms_start - c.t_ms_start
                    # A short final flush chunk is shorter than the timeslice;
                    # anything longer is a gap.
                    dur = min(delta, VIDEO_CHUNK_NOMINAL_MS) if delta > 0 else own
                else:
                    dur = min(own, VIDEO_CHUNK_NOMINAL_MS) if own > 0 else VIDEO_CHUNK_NOMINAL_MS
                if dur <= 0:
                    dur = VIDEO_CHUNK_NOMINAL_MS
                segments.append({"t_ms": c.t_ms_start, "video_t_ms": video_t, "dur_ms": dur})
                video_t += dur

            videos.append({
                "run_id": run_id,
                "participant_id": str(pid) if pid else None,
                "label": label,
                "src": f"/admin/sessions/{session.id}/video?run={run_id}",
                "start_t_ms": ordered[0].t_ms_start,
                "t_ms_end": segments[-1]["t_ms"] + segments[-1]["dur_ms"] if segments else 0,
                "duration_ms": video_t,        # total playable length
                "segments": segments,
                "transcribe": transcribe,
            })
        video = videos[0] if videos else None


    from studio.models import BiometricChunk
    bio_chunks = await BiometricChunk.find(BiometricChunk.session_id == session.id).sort("+t_ms_start").to_list()
    heart_rate = [
        {"participant_id": str(c.participant_id), "t_ms": s.t_ms, "bpm": s.bpm}
        for c in bio_chunks
        for s in c.samples
    ]

    # External sensor samples, flattened per named channel across all of this
    # session's SensorChunk batches — one strip per channel in the replay UI.
    from studio.models import SensorChunk
    sensor_chunks = await SensorChunk.find(SensorChunk.session_id == session.id).sort("+t_ms_start").to_list()
    sensor_channels: dict[str, list[dict]] = {}
    for c in sensor_chunks:
        bucket = sensor_channels.setdefault(c.channel, [])
        for s in c.samples:
            bucket.append({"participant_id": str(c.participant_id), "t_ms": s.t_ms, "value": s.value})

    if videos:
        t_max = max([t_max] + [int(v["t_ms_end"]) for v in videos])

    return {
        "session_id": str(session.id),
        "t_max": t_max,
        "timeline": timeline,
        "snapshots": snapshots,
        "n_events": len(events),
        "audio_strip": audio_strip,
        "video": video,     # primary POV (back-compat)
        "videos": videos,   # all POVs (one per participant run)
        "participants": participants,  # id → {anon_id, role} for per-user lanes
        "task_va": task_va,  # task_id → va_system on screen (None = no VA)
        "heart_rate": heart_rate,  # flattened BLE heart-rate samples for the replay curve
        "sensor_channels": sensor_channels,  # channel name -> flattened external sensor samples
        "categories": replay_cfg.get("categories") or [],  # researcher-defined category label/color overrides
    }
