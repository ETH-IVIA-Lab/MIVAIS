"""Auto-check engine for task_steps.

A task may declare `task_steps[].auto_check_on:` with an event type and an
optional `meta:` predicate. When the WebSocket collector persists a MIVAIS
event, it asks this engine whether any pending step trigger matches. If a
step's configured `count` is reached, the engine calls a registered callback
so the session manager can persist the check + emit the `task_step_checked`
event.

State is held in-process and keyed by session_id. On task start the orchestrator
calls `register_task`; on task end it calls `clear_task`. The collector calls
`feed_event` for every MIVAIS event it persists.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("studio.auto_check")


# Callback signature: (session_id, task_id, step_id, source) -> coroutine
StepCheckedCallback = Callable[[str, str, str, str], Awaitable[None]]


@dataclass
class _ActiveTrigger:
    task_id: str
    step_id: str
    event_type: str
    meta_pred: dict[str, Any]
    target_count: int
    current_count: int = 0
    fired: bool = False


# session_id -> list of active triggers (one per step that has auto_check_on)
_active: dict[str, list[_ActiveTrigger]] = {}

# session-wide callback hook the session manager registers once at startup
_callback: StepCheckedCallback | None = None


def set_callback(cb: StepCheckedCallback) -> None:
    """Register the coroutine called when a trigger fires. Idempotent."""
    global _callback
    _callback = cb


def register_task(session_id: str, task_id: str, task_steps: list[dict[str, Any]]) -> None:
    """Replace any active triggers for `(session_id, task_id)` with this task's set."""
    new: list[_ActiveTrigger] = []
    # Drop any existing triggers from earlier task in the session.
    existing = _active.get(session_id, [])
    new.extend(t for t in existing if t.task_id != task_id)

    for step in task_steps or []:
        trigger = step.get("auto_check_on") if isinstance(step, dict) else None
        if not trigger:
            continue
        try:
            new.append(_ActiveTrigger(
                task_id=task_id,
                step_id=str(step["id"]),
                event_type=str(trigger["event_type"]),
                meta_pred=dict(trigger.get("meta") or {}),
                target_count=int(trigger.get("count") or 1),
            ))
        except Exception as exc:
            log.warning("ignoring malformed auto_check trigger for step=%r: %s", step, exc)
    _active[session_id] = new


def clear_task(session_id: str, task_id: str) -> None:
    """Forget every trigger belonging to this task on this session."""
    if session_id not in _active:
        return
    _active[session_id] = [t for t in _active[session_id] if t.task_id != task_id]
    if not _active[session_id]:
        _active.pop(session_id, None)


def clear_session(session_id: str) -> None:
    _active.pop(session_id, None)


def feed_event(session_id: str, event: dict[str, Any]) -> None:
    """Match a freshly-ingested MIVAIS event against this session's triggers.

    Schedules the callback on the running loop for each trigger that fires.
    Synchronous so the tailer's persistence loop is never awaited on it.
    """
    if not _callback:
        return
    triggers = _active.get(session_id)
    if not triggers:
        return

    event_type = event.get("type")
    for trig in triggers:
        if trig.fired:
            continue
        if trig.event_type != event_type:
            continue
        if not _meta_matches(trig.meta_pred, event):
            continue
        trig.current_count += 1
        if trig.current_count < trig.target_count:
            continue
        trig.fired = True
        loop = asyncio.get_event_loop()
        loop.create_task(_callback(session_id, trig.task_id, trig.step_id, "auto"))


def _meta_matches(predicate: dict[str, Any], event: dict[str, Any]) -> bool:
    """All key/value pairs in `predicate` must match the event.

    Keys may be dotted paths (e.g. ``data.key`` → ``event["data"]["key"]``).
    Lookup is best-effort: a missing path counts as a non-match.
    """
    if not predicate:
        return True
    for path, expected in predicate.items():
        value = _resolve_path(event, str(path).split("."))
        if value != expected:
            return False
    return True


def _resolve_path(root: Any, parts: list[str]) -> Any:
    current = root
    for p in parts:
        if isinstance(current, dict) and p in current:
            current = current[p]
        else:
            return None
    return current
