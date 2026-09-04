"""Declarative behavioral metrics, computed from a participant's event stream.

Studies declare metrics in study.yaml::

    metrics:
      - id: suggestion_response_time
        label: "Time to respond to a suggestion"
        kind: latency
        from: { event_type: user_action, meta: { action: suggestion_shown } }
        to:   { event_type: user_action, meta: { action: accept_suggestion } }
        aggregate: median

      - id: acceptance_rate
        kind: ratio                # numerator / (numerator + denominator)
        numerator:   { event_type: user_action, meta: { action: accept_suggestion } }
        denominator: { event_type: user_action, meta: { action: reject_suggestion } }

      - id: interaction_rate
        kind: rate                 # matched events per minute
        match: { event_type: user_action }
        task: explore              # optional: scope to one task's window

      - id: my_special_thing
        kind: python               # escape hatch, same plugin convention as
        module: studio.metrics.custom.example_idle_share:compute   # custom scorers
        params: { threshold_s: 5 }

Event matchers use the same vocabulary as ``task_steps.auto_check_on``:
``event_type`` plus a ``meta`` predicate of (dotted-path) key → expected value.

Everything here is pure computation over already-persisted events — metrics
are evaluated lazily by analytics/API calls and change retroactively when the
study's definitions change.
"""
from __future__ import annotations

import importlib
import statistics
from typing import Any

__all__ = ["compute_metrics", "MetricResult"]

MetricResult = dict[str, Any]  # {id, label, kind, value, unit, n, detail}


# ── event matching (auto_check_on semantics) ─────────────────────────────────

def _resolve_path(root: Any, parts: list[str]) -> Any:
    current = root
    for p in parts:
        if isinstance(current, dict) and p in current:
            current = current[p]
        else:
            return None
    return current


def _matches(matcher: dict[str, Any] | None, event: dict[str, Any]) -> bool:
    if not matcher:
        return False
    if matcher.get("event_type") and event.get("type") != matcher["event_type"]:
        return False
    if matcher.get("source") and event.get("source") != matcher["source"]:
        return False
    for path, expected in (matcher.get("meta") or {}).items():
        # meta predicates look inside event["meta"] first (the common case),
        # falling back to the event root for fields like task_id.
        value = _resolve_path(event.get("meta") or {}, str(path).split("."))
        if value is None:
            value = _resolve_path(event, str(path).split("."))
        if value != expected:
            return False
    return True


# ── task windows ──────────────────────────────────────────────────────────────

def _task_windows(events: list[dict[str, Any]], task_id: str) -> list[tuple[int, int]]:
    """[(start_t_ms, end_t_ms)] for every run of ``task_id`` in the stream."""
    windows: list[tuple[int, int]] = []
    start: int | None = None
    for ev in events:
        if ev.get("task_id") != task_id:
            continue
        if ev.get("type") == "task_start":
            start = int(ev.get("t_ms") or 0)
        elif ev.get("type") == "task_end" and start is not None:
            windows.append((start, int(ev.get("t_ms") or 0)))
            start = None
    if start is not None:  # task never ended (abandoned session)
        last_t = int(events[-1].get("t_ms") or 0) if events else start
        windows.append((start, max(start, last_t)))
    return windows


def _scope(events: list[dict[str, Any]], task_id: str | None) -> tuple[list[dict[str, Any]], int]:
    """Events inside the metric's scope + the scope duration in ms."""
    if not task_id:
        duration = int(events[-1].get("t_ms") or 0) - int(events[0].get("t_ms") or 0) if events else 0
        return events, max(duration, 0)
    windows = _task_windows(events, task_id)
    scoped = [
        ev for ev in events
        if any(a <= int(ev.get("t_ms") or 0) <= b for a, b in windows)
    ]
    return scoped, sum(b - a for a, b in windows)


# ── metric kinds ──────────────────────────────────────────────────────────────

_AGGREGATES = {
    "mean": statistics.fmean,
    "median": statistics.median,
    "min": min,
    "max": max,
}


def _latency(defn: dict[str, Any], events: list[dict[str, Any]]) -> tuple[float | None, int, dict]:
    """Pair each `to` event with the most recent unconsumed `from` before it."""
    samples_ms: list[int] = []
    pending_from: int | None = None
    for ev in events:
        if _matches(defn.get("from"), ev):
            # A new trigger resets the pending window (latest-from semantics).
            pending_from = int(ev.get("t_ms") or 0)
        elif pending_from is not None and _matches(defn.get("to"), ev):
            samples_ms.append(int(ev.get("t_ms") or 0) - pending_from)
            pending_from = None
            if defn.get("first_only"):
                break
    if not samples_ms:
        return None, 0, {"samples_ms": []}
    agg = _AGGREGATES.get(defn.get("aggregate") or "median", statistics.median)
    return round(agg(samples_ms) / 1000.0, 3), len(samples_ms), {"samples_ms": samples_ms[:100]}


def _compute_one(defn: dict[str, Any], events: list[dict[str, Any]]) -> MetricResult:
    kind = defn.get("kind")
    scoped, duration_ms = _scope(events, defn.get("task"))
    value: float | None = None
    unit = ""
    n = 0
    detail: dict[str, Any] = {}

    if kind == "count":
        n = sum(1 for ev in scoped if _matches(defn.get("match"), ev))
        value = float(n)
        unit = "events"

    elif kind == "rate":
        n = sum(1 for ev in scoped if _matches(defn.get("match"), ev))
        minutes = duration_ms / 60000.0
        value = round(n / minutes, 3) if minutes > 0 else None
        unit = "events/min"
        detail = {"count": n, "duration_ms": duration_ms}

    elif kind == "latency":
        value, n, detail = _latency(defn, scoped)
        unit = "s"

    elif kind == "ratio":
        num = sum(1 for ev in scoped if _matches(defn.get("numerator"), ev))
        den = sum(1 for ev in scoped if _matches(defn.get("denominator"), ev))
        total = num + den
        value = round(num / total, 3) if total else None
        n = total
        unit = "share"
        detail = {"numerator": num, "denominator": den}

    elif kind == "python":
        value, n, detail = _run_python_metric(defn, scoped)

    return {
        "id": defn.get("id") or "?",
        "label": defn.get("label") or defn.get("id") or "?",
        "kind": kind,
        "value": value,
        "unit": unit,
        "n": n,
        "detail": detail,
    }


def _run_python_metric(defn: dict[str, Any], events: list[dict[str, Any]]) -> tuple[float | None, int, dict]:
    """Load ``module.path:callable`` and call it with (events, params).

    The callable returns a number, or ``(number, detail_dict)``. Errors are
    captured into the result instead of breaking the whole metrics response.
    """
    ref = str(defn.get("module") or "")
    if ":" not in ref:
        return None, 0, {"error": f"module must be 'pkg.mod:callable', got {ref!r}"}
    mod_path, func_name = ref.split(":", 1)
    if not mod_path.startswith("studio.metrics.custom."):
        return None, 0, {"error": "custom metrics must live under studio.metrics.custom"}
    try:
        fn = getattr(importlib.import_module(mod_path), func_name)
        out = fn(events, dict(defn.get("params") or {}))
    except Exception as exc:  # surface, don't crash the endpoint
        return None, 0, {"error": f"{type(exc).__name__}: {exc}"[:200]}
    if isinstance(out, tuple):
        value, detail = out[0], (out[1] if len(out) > 1 else {})
    else:
        value, detail = out, {}
    return (float(value) if value is not None else None), len(events), dict(detail or {})


def compute_metrics(metric_defs: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[MetricResult]:
    """Evaluate every declared metric over ONE participant's time-ordered events."""
    ordered = sorted(events, key=lambda ev: int(ev.get("t_ms") or 0))
    return [_compute_one(d, ordered) for d in metric_defs]
