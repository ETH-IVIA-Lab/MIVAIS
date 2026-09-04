"""Studio → MIVAIS Gateway WebSocket client.

Used at task-start to write the task's `world_state:` payload into the running
VA. Reuses the MIVAIS Gateway's existing `replay.push_state` action, which
calls `WorldState.system_write(key, value)` for each entry — bypassing the
Permission Guard by design when the client connects with role `studio_replayer`.

Connection is opened, the payload is sent in one frame, and the socket is
closed. These are the write-only flows; ``ws_collector`` maintains the
long-lived, read-only ``studio_collector`` connection that is the read side
of the contract.
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import websockets

log = logging.getLogger("studio.va_client")


class VAClientError(RuntimeError):
    pass


def _ws_url_from_iframe(iframe_url: str, channel: str, role: str = "studio_replayer") -> str:
    """Derive ``ws(s)://<host>:<port>/ws/<channel>?role=<role>`` from
    the VA's iframe HTTP URL. We use the same host+port the VA serves on; the
    `/ws/<channel>` path is the MIVAIS convention.

    The iframe URL's ``room`` query param (set by the spawner for an isolated
    external VA) is forwarded so the server-side WorldState push (or the live
    provenance collector) targets the SAME room the participant is in —
    without it the write would land in the VA's shared ``default`` world.
    """
    parsed = urlparse(iframe_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    netloc = f"{host}:{port}" if port else host
    url = f"{scheme}://{netloc}/ws/{channel}?role={role}"
    room = (parse_qs(parsed.query).get("room") or [None])[0]
    if room:
        url += f"&room={quote(room, safe='')}"
    return url


async def push_world_state(
    iframe_url: str,
    state: dict[str, Any],
    *,
    channel: str | None = None,
    timeout_s: float = 5.0,
) -> None:
    """Open a short-lived WS to the VA and push ``state`` into its WorldState.

    Each top-level key in ``state`` is written via ``system_write``. The VA's
    normal WorldState subscribers (including the recorder) see the writes.
    Channel defaults to a Studio-namespaced random id so the VA can identify
    Studio-driven connections in its access logs.
    """
    if not state:
        return
    ch = channel or f"studio-write-{secrets.token_hex(4)}"
    url = _ws_url_from_iframe(iframe_url, ch)
    payload = json.dumps({"action": "replay.push_state", "state": state})

    try:
        async with websockets.connect(url, open_timeout=timeout_s, close_timeout=timeout_s) as ws:
            # MIVAIS Gateway pushes initial_state on connect; drain it so the
            # socket doesn't buffer indefinitely (we don't need the value).
            try:
                await _drain_one_with_deadline(ws, timeout_s)
            except Exception:
                pass
            await ws.send(payload)
    except Exception as exc:
        # Best-effort write: surface as a typed error so the orchestrator can
        # log it without taking down the participant flow.
        raise VAClientError(f"push_world_state to {url}: {exc!r}") from exc


async def send_wizard_action(
    iframe_url: str,
    action: dict[str, Any],
    *,
    channel: str | None = None,
    timeout_s: float = 5.0,
) -> None:
    """Open a short-lived WS to the VA and send one Wizard-of-Oz action.

    Connects with role ``studio_replayer`` (the privileged Studio channel the VA
    Gateway requires for ``wizard.*`` actions), so the operator drives the agents
    server-side without ever joining as a participant. ``action`` is e.g.
    ``{"action": "wizard.act", "actor": "svm_ranker", "key": "weights", "value": …}``
    or ``{"action": "wizard.say", "actor": "svm_ranker", "text": "…"}``.
    """
    if not action:
        return
    ch = channel or f"wizard-{secrets.token_hex(4)}"
    url = _ws_url_from_iframe(iframe_url, ch)
    payload = json.dumps(action)
    try:
        async with websockets.connect(url, open_timeout=timeout_s, close_timeout=timeout_s) as ws:
            try:
                await _drain_one_with_deadline(ws, timeout_s)
            except Exception:
                pass
            await ws.send(payload)
    except Exception as exc:
        raise VAClientError(f"send_wizard_action to {url}: {exc!r}") from exc


async def _drain_one_with_deadline(ws, timeout_s: float) -> None:
    """Read one message off the socket within ``timeout_s`` seconds, else move on."""
    import asyncio
    try:
        await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return
