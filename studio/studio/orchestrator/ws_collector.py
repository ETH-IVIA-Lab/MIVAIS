"""Live WebSocket provenance collector: Studio connects directly to each VA's
MIVAIS Gateway (role ``studio_collector``) and persists every event the
Gateway taps from its own SessionRecorder — no local filesystem access to the
VA's recording directory is required, so this works for co-located AND
externally-hosted VAs alike.

One connection per ``(session_id, va_system_id)``, auto-reconnecting with
backoff if the VA restarts or the connection drops.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from datetime import datetime, timezone

from beanie import PydanticObjectId
import websockets

from studio.models import Event, Session
from studio.models.event import SOURCE_MIVAIS
from studio.orchestrator import auto_check
from studio.orchestrator.va_client import _ws_url_from_iframe

log = logging.getLogger("studio.ws_collector")

# session_id -> task currently active (task_id, logging_id)
_active_task: dict[str, tuple[str | None, str | None]] = {}

# composite "<session_id>::<va_system_id>" -> collector task
_tasks: dict[str, asyncio.Task] = {}


def _key(session_id: str, va_system_id: str) -> str:
    return f"{session_id}::{va_system_id}"


def set_active_task(session_id: str, task_id: str | None, logging_id: str | None = None) -> None:
    _active_task[session_id] = (task_id, logging_id)


def clear_active_task(session_id: str) -> None:
    _active_task.pop(session_id, None)


async def start_collector(
    session_id: PydanticObjectId,
    study_id: PydanticObjectId,
    va_system_id: str,
    iframe_url: str,
) -> None:
    """Start collecting one VA's live event stream in a background task."""
    sid = str(session_id)
    composite = _key(sid, va_system_id)
    if composite in _tasks:
        return
    task = asyncio.create_task(
        _collect_loop(sid, str(study_id), va_system_id, iframe_url),
        name=f"ws-collector:{composite}",
    )
    _tasks[composite] = task


async def stop_collector(session_id: PydanticObjectId, va_system_id: str) -> None:
    composite = _key(str(session_id), va_system_id)
    task = _tasks.pop(composite, None)
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def stop_session(session_id: PydanticObjectId) -> None:
    """Stop every collector running for the given session and forget its active task."""
    sid = str(session_id)
    prefix = f"{sid}::"
    keys = [k for k in _tasks if k.startswith(prefix)]
    for k in keys:
        _, va_system_id = k.split("::", 1)
        await stop_collector(session_id, va_system_id)
    _active_task.pop(sid, None)


async def stop_all() -> None:
    for k in list(_tasks.keys()):
        sid_str, va_system_id = k.split("::", 1)
        await stop_collector(PydanticObjectId(sid_str), va_system_id)


# ── internal ──────────────────────────────────────────────────────────────

async def _collect_loop(session_id: str, study_id: str, va_system_id: str, iframe_url: str) -> None:
    channel = f"studio-collector-{secrets.token_hex(4)}"
    url = _ws_url_from_iframe(iframe_url, channel, role="studio_collector")
    start_ms = time.monotonic() * 1000
    backoff_s = 1.0

    while True:
        try:
            async with websockets.connect(url, open_timeout=10, close_timeout=5) as ws:
                backoff_s = 1.0
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") != "recorder_event":
                        continue
                    await _handle_recorder_event(
                        session_id, study_id, va_system_id, start_ms,
                        str(msg.get("event_type", "unknown")), msg.get("data") or {},
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("ws collector for %s reconnecting after error: %r", url, exc)
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 15.0)


async def _handle_recorder_event(
    session_id: str, study_id: str, va_system_id: str, start_ms: float,
    event_type: str, data: dict,
) -> None:
    await _maybe_set_jsonl_offset(session_id)
    t_ms = int(time.monotonic() * 1000 - start_ms)
    raw = {"t": t_ms, "type": event_type, **data}
    await _persist_event(session_id, study_id, va_system_id, raw)


async def _maybe_set_jsonl_offset(session_id: str) -> None:
    """Anchor the audio/video alignment offset to the first live event this
    collector receives, mirroring what the (now-removed) JSONL tailer used to
    derive from the recording file's creation time."""
    session = await Session.get(PydanticObjectId(session_id))
    if session is None or session.va_started_at is None or session.va_jsonl_offset_ms != 0:
        return
    anchor = session.va_started_at
    if anchor.tzinfo is not None:
        anchor = anchor.replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.va_jsonl_offset_ms = int((now - anchor).total_seconds() * 1000)
    await session.save()


async def _persist_event(session_id: str, study_id: str, va_system_id: str, raw: dict) -> None:
    task_id, logging_id = _active_task.get(session_id, (None, None))
    try:
        event = Event(
            study_id=PydanticObjectId(study_id),
            session_id=PydanticObjectId(session_id),
            task_id=task_id,
            logging_id=logging_id,
            va_system_id=va_system_id,
            t_ms=int(raw.get("t", 0)),
            source=SOURCE_MIVAIS,
            type=str(raw.get("type", "unknown")),
            meta={k: v for k, v in raw.items() if k not in ("t", "type")},
        )
        await event.insert()
    except Exception:
        # Best-effort: never let a malformed event kill the collector
        return

    try:
        auto_check.feed_event(session_id, raw)
    except Exception:
        pass
