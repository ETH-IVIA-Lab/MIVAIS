"""Read-only shared-replay endpoints — token-gated, no admin login.

An admin mints a ``share_token`` for a session (``POST
/api/admin/sessions/{id}/share``); anyone holding the resulting
``/admin/shared/<token>`` link can then view that ONE session's replay:
the event timeline, WorldState snapshots, markers and the screen recording.
Nothing here mutates state, and nothing beyond the shared session is
reachable — the token scopes every route.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from studio.api.analytics_helpers import replay_payload
from studio.models import Session, Study

router = APIRouter(prefix="/api/shared", tags=["shared"])


async def _session_by_token(token: str) -> Session:
    if not token or len(token) < 16:
        raise HTTPException(404, "Unknown share link")
    session = await Session.find_one(Session.share_token == token)
    if session is None:
        raise HTTPException(404, "Unknown share link")
    return session


@router.get("/replay/{token}")
async def shared_replay(token: str) -> dict[str, Any]:
    """The replay payload for a shared session — same data the admin replay
    viewer uses, minus admin-only surfaces (notes, live-VA replay)."""
    session = await _session_by_token(token)
    study = await Study.get(session.study_id)
    payload = await replay_payload(session)

    for v in payload.get("videos", []):
        v["src"] = f"/api/shared/replay/{token}/video?run={v['run_id']}"

    return {
        # Deliberately slim: no process info, notes, tags or study snapshot.
        "session": {
            "id": str(session.id),
            "status": session.status,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "mode": session.mode,
        },
        "study": {"name": study.name if study else "", "slug": study.slug if study else ""},
        "markers": list(session.markers or []),
        "payload": payload,
    }


@router.get("/replay/{token}/video", response_model=None)
async def shared_replay_video(token: str, run: str | None = None) -> FileResponse:
    """Stream the shared session's combined recording (Range-capable), exactly
    like the admin video route but gated by the share token instead of login."""
    session = await _session_by_token(token)
    from studio.api.video import _build_combined, _run_chunks

    chunks = await _run_chunks(session.id, run)
    if not chunks:
        raise HTTPException(404, "No recording for this session")
    combined = _build_combined(chunks)
    if combined is None or not combined.exists():
        raise HTTPException(404, "Recording files are missing")
    return FileResponse(str(combined), media_type="video/webm",
                        filename=f"session_{session.id}.webm")
