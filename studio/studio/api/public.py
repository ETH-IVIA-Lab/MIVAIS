"""Public read-only v1 API — programmatic access for external tools.

Authentication: mint an API key in the admin (System → API access) and send
it as ``Authorization: Bearer mvs_...``. Keys are read-only by design: this
router exposes GETs only, so an external analysis pipeline, dashboard, or
notebook can pull everything a study produces without touching the admin UI.

Endpoints (all under ``/api/v1``):

    GET /studies                                 list registered studies
    GET /studies/{slug}                          study detail incl. config
    GET /studies/{slug}/sessions                 sessions of a study (paginated)
    GET /studies/{slug}/metrics                  declared metrics, aggregated
    GET /sessions/{id}                           session + participants + VAs
    GET /sessions/{id}/events                    full event timeline (paginated)
    GET /sessions/{id}/answers                   per-participant task runs/answers
    GET /sessions/{id}/metrics                   declared metrics for this session
    GET /sessions/{id}/annotations               markers + notes + tags
    GET /sessions/{id}/transcript                speech transcript per video run

Interactive schema: FastAPI's OpenAPI covers these routes (/docs).
"""
from __future__ import annotations

from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from studio.models import ApiKey, Event, Participant, Session, Study
from studio.models.api_key import hash_token

router = APIRouter(prefix="/api/v1", tags=["public-v1"])


# ── auth ──────────────────────────────────────────────────────────────────────

async def _require_key(request: Request) -> ApiKey:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token — mint an API key in the admin (System → API access)")
    token = auth[7:].strip()
    key = await ApiKey.find_one(ApiKey.token_hash == hash_token(token))
    if key is None or key.revoked:
        raise HTTPException(401, "Invalid or revoked API key")
    from datetime import datetime, timezone
    key.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await key.save()
    return key


# ── serialization helpers ─────────────────────────────────────────────────────

def _study_out(study: Study, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "slug": study.slug,
        "name": study.name,
        "version": study.version,
        "mode": study.mode,
        "archived": study.archived,
        "created_at": study.created_at.isoformat(),
        "yaml_hash": study.yaml_hash,
    }
    if full:
        out.update({
            "participants_required": study.participants_required,
            "roles": study.roles,
            "va_systems": {k: (v or {}) for k, v in (study.va_systems or {}).items()},
            "blocks": study.blocks,
            "metrics": study.metrics,
            "parameters": study.parameters,
            "recording": study.recording,
        })
    return out


def _session_out(session: Session) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "study_id": str(session.study_id),
        "mode": session.mode,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "current_task_index": session.current_task_index,
        "tags": session.tags,
    }


def _participant_out(p: Participant) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "anon_id": p.anon_id,
        "session_id": str(p.session_id),
        "role": getattr(p, "role", None),
        "status": getattr(p, "status", None),
        "external_id": getattr(p, "external_id", None),
    }


async def _get_session_or_404(session_id: str) -> Session:
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


# ── studies ───────────────────────────────────────────────────────────────────

@router.get("/studies")
async def v1_studies(request: Request, include_archived: bool = False) -> JSONResponse:
    await _require_key(request)
    studies = await Study.find().sort("-created_at").to_list()
    rows = [_study_out(s) for s in studies if include_archived or not s.archived]
    return JSONResponse({"studies": rows})


@router.get("/studies/{slug}")
async def v1_study_detail(request: Request, slug: str) -> JSONResponse:
    await _require_key(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    n_sessions = await Session.find(Session.study_id == study.id).count()
    out = _study_out(study, full=True)
    out["n_sessions"] = n_sessions
    return JSONResponse({"study": out})


@router.get("/studies/{slug}/sessions")
async def v1_study_sessions(
    request: Request,
    slug: str,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    await _require_key(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    query = Session.find(Session.study_id == study.id)
    if status:
        query = Session.find(Session.study_id == study.id, Session.status == status)
    total = await query.count()
    sessions = await query.sort("-created_at").skip(offset).limit(limit).to_list()
    return JSONResponse({
        "total": total, "limit": limit, "offset": offset,
        "sessions": [_session_out(s) for s in sessions],
    })


@router.get("/studies/{slug}/metrics")
async def v1_study_metrics(request: Request, slug: str) -> JSONResponse:
    await _require_key(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    from studio.metrics.service import compute_study_metrics
    return JSONResponse(await compute_study_metrics(study))


# ── sessions ──────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}")
async def v1_session_detail(request: Request, session_id: str) -> JSONResponse:
    await _require_key(request)
    session = await _get_session_or_404(session_id)
    study = await Study.get(session.study_id)
    participants = await Participant.find(Participant.session_id == session.id).to_list()
    out = _session_out(session)
    out["study_slug"] = study.slug if study else None
    out["participants"] = [_participant_out(p) for p in participants]
    out["vas"] = {k: {"variant": v.variant} for k, v in (session.vas or {}).items()}
    return JSONResponse({"session": out})


@router.get("/sessions/{session_id}/events")
async def v1_session_events(
    request: Request,
    session_id: str,
    type: str | None = None,
    source: str | None = None,
    task_id: str | None = None,
    after_t_ms: int | None = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """The session's full unified timeline — the same events replay/analytics
    are built from. Filterable and paginated for incremental pulls (poll with
    ``after_t_ms`` to stream a running session)."""
    await _require_key(request)
    session = await _get_session_or_404(session_id)
    conditions: list[Any] = [Event.session_id == session.id]
    if type:
        conditions.append(Event.type == type)
    if source:
        conditions.append(Event.source == source)
    if task_id:
        conditions.append(Event.task_id == task_id)
    if after_t_ms is not None:
        conditions.append(Event.t_ms > after_t_ms)
    query = Event.find(*conditions)
    total = await query.count()
    events = await query.sort("t_ms").skip(offset).limit(limit).to_list()
    return JSONResponse({
        "total": total, "limit": limit, "offset": offset,
        "events": [
            {
                "t_ms": ev.t_ms,
                "wall_clock": ev.wall_clock.isoformat(),
                "source": ev.source,
                "type": ev.type,
                "task_id": ev.task_id,
                "block_id": ev.block_id,
                "participant_id": str(ev.participant_id) if ev.participant_id else None,
                "va_system_id": ev.va_system_id,
                "meta": ev.meta,
            }
            for ev in events
        ],
    })


@router.get("/sessions/{session_id}/answers")
async def v1_session_answers(request: Request, session_id: str) -> JSONResponse:
    """Every participant's task runs: answers, scores, timings, checked steps."""
    await _require_key(request)
    session = await _get_session_or_404(session_id)
    participants = await Participant.find(Participant.session_id == session.id).to_list()
    rows = []
    for p in participants:
        rows.append({
            **_participant_out(p),
            "task_runs": [
                {
                    "task_id": r.task_id,
                    "task_index": r.task_index,
                    "started_at": r.started_at.isoformat(),
                    "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                    "duration_ms": r.duration_ms,
                    "answer": r.answer,
                    "score": r.score,
                    "correct": r.correct,
                    "score_details": r.score_details,
                    "timed_out": r.timed_out,
                    "skipped": r.skipped,
                    "checked_steps": list(r.checked_steps),
                }
                for r in (p.task_runs or [])
            ],
        })
    return JSONResponse({"participants": rows})


@router.get("/sessions/{session_id}/metrics")
async def v1_session_metrics(request: Request, session_id: str) -> JSONResponse:
    await _require_key(request)
    session = await _get_session_or_404(session_id)
    study = await Study.get(session.study_id)
    if study is None:
        raise HTTPException(404, "Study gone")
    from studio.metrics.service import compute_session_metrics
    return JSONResponse({"participants": await compute_session_metrics(study, session)})


@router.get("/sessions/{session_id}/annotations")
async def v1_session_annotations(request: Request, session_id: str) -> JSONResponse:
    """Researcher annotations: timeline markers (incl. transcript quotes),
    free-form notes, and tags."""
    await _require_key(request)
    session = await _get_session_or_404(session_id)
    return JSONResponse({
        "markers": list(session.markers or []),
        "notes": list(session.notes or []),
        "tags": list(session.tags or []),
        "tags_by_author": dict(session.tags_by_author or {}),
    })


@router.get("/sessions/{session_id}/transcript")
async def v1_session_transcript(request: Request, session_id: str, run: str | None = None) -> JSONResponse:
    """Speech transcript segments for a session's recording. ``?run=`` selects
    a specific participant's POV (see /sessions/{id} → participants)."""
    await _require_key(request)
    session = await _get_session_or_404(session_id)
    from studio.api.video import _build_combined, _run_chunks
    from studio.video import transcribe as video_transcribe
    chunks = await _run_chunks(session.id, run)
    if not chunks:
        return JSONResponse({"status": "none", "segments": []})
    combined = _build_combined(chunks)
    if combined is None or not combined.exists():
        return JSONResponse({"status": "none", "segments": []})
    st, segs = video_transcribe.status(combined.parent)
    return JSONResponse({"status": st, "segments": segs})
