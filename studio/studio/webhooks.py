"""Outbound webhook delivery.

When a hooked event fires (session_completed, session_failed, ...), every
matching WebhookEndpoint for the study receives an HTTP POST with:

    Content-Type: application/json
    X-Studio-Event:     <event_name>
    X-Studio-Delivery:  <delivery uuid>
    X-Studio-Signature: sha256=<hex hmac of body keyed on endpoint.secret>

Body shape:

    {
      "event": "session_completed",
      "delivery_id": "...",
      "ts": "2026-05-24T19:30:00Z",
      "study": { "slug": ..., "name": ..., "mode": ... },
      "session": { "id": ..., "status": ..., "mode": ..., "current_task_index": ... },
      "data": { ...event-specific... }
    }

"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from beanie import PydanticObjectId

from studio.models import Session, Study, WebhookEndpoint

log = logging.getLogger("studio.webhooks")

_ALLOWED_SCHEMES = {"http", "https"}


def _sign(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def _discord_payload(event: str, envelope: dict[str, Any]) -> bytes:
    """Format a Discord channel-webhook message (an embed) from the envelope."""
    study = envelope.get("study") or {}
    session = envelope.get("session") or {}
    data = envelope.get("data") or {}
    titles = {
        "participant_finished": "✅ Participant finished",
        "session_completed": "🏁 Session completed",
        "session_failed": "❌ Session failed",
        "session_started": "▶️ Session started",
        "code_minted": "🎟️ Code minted",
    }
    colors = {
        "participant_finished": 0x57F287,  # green
        "session_completed": 0x5865F2,     # blurple
        "session_failed": 0xED4245,        # red
        "session_started": 0xFEE75C,       # yellow
        "code_minted": 0xEB459E,           # pink
    }
    fields = [{"name": "Study", "value": f"{study.get('name', '?')} ({study.get('mode', '?')})", "inline": False}]
    if data.get("participant_anon"):
        who = data["participant_anon"]
        if data.get("role"):
            who += f" · {data['role']}"
        if data.get("task_runs") is not None:
            who += f" · {data['task_runs']} task run(s)"
        fields.append({"name": "Participant", "value": f"`{who}`", "inline": True})
    fields.append({"name": "Status", "value": str(session.get("status") or "—"), "inline": True})
    fields.append({"name": "Session", "value": f"`{session.get('id', '')}`", "inline": False})
    embed = {
        "title": titles.get(event, event),
        "color": colors.get(event, 0x5865F2),
        "fields": fields,
        "timestamp": envelope.get("ts"),
        "footer": {"text": "MIVAIS Studio"},
    }
    return json.dumps({"embeds": [embed]}).encode("utf-8")


async def url_is_safe(url: str) -> tuple[bool, str]:
    """


    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "unparseable URL"
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' not allowed (use http/https)"
    host = parsed.hostname
    if not host:
        return False, "missing host"
    # A literal IP host is checked directly; a name is resolved and every
    # returned address is checked (defends against DNS-rebinding to internal).
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = await asyncio.get_event_loop().getaddrinfo(host, port)
    except Exception as exc:
        return False, f"DNS resolution failed: {exc}"
    for info in infos:
        ip_str = info[4][0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"invalid resolved address {ip_str}"
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False, f"resolves to non-public address {ip_str}"
    return True, ""


async def fire(event: str, study: Study, session: Session, data: dict[str, Any] | None = None) -> None:
    """Deliver ``event`` for ``session`` to every active webhook on ``study``."""
    if event not in {"session_completed", "session_failed", "session_started",
                     "participant_finished", "code_minted"}:
        log.warning("ignoring unknown webhook event '%s'", event)
        return

    hooks = await WebhookEndpoint.find(
        WebhookEndpoint.study_id == study.id,
        WebhookEndpoint.active == True,  # noqa: E712
    ).to_list()
    if not hooks:
        return

    envelope = {
        "event": event,
        "delivery_id": secrets.token_hex(12),
        "ts": datetime.now(timezone.utc).isoformat(),
        "study": {"slug": study.slug, "name": study.name, "mode": study.mode},
        "session": {
            "id": str(session.id),
            "status": session.status,
            "mode": session.mode,
            "current_task_index": session.current_task_index,
            "tags": list(session.tags or []),
        },
        "data": data or {},
    }
    body = json.dumps(envelope, default=str).encode("utf-8")

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        for h in hooks:
            if event not in (h.events or []):
                continue
            safe, reason = await url_is_safe(h.url)
            if not safe:
                h.last_delivery_status = -1
                h.failure_count += 1
                h.last_delivery_at = datetime.now(timezone.utc).replace(tzinfo=None)
                log.warning("webhook %s blocked by SSRF guard: %s", h.url, reason)
                await h.save()
                continue
            try:
                if getattr(h, "kind", "studio") == "discord":
                    content = _discord_payload(event, envelope)
                    headers = {"Content-Type": "application/json"}
                else:
                    content = body
                    headers = {
                        "Content-Type": "application/json",
                        "X-Studio-Event": event,
                        "X-Studio-Delivery": envelope["delivery_id"],
                        "X-Studio-Signature": _sign(h.secret, body),
                    }
                resp = await client.post(h.url, content=content, headers=headers)
                h.last_delivery_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    h.delivery_count += 1
                else:
                    h.failure_count += 1
                    log.warning("webhook %s returned HTTP %s", h.url, resp.status_code)
            except Exception as exc:
                h.last_delivery_status = -1
                h.failure_count += 1
                log.warning("webhook %s failed: %s", h.url, exc)
            h.last_delivery_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await h.save()
