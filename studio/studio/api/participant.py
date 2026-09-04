"""Participant flow: code entry, consent, task runner, finish. JSON API.

Every route here is consumed by the React participant SPA (studio/frontend,
src/participant) via fetch.
"""
from __future__ import annotations

import json
from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from studio.api.markdown import render_markdown
from studio.config.schemas import StudyConfig
from studio.models import Code, Event, Participant, Session, Study
from studio.models.event import SOURCE_MIVAIS
from studio.orchestrator import auto_check, flow, session_manager

router = APIRouter(prefix="/api", tags=["participant"])

PARTICIPANT_COOKIE = "studio_participant"


class NextResponse(BaseModel):
    """Shared shape for the SPA's client-side-navigation contract: `next`
    points the router at the following page instead of an HTTP redirect.
    `error` coexists with `next` only on `/p/role`'s "role just filled"
    case (see `role_pick`) — every other route that sets `error` here
    raises a real `HTTPException` instead (this base model just needs to
    accept the one legitimate case without forcing every subclass to redeclare
    it).
    """

    next: str | None = None
    error: str | None = None


class PreflightResponse(BaseModel):
    code: str
    study: dict[str, Any] | None
    audio_required: bool
    valid_code: bool


# ── code entry & landing ──────────────────────────────────────────────────


_EXTERNAL_ID_KEYS = ("PROLIFIC_PID", "prolific_pid", "workerId", "worker_id",
                     "pid", "external_id", "participant_id")
# Extra recruitment params kept verbatim (e.g. Prolific STUDY_ID / SESSION_ID).
_RECRUITMENT_KEYS = ("PROLIFIC_PID", "STUDY_ID", "SESSION_ID",
                     "workerId", "assignmentId", "hitId")


class JoinRequest(BaseModel):
    code: str = ""


@router.post("/join")
async def join_submit(request: Request, body: JoinRequest) -> JSONResponse:
    """Used both by the code-entry form and the ``/s/:code`` deep-link page.

    The deep-link page forwards its own query string verbatim (Prolific/MTurk
    recruitment params) so the extraction logic stays server-side only.
    """
    code_value = body.code.strip().upper()
    qp = request.query_params
    external_id = next((qp[k] for k in _EXTERNAL_ID_KEYS if qp.get(k)), None)
    recruitment = {k: qp[k][:200] for k in _RECRUITMENT_KEYS if qp.get(k)}
    return await _start_or_resume(request, code_value, external_id=external_id, recruitment=recruitment)


@router.get("/p/preflight/{code}", response_model=PreflightResponse)
async def preflight(code: str) -> PreflightResponse:
    """Pre-join system check: shows the participant what we'll need (mic,
    browser support, network reach) before they spend the access code.
    """
    code_obj = await Code.find_one(Code.code == code.upper())
    study = await Study.get(code_obj.study_id) if code_obj else None
    audio_required = bool(study and (study.recording or {}).get("audio", "none") != "none")
    return PreflightResponse(
        code=code.upper(),
        study=study.model_dump(mode="json") if study else None,
        audio_required=audio_required,
        valid_code=code_obj is not None and code_obj.is_usable()
        and not (study is not None and study.archived),
    )


async def _start_or_resume(
    request: Request,
    code_value: str,
    external_id: str | None = None,
    recruitment: dict | None = None,
) -> JSONResponse:
    code = await Code.find_one(Code.code == code_value)
    if code is None or not code.is_usable():
        raise HTTPException(400, "Invalid or expired code.")
    study = await Study.get(code.study_id)
    if study is None:
        raise HTTPException(404, "Study not found")

    # Validate any pre-bound role on the code is still declared on the study.
    if code.role and not any(r.get("id") == code.role for r in (study.roles or [])):
        raise HTTPException(
            409,
            f"This code is bound to role '{code.role}', "
            f"which the study no longer declares.",
        )

    # Reuse the participant cookie when present; else create a new session for this participant.
    participant_id = request.cookies.get(PARTICIPANT_COOKIE)
    participant = None
    if participant_id:
        try:
            participant = await Participant.get(PydanticObjectId(participant_id))
        except Exception:
            participant = None

    if participant is None or participant.study_id != study.id or participant.status == "finished":
        
        if external_id:
            done = await Participant.find_one(
                Participant.study_id == study.id,
                Participant.external_id == external_id[:128],
                Participant.status == "finished",
            )
            if done is not None:
                resp = JSONResponse({"next": "/p/finish"})
                resp.set_cookie(
                    PARTICIPANT_COOKIE, str(done.id),
                    httponly=True, samesite="lax", max_age=60 * 60 * 24,
                )
                return resp
        
        if study.archived:
            raise HTTPException(410, "This study is closed and no longer accepts participants.")
        session = await _attach_to_session(study, code)
        if session is None:
            raise HTTPException(409, "This cohort is already full. Ask the researcher for a fresh code.")
        participant = await session_manager.register_participant(
            session,
            user_agent=request.headers.get("user-agent"),
            ip_hash=None,
            code_id=code.id,
            role=code.role,
        )
        if external_id or recruitment:
            if external_id:
                participant.external_id = external_id[:128]
            if recruitment:
                participant.recruitment = recruitment
            await participant.save()
        code.uses += 1
        await code.save()

        resp = JSONResponse({"next": _next_for(participant, study)})
        resp.set_cookie(
            PARTICIPANT_COOKIE, str(participant.id),
            httponly=True, samesite="lax", max_age=60 * 60 * 24,
        )
        return resp

   
    if participant.code_id and participant.code_id != code.id:
        raise HTTPException(
            409,
            "This browser is already registered for this study"
            + (f" as {participant.role}" if participant.role else "")
            + ". To join with a different code, use a different browser or a private/incognito window.",
        )

    
    changed = False
    if external_id and not participant.external_id:
        participant.external_id = external_id[:128]
        changed = True
    if recruitment and not participant.recruitment:
        participant.recruitment = recruitment
        changed = True
    if changed:
        await participant.save()
    return JSONResponse({"next": _next_for(participant, study)})


async def _attach_to_session(study: Study, code: Code) -> Session | None:
    """Resolve which Session this newly-joined participant should attach to.

    - Singleplayer: always create a new session.
    - Multiplayer: reuse the code's existing cohort session if it still has
      capacity and is still in the lobby; otherwise spin up a new cohort.
      Returns None when capacity is exhausted and the code should refuse.
    """
    if study.mode != "multiplayer":
        return await session_manager.create_singleplayer_session(study)

    required = study.participants_required or 1
    # 1) This code is already bound to a cohort session that's still open.
    if code.multiplayer_session_id is not None:
        existing = await Session.get(code.multiplayer_session_id)
        if existing is not None and existing.status == "lobby":
            current = await Participant.find(Participant.session_id == existing.id).count()
            if current < required:
                return existing

    open_lobbies = await Session.find(
        Session.study_id == study.id,
        Session.mode == "multiplayer",
        Session.status == "lobby",
    ).to_list()
    for s in open_lobbies:
        current = await Participant.find(Participant.session_id == s.id).count()
        if current < required:
            code.multiplayer_session_id = s.id
            await code.save()
            return s

    
    session = await session_manager.create_multiplayer_session(study)
    code.multiplayer_session_id = session.id
    await code.save()
    return session


def _next_for(participant: Participant, study: Study) -> str:
    """Pick the next page in the participant flow based on current state."""
    if participant.status == "finished":
        return "/p/finish"
    if participant.consented_at is None:
        return "/p/consent"
    # After consent: if no role yet, force the picker (only when study has selectable roles).
    selectable_roles = [r for r in (study.roles or []) if r.get("selectable", True)]
    if not participant.role and selectable_roles:
        return "/p/role"
    if study.mode == "multiplayer" and participant.status in ("lobby", "consented", "joined", "ready"):
        return "/p/lobby"
    return "/p/task"


# ── consent ───────────────────────────────────────────────────────────────

class ConsentPageResponse(NextResponse):
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None
    consent_html: str | None = None


@router.get("/p/consent", response_model=ConsentPageResponse)
async def consent_page(request: Request) -> ConsentPageResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return ConsentPageResponse(next="/")
    # Per-language consent body override.
    from studio.settings import get_settings
    lang = flow.resolve_lang(
        request.query_params.get("lang"),
        request.headers.get("accept-language"),
        get_settings().default_lang,
    )
    by_lang = getattr(study, "consent_text_md_by_lang", None) or {}
    consent_body = study.consent_text_md or ""
    for c in (lang, lang.split("-")[0] if "-" in lang else None):
        if c and c in by_lang:
            consent_body = by_lang[c]
            break
    return ConsentPageResponse(
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
        consent_html=render_markdown(consent_body),
    )


def _post_consent_next(participant: Participant, study: Study) -> str:
    """Where to send the participant right after consent (or after the
    biometric-pairing step, which sits in the same slot). Biometric pairing
    happens before the video recorder shell so each optional-permission
    prompt gets its own dedicated user gesture."""
    if participant.biometric_status == "not_asked" and (study.recording or {}).get("biometric", False):
        return "/p/biometric"
    if (study.recording or {}).get("video", "none") != "none":
        return "/p/run"
    return _next_for(participant, study)


@router.post("/p/consent", response_model=NextResponse)
async def consent_submit(request: Request) -> NextResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return NextResponse(next="/")
    await session_manager.record_consent(participant)
    # Reload so _next_for sees consented_at set.
    fresh = await Participant.get(participant.id)
    if fresh is None:
        return NextResponse(next="/")
    return NextResponse(next=_post_consent_next(fresh, study))


# ── biometric (BLE heart-rate) pairing ─────────────────────────────────────

class BiometricPageResponse(NextResponse):
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None


class BiometricSubmit(BaseModel):
    status: str  # "connected" | "skipped" | "unsupported"


@router.get("/p/biometric", response_model=BiometricPageResponse)
async def biometric_page(request: Request) -> BiometricPageResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return BiometricPageResponse(next="/")
    if participant.consented_at is None:
        return BiometricPageResponse(next="/p/consent")
    if participant.biometric_status != "not_asked" or not (study.recording or {}).get("biometric", False):
        # Already handled, or the study doesn't ask for it — don't strand a
        # direct/back-button visit here.
        next_ = "/p/run" if (study.recording or {}).get("video", "none") != "none" else _next_for(participant, study)
        return BiometricPageResponse(next=next_)
    return BiometricPageResponse(
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
    )


@router.post("/p/biometric", response_model=NextResponse)
async def biometric_submit(request: Request, body: BiometricSubmit) -> NextResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return NextResponse(next="/")
    if body.status not in ("connected", "skipped", "unsupported"):
        raise HTTPException(400, "Invalid biometric status")
    participant.biometric_status = body.status
    await participant.save()
    next_ = "/p/run" if (study.recording or {}).get("video", "none") != "none" else _next_for(participant, study)
    return NextResponse(next=next_)


class RunShellResponse(NextResponse):
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None


@router.get("/p/run", response_model=RunShellResponse)
async def run_shell(request: Request) -> RunShellResponse:
    """Recorder shell (video studies only): a single long-lived page that
    screen+mic records the whole session while the actual flow runs in a nested
    iframe (see ``/p/resume``). getDisplayMedia can't silently re-acquire across
    page loads, so capturing here once keeps one stream for the whole session.
    """
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return RunShellResponse(next="/")
    if participant.status == "finished":
        return RunShellResponse(next="/p/finish")
    if participant.consented_at is None:
        return RunShellResponse(next="/p/consent")
    # Biometric pairing (if enabled) happens before the recorder shell so its
    # gesture-gated prompt isn't entangled with getDisplayMedia's.
    if participant.biometric_status == "not_asked" and (study.recording or {}).get("biometric", False):
        return RunShellResponse(next="/p/biometric")
    # No video → no shell; fall back to the normal next-page chain.
    if (study.recording or {}).get("video", "none") == "none":
        return RunShellResponse(next=_next_for(participant, study))
    return RunShellResponse(
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
    )


class RunDeclineSubmit(BaseModel):
    choice: str  # "continue" | "end"


@router.post("/p/run/decline", response_model=NextResponse)
async def run_decline(request: Request, body: RunDeclineSubmit) -> NextResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return NextResponse(next="/")
    if body.choice not in ("continue", "end"):
        raise HTTPException(400, "Invalid choice")
    if body.choice == "end":
        participant.status = "dropped"
        participant.flow_pointer = len(participant.applied_task_order)
        await participant.save()
        return NextResponse(next="/p/finish")
    participant.recording_status = "declined_continue"
    await participant.save()
    return NextResponse(next="/p/resume")


@router.get("/p/resume", response_model=NextResponse)
async def resume_flow(request: Request) -> NextResponse:
    """Inner-iframe entrypoint for the recorder shell: bounce to the correct next
    page (role / lobby / task / finish) using the normal post-consent chain."""
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return NextResponse(next="/")
    return NextResponse(next=_next_for(participant, study))


# ── role picker ──────────────────────────────────────────────────────────

class RolePickerResponse(NextResponse):
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None
    roles: list[dict[str, Any]] | None = None


@router.get("/p/role", response_model=RolePickerResponse)
async def role_picker(request: Request) -> RolePickerResponse:
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return RolePickerResponse(next="/")
    if participant.consented_at is None:
        return RolePickerResponse(next="/p/consent")
    selectable = [r for r in (study.roles or []) if r.get("selectable", True)]
    if not selectable or participant.role:
        return RolePickerResponse(next=_next_for(participant, study))
    # Compute remaining capacity per role within this session.
    co_participants = await Participant.find(Participant.session_id == session.id).to_list()
    taken: dict[str, int] = {}
    for p in co_participants:
        if p.role:
            taken[p.role] = taken.get(p.role, 0) + 1
    available = []
    for r in selectable:
        cap = r.get("capacity")
        avail = None if cap is None else max(0, cap - taken.get(r["id"], 0))
        available.append({**r, "available": avail, "taken": taken.get(r["id"], 0)})
    return RolePickerResponse(
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
        roles=available,
    )


class RoleStateResponse(BaseModel):
    error: str | None = None
    redirect: str | None = None
    roles: list[dict[str, Any]] | None = None


@router.get("/p/role/state", response_model=RoleStateResponse)
async def role_state(request: Request) -> RoleStateResponse:
    """Polled by the role picker so a role filled by a peer greys out live."""
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return RoleStateResponse(error="not-found")

    if participant.role:
        return RoleStateResponse(redirect="/p/lobby")
    if session.status == "running":
        return RoleStateResponse(redirect="/p/lobby")
    selectable = [r for r in (study.roles or []) if r.get("selectable", True)]
    co_participants = await Participant.find(Participant.session_id == session.id).to_list()
    taken: dict[str, int] = {}
    for p in co_participants:
        if p.role:
            taken[p.role] = taken.get(p.role, 0) + 1
    roles = []
    for r in selectable:
        cap = r.get("capacity")
        avail = None if cap is None else max(0, cap - taken.get(r["id"], 0))
        roles.append({
            "id": r["id"],
            "capacity": cap,
            "available": avail,
            "taken": taken.get(r["id"], 0),
        })
    return RoleStateResponse(roles=roles)


class RolePickRequest(BaseModel):
    role: str = ""


@router.post("/p/role", response_model=NextResponse)
async def role_pick(request: Request, body: RolePickRequest) -> NextResponse:
    role = body.role
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return NextResponse(next="/")
    selectable = {r["id"]: r for r in (study.roles or []) if r.get("selectable", True)}
    if role not in selectable:
        return NextResponse(next="/p/role")
    # Check capacity again under the participant set.
    cap = selectable[role].get("capacity")
    if cap is not None:
        co = await Participant.find(
            Participant.session_id == session.id,
            Participant.role == role,
        ).count()
        if co >= cap and participant.role != role:
            return NextResponse(next="/p/role", error="full")
    await session_manager.assign_role(participant, role)
    fresh = await Participant.get(participant.id)
    return NextResponse(next=_next_for(fresh, study))


# ── lobby (multiplayer) ──────────────────────────────────────────────────

class LobbyPageResponse(NextResponse):
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None
    session: dict[str, Any] | None = None
    participants: list[dict[str, Any]] | None = None
    required: int | None = None


@router.get("/p/lobby", response_model=LobbyPageResponse)
async def lobby_page(request: Request) -> LobbyPageResponse:
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return LobbyPageResponse(next="/")
    if study.mode != "multiplayer":
        return LobbyPageResponse(next="/p/task")
    if session.status == "running":
        return LobbyPageResponse(next="/p/task")
    co_participants = await Participant.find(Participant.session_id == session.id).to_list()
    required = study.participants_required or len(co_participants)
    return LobbyPageResponse(
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
        session=session.model_dump(mode="json"),
        participants=[p.model_dump(mode="json") for p in co_participants],
        required=required,
    )


class LobbyReadyResponse(NextResponse):
    ok: bool | None = None


@router.post("/p/lobby/ready", response_model=LobbyReadyResponse)
async def lobby_ready(request: Request) -> LobbyReadyResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return LobbyReadyResponse(next="/")
    await session_manager.mark_ready(participant)
    return LobbyReadyResponse(ok=True)


class LobbyParticipantOut(BaseModel):
    anon_id: str
    role: str | None
    status: str
    is_self: bool


class LobbyStateResponse(BaseModel):
    error: str | None = None
    session_status: str | None = None
    required: int | None = None
    released: bool | None = None
    participants: list[LobbyParticipantOut] | None = None
    ready_count: int | None = None


@router.get("/p/lobby/state", response_model=LobbyStateResponse)
async def lobby_state(request: Request) -> LobbyStateResponse:
    """Polled by the lobby page. Returns presence + readiness + transition flag."""
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return LobbyStateResponse(error="not-found")
    co_participants = await Participant.find(Participant.session_id == session.id).to_list()
    required = study.participants_required or len(co_participants)
    return LobbyStateResponse(
        session_status=session.status,
        required=required,
        released=session.status == "running",
        participants=[
            LobbyParticipantOut(anon_id=p.anon_id, role=p.role, status=p.status,
                                 is_self=str(p.id) == str(participant.id))
            for p in co_participants
        ],
        ready_count=sum(1 for p in co_participants if p.status in ("ready", "in_session")),
    )


# ── shared polling endpoint ──────────────────────────────────────────────

class ParticipantStateResponse(BaseModel):
    error: str | None = None
    session_status: str | None = None
    session_task_index: int | None = None
    participant_status: str | None = None
    seconds_until_auto_advance: int | None = None


@router.get("/p/state", response_model=ParticipantStateResponse)
async def participant_state(request: Request) -> ParticipantStateResponse:
    """Polled by the task page so multiplayer participants notice when the
    cohort advances. Returns the session's current_task_index so the JS can
    refresh the page when it changes.

    Also re-checks try_advance_session: it's the only thing that can fire an
    `advance.policy: admin` task's `timeout_seconds` safety net once every
    participant has already submitted and is just sitting on the "waiting for
    the cohort" screen polling this endpoint — nothing else calls it again
    after that point (task_submit won't fire twice, and a researcher who
    doesn't notice the live view never hits the force-advance route), so
    without this the cohort would hang past its own configured timeout.
    """
    participant, _study, session = await _resolve_participant(request)
    if participant is None or session is None:
        return ParticipantStateResponse(error="not-found")
    eta = None
    if session.mode == "multiplayer":
        advanced = await session_manager.try_advance_session(session)
        # No point reporting an ETA for the task we just left.
        if not advanced:
            eta = await session_manager.seconds_until_auto_advance(session)
    return ParticipantStateResponse(
        session_status=session.status,
        session_task_index=session.current_task_index,
        participant_status=participant.status,
        seconds_until_auto_advance=eta,
    )


# ── task runner ───────────────────────────────────────────────────────────

class TaskPageResponse(NextResponse):
    interrupted: bool | None = None
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None
    session: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    task: dict[str, Any] | None = None
    task_index: int | None = None
    total_tasks: int | None = None
    block_id: str | None = None
    iframe_url: str | None = None
    waiting_for_cohort: bool | None = None
    is_wizard: bool | None = None


@router.get("/p/task", response_model=TaskPageResponse)
async def task_page(request: Request) -> TaskPageResponse:
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return TaskPageResponse(next="/")
    if participant.status == "finished":
        return TaskPageResponse(next="/p/finish")
    # Studio crashed mid-session and the VA didn't survive — surface clearly.
    if session.status == "interrupted":
        return TaskPageResponse(
            interrupted=True,
            participant=participant.model_dump(mode="json"),
            study=study.model_dump(mode="json"),
            session=session.model_dump(mode="json"),
        )
    # Multiplayer: bounce back to lobby until the cohort has been released.
    if study.mode == "multiplayer" and session.status != "running":
        return TaskPageResponse(next="/p/lobby")

    cfg = _study_to_config(study)
    
    task_by_id, block_id_by_task = _resolve_task_paths(cfg)

    if study.mode == "multiplayer":
        applied = list(session.applied_task_order or [])
        if not applied:
            applied = [t.id for b in cfg.blocks for t in b.tasks]
        cursor = session.current_task_index
    else:
        applied = list(participant.applied_task_order or [])
        if not applied:
            # Legacy participant: lazy-build a declared-order path.
            applied = [t.id for b in cfg.blocks for t in b.tasks]
            participant.applied_task_order = applied
            await participant.save()
        cursor = participant.flow_pointer or 0

    if cursor >= len(applied):
        await session_manager.finish_participant(participant, session)
        return TaskPageResponse(next="/p/finish")

    task_id = applied[cursor]
    if task_id not in task_by_id:
        # YAML changed under our feet; bail safely.
        await session_manager.finish_participant(participant, session)
        return TaskPageResponse(next="/p/finish")
    # Locale resolution: ?lang= query > Accept-Language > settings default.
    from studio.settings import get_settings
    lang = flow.resolve_lang(
        request.query_params.get("lang"),
        request.headers.get("accept-language"),
        get_settings().default_lang,
    )
    task = flow.apply_role_overrides(task_by_id[task_id], participant.role)
    task = flow.apply_lang_overrides(task, lang)
    task = flow.substitute_params(task, cfg.parameters or {})
    block_id = block_id_by_task.get(task_id, "")
    task_index = cursor

    if task.get("type") == "info_screen":
        task["body_html"] = render_markdown(task.get("body_md") or "")
    else:
        task["prompt_html"] = render_markdown(task.get("prompt_md") or "")

    waiting_for_cohort = False
    if study.mode == "multiplayer":
        last = participant.task_runs[-1] if participant.task_runs else None
        if last and last.task_index == task_index and last.ended_at is not None:
            waiting_for_cohort = True

    # Start the task if it is not already started (and not waiting).
    if not waiting_for_cohort and (
        not participant.task_runs
        or participant.task_runs[-1].task_id != task["id"]
        or participant.task_runs[-1].ended_at is not None
    ):
        await session_manager.start_task(
            participant, session, task, task_index, block_id, study_config=cfg,
        )
        participant = await Participant.get(participant.id)

    # Spawn / reuse the VA for any task that wants it visible.
    iframe_url = None
    wants_va = task["type"] == "va_interaction" or task.get("with_va", False)
    va_system_id = task.get("va_system") or cfg.primary_va_system
    if wants_va and va_system_id and va_system_id in cfg.va_systems:
        variant = task.get("variant") if task["type"] == "va_interaction" else None
        try:
            iframe_url = await session_manager.ensure_va_started(
                session, cfg, va_system_id, variant,
            )
        except Exception:
            iframe_url = None
    if iframe_url:
        agent_id: str | None = None
        if _role_is_wizard_sync(study, participant.role):
            agent_id = "studio_replayer"
        elif participant.role:
            agent_id = _role_agent_id(study, participant.role) or participant.role
        else:
            roles = list(study.roles or [])
            if roles:
                agent_id = roles[0].get("agent_id") or roles[0].get("id")
            else:
                agent_id = "analyst"
        if agent_id:
            sep = "&" if "?" in iframe_url else "?"
            iframe_url = f"{iframe_url}{sep}role={agent_id}"

    return TaskPageResponse(
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
        ui=study.ui,
        task=task,
        task_index=task_index,
        total_tasks=len(applied),
        block_id=block_id,
        iframe_url=iframe_url,
        waiting_for_cohort=waiting_for_cohort,
        is_wizard=_role_is_wizard_sync(study, participant.role),
    )


class TaskSubmitRequest(BaseModel):
    """``value``'s shape is polymorphic by ``task["type"]`` (see
    ``_extract_answer``) — single_choice/free_text: str, multi_choice:
    list[str], likert: dict[str, int], va_interaction: arbitrary JSON — so
    it stays loosely typed here rather than forcing a false union across
    task types.
    """

    action: str = "submit"
    value: Any = None


@router.post("/p/task", response_model=NextResponse)
async def task_submit(request: Request, body: TaskSubmitRequest) -> NextResponse:
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        return NextResponse(next="/")

    cfg = _study_to_config(study)
    task_by_id, block_id_by_task = _resolve_task_paths(cfg)

    if not participant.task_runs or participant.task_runs[-1].ended_at is not None:
        return NextResponse(next="/p/task")
    run = participant.task_runs[-1]
    task_id = run.task_id
    if task_id not in task_by_id:
        return NextResponse(next="/p/finish")
    task = task_by_id[task_id]
    block_id = block_id_by_task.get(task_id, "")

    action = body.action or "submit"
    skipped = (action == "skip")
    answer: Any = None
    if not skipped:
        answer = _extract_answer(task, body.value)
    if action == "submit":
        required_step_ids = [
            s.get("id") for s in (task.get("task_steps") or [])
            if s.get("required") and s.get("id")
        ]
        if required_step_ids:
            checked = set(run.checked_steps or [])
            missing = [s for s in required_step_ids if s not in checked]
            if missing:
                raise HTTPException(
                    400,
                    f"Required step(s) not checked: {', '.join(missing)}",
                )

    await session_manager.end_task(participant, session, task, answer, block_id, skipped=skipped)

    if study.mode == "multiplayer":
        session = await Session.get(session.id) or session
        await session_manager.try_advance_session(session)
    else:
        # Singleplayer: resolve `next:` rules to decide where the participant goes.
        await _resolve_singleplayer_next(
            participant=participant, study=study, cfg=cfg,
            task=task, run=run, answer=answer,
        )

    return NextResponse(next="/p/task")


async def _resolve_singleplayer_next(
    *,
    participant: Participant,
    study: Study,
    cfg: StudyConfig,
    task: dict[str, Any],
    run: Any,
    answer: Any,
) -> None:
    """Advance ``participant.flow_pointer`` based on the task's ``next:`` rules.

    Falls back to linear advancement when no rules match. Branching may also
    drop the participant or end the session — see flow.resolve_next.
    """
    fresh = await Participant.get(participant.id) or participant
    applied = list(fresh.applied_task_order or [])
    if not applied:
        applied = [t.id for b in cfg.blocks for t in b.tasks]
        fresh.applied_task_order = applied
    cursor = fresh.flow_pointer or 0

    _by_id, block_id_by_task = _resolve_task_paths(cfg)
    block_id_by_index = [block_id_by_task.get(tid, "") for tid in applied]

    directive = flow.resolve_next(
        task.get("next"),
        current_index=cursor,
        applied_task_order=applied,
        block_index_by_task={t: i for i, t in enumerate(applied)},
        block_id_by_index=block_id_by_index,
        answer=answer,
        score=getattr(run, "score", None),
        correct=getattr(run, "correct", None),
        role=fresh.role,
        params=cfg.parameters or {},
    )

    if directive["kind"] == "drop":
        fresh.status = "dropped"
        fresh.flow_pointer = len(applied)
        await fresh.save()
        return
    if directive["kind"] == "end":
        # Force finish on next /p/task render.
        fresh.flow_pointer = len(applied)
        await fresh.save()
        return
    if directive["kind"] == "skip_block":
        cur_block = block_id_by_task.get(applied[cursor], "") if cursor < len(applied) else ""
        next_idx = cursor + 1
        while next_idx < len(applied) and block_id_by_task.get(applied[next_idx], "") == cur_block:
            next_idx += 1
        fresh.flow_pointer = next_idx
        await fresh.save()
        return
    if directive["kind"] in ("task", "block", "next"):
        new_idx = directive.get("index") or cursor + 1
        fresh.flow_pointer = new_idx
        await fresh.save()
        return


def _role_agent_id(study: Study, role_id: str) -> str | None:
    for r in (study.roles or []):
        if r.get("id") == role_id:
            return r.get("agent_id") or role_id
    return None


def _role_is_wizard_sync(study: Study, role_id: str | None) -> bool:
    if not role_id:
        return False
    for r in (study.roles or []):
        if r.get("id") == role_id and r.get("wizard_panel"):
            return True
    return False


async def _role_is_wizard(study: Study, role_id: str | None) -> bool:
    return _role_is_wizard_sync(study, role_id)


# ── Wizard-of-Oz control panel (server-side endpoints) ──────────────────

async def _wizard_resolve_va(participant, study, session):
    """Resolve the running VA for the wizard's current task. Raises HTTPException."""
    cfg = _study_to_config(study)
    task_by_id, _ = _resolve_task_paths(cfg)
    current_task_id = participant.task_runs[-1].task_id if participant.task_runs else None
    task = task_by_id.get(current_task_id) if current_task_id else None
    va_system_id = (task or {}).get("va_system") if task else None
    va_system_id = va_system_id or cfg.primary_va_system
    if not va_system_id:
        raise HTTPException(400, "Study has no VA system")
    from studio.orchestrator.va_spawner import va_spawner
    spawned = va_spawner.get(str(session.id), va_system_id)
    if spawned is None:
        raise HTTPException(409, f"VA '{va_system_id}' is not running")
    return current_task_id, va_system_id, spawned


class WizardWriteRequest(BaseModel):
    actor: str = "wizard"
    key: str
    value_json: str = ""


class WizardWriteResponse(BaseModel):
    ok: bool = True
    actor: str
    key: str
    va_system_id: str


@router.post("/p/wizard/agent_write", response_model=WizardWriteResponse)
async def wizard_agent_write(request: Request, body: WizardWriteRequest) -> WizardWriteResponse:
    """Wizard-only: write a WorldState key ATTRIBUTED TO A CHOSEN AGENT.

    Body: ``{ actor, key, value_json }``. The write lands in the VA as that
    agent's action (audit log + per-agent replay lane), so the participant sees
    "the AI" act. The operator drives the agents in full but the action is never
    attributed to — and can never impersonate — a participant.
    """
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        raise HTTPException(401, "No active participant")
    if not await _role_is_wizard(study, participant.role):
        raise HTTPException(403, "Wizard panel is only available to wizard roles")

    actor = body.actor.strip() or "wizard"
    key = body.key.strip()
    raw = body.value_json.strip()
    if not key:
        raise HTTPException(400, "Missing key")
    try:
        value = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        value = raw  # accept bare strings without quotes

    current_task_id, va_system_id, spawned = await _wizard_resolve_va(participant, study, session)
    from studio.orchestrator.va_client import send_wizard_action, VAClientError
    try:
        await send_wizard_action(spawned.iframe_url, {
            "action": "wizard.act", "actor": actor, "key": key, "value": value,
        })
    except VAClientError as exc:
        raise HTTPException(502, f"VA push failed: {exc}")

    await session_manager._record_event(
        session.study_id, session.id, type="wizard_agent_write",
        participant_id=participant.id, task_id=current_task_id,
        va_system_id=va_system_id, meta={"actor": actor, "key": key, "value": value},
    )
    return WizardWriteResponse(actor=actor, key=key, va_system_id=va_system_id)


class WizardSayRequest(BaseModel):
    actor: str = "wizard"
    text: str


class WizardSayResponse(BaseModel):
    ok: bool = True
    actor: str
    va_system_id: str


@router.post("/p/wizard/agent_say", response_model=WizardSayResponse)
async def wizard_agent_say(request: Request, body: WizardSayRequest) -> WizardSayResponse:
    """Wizard-only: post a chat message AS A CHOSEN AGENT.

    Body: ``{ actor, text }``. Lets the operator voice the AI conversationally.
    """
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        raise HTTPException(401, "No active participant")
    if not await _role_is_wizard(study, participant.role):
        raise HTTPException(403, "Wizard panel is only available to wizard roles")

    actor = body.actor.strip() or "wizard"
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Missing text")

    current_task_id, va_system_id, spawned = await _wizard_resolve_va(participant, study, session)
    from studio.orchestrator.va_client import send_wizard_action, VAClientError
    try:
        await send_wizard_action(spawned.iframe_url, {
            "action": "wizard.say", "actor": actor, "text": text,
        })
    except VAClientError as exc:
        raise HTTPException(502, f"VA push failed: {exc}")

    await session_manager._record_event(
        session.study_id, session.id, type="wizard_agent_say",
        participant_id=participant.id, task_id=current_task_id,
        va_system_id=va_system_id, meta={"actor": actor, "text": text},
    )
    return WizardSayResponse(actor=actor, va_system_id=va_system_id)


class WizardAdvanceResponse(BaseModel):
    ok: bool = True
    scope: str
    advanced: bool | None = None


@router.post("/p/wizard/advance", response_model=WizardAdvanceResponse)
async def wizard_advance(request: Request) -> WizardAdvanceResponse:
    """Wizard-only: force the cohort to advance to the next task."""
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        raise HTTPException(401, "No active participant")
    if not await _role_is_wizard(study, participant.role):
        raise HTTPException(403, "Wizard panel is only available to wizard roles")
    if study.mode != "multiplayer":
        fresh = await Participant.get(participant.id)
        if fresh and fresh.applied_task_order:
            fresh.flow_pointer = min((fresh.flow_pointer or 0) + 1, len(fresh.applied_task_order))
            await fresh.save()
        return WizardAdvanceResponse(scope="self")
    advanced = await session_manager.try_advance_session(session, force=True)
    return WizardAdvanceResponse(scope="cohort", advanced=advanced)


class WizardPeerOut(BaseModel):
    id: str
    anon_id: str
    role: str | None
    status: str
    task_id: str | None
    task_index: int
    is_self: bool


class WizardPeersResponse(BaseModel):
    peers: list[WizardPeerOut]


@router.get("/p/wizard/peers", response_model=WizardPeersResponse)
async def wizard_peers(request: Request) -> WizardPeersResponse:
    """Wizard-only: snapshot of peer status (anon_id + role + current task)."""
    participant, study, session = await _resolve_participant(request)
    if participant is None or study is None or session is None:
        raise HTTPException(401, "No active participant")
    if not await _role_is_wizard(study, participant.role):
        raise HTTPException(403, "Wizard panel is only available to wizard roles")
    peers = await Participant.find(Participant.session_id == session.id).to_list()
    return WizardPeersResponse(peers=[
        WizardPeerOut(
            id=str(p.id),
            anon_id=p.anon_id,
            role=p.role,
            status=p.status,
            task_id=(p.task_runs[-1].task_id if p.task_runs else None),
            task_index=(p.task_runs[-1].task_index if p.task_runs else 0),
            is_self=str(p.id) == str(participant.id),
        )
        for p in peers
    ])


def _extract_answer(task: dict[str, Any], value: Any) -> Any:
    """Pull a task-type-specific answer out of the submitted ``value``."""
    ttype = task["type"]
    if ttype == "info_screen":
        return None
    if ttype == "single_choice":
        return value
    if ttype == "multi_choice":
        return list(value or [])
    if ttype == "likert":
        raw = value or {}
        out: dict[str, int] = {}
        for item in task.get("items", []):
            v = raw.get(item["id"])
            if v is not None:
                try:
                    out[item["id"]] = int(v)
                except (TypeError, ValueError):
                    pass
        return out
    if ttype in ("slider", "number_input"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if ttype == "free_text":
        return value if value is not None else ""
    if ttype == "va_interaction":
        # v0 captures the raw submitted JSON if any, plus a free-text note.
        return value
    return None


# ── task_steps (auto + manual check) ─────────────────────────────────────

class TaskStepsResponse(BaseModel):
    task_id: str | None
    checked: list[str]


@router.get("/p/task/steps", response_model=TaskStepsResponse)
async def task_steps_state(request: Request) -> TaskStepsResponse:
    """Return the list of checked step ids for the participant's active task.

    Polled by the participant UI so the right-sidebar checklist reflects both
    user clicks and Studio's auto-check engine.
    """
    participant, _study, _session = await _resolve_participant(request)
    if participant is None or not participant.task_runs:
        return TaskStepsResponse(task_id=None, checked=[])
    run = participant.task_runs[-1]
    if run.ended_at is not None:
        return TaskStepsResponse(task_id=run.task_id, checked=[])
    return TaskStepsResponse(task_id=run.task_id, checked=list(run.checked_steps))


class CheckStepRequest(BaseModel):
    step_id: str
    checked: bool = True


class CheckStepResponse(BaseModel):
    checked: list[str]


@router.post("/p/task/check_step", response_model=CheckStepResponse)
async def task_check_step(request: Request, body: CheckStepRequest) -> CheckStepResponse:
    """Persist a manual check/uncheck of a task_step.

    The auto-check engine writes via session_manager.record_step_checked, so
    here we mirror manual ticks through the same path (event row + persistence).
    """
    step_id = body.step_id
    is_checked = body.checked

    participant, _study, session = await _resolve_participant(request)
    if participant is None or session is None or not participant.task_runs:
        raise HTTPException(401, "No active task")
    run = participant.task_runs[-1]
    if run.ended_at is not None:
        raise HTTPException(400, "Task already ended")

    study = await Study.get(participant.study_id)
    if study is None:
        raise HTTPException(404, "Study gone")
    cfg = _study_to_config(study)
    flat_tasks = _flat_tasks_with_block(cfg)
    if run.task_index >= len(flat_tasks):
        raise HTTPException(400, "Task index out of range")
    task, _block_id = flat_tasks[run.task_index]

    step_def = next((s for s in (task.get("task_steps") or []) if s.get("id") == step_id), None)
    if step_def is not None and step_def.get("mode") == "auto":
        raise HTTPException(
            400,
            f"step '{step_id}' is mode=auto — it can only be checked by MIVAIS auto-detection",
        )

    if is_checked:
        await session_manager.record_step_checked(
            participant, session, task, step_id, source="manual",
        )
    else:
        if step_id in run.checked_steps:
            run.checked_steps.remove(step_id)
            await participant.save()
    fresh = await Participant.get(participant.id)
    return CheckStepResponse(checked=list(fresh.task_runs[-1].checked_steps) if fresh and fresh.task_runs else [])


class VaEventResponse(BaseModel):
    ok: bool
    reason: str | None = None


@router.post("/p/va/event", response_model=VaEventResponse)
async def task_va_event(request: Request) -> VaEventResponse:
    """Record a browser-relayed event, as a fallback for VAs whose frontend
    relays events up to the embedding page instead of relying solely on
    ``ws_collector``'s live ``studio_collector`` connection to their Gateway
    (e.g. a non-MIVAIS VA that cannot be reached over the Gateway protocol).

    We persist it as a MIVAIS-sourced :class:`Event` — identical in shape to
    what the collector would write, so it appears in the admin recording
    timeline — and feed it to the in-process auto-check engine so task_steps
    still auto-tick. Mirrors ``ws_collector._persist_event`` plus a participant tag.
    """
    participant, _study, session = await _resolve_participant(request)
    if participant is None or session is None or not participant.task_runs:
        raise HTTPException(401, "No active task")
    run = participant.task_runs[-1]
    if run.ended_at is not None:
        return VaEventResponse(ok=False, reason="task-ended")

    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be a JSON object")
    if not isinstance(raw, dict):
        raise HTTPException(400, "Body must be a JSON object")
    event_type = str(raw.get("type") or "").strip()
    if not event_type:
        raise HTTPException(400, "Event needs a non-empty 'type'")

    study = await Study.get(participant.study_id)
    cfg = _study_to_config(study) if study is not None else None
    task = None
    if cfg is not None:
        task_by_id, _block_by_task = _resolve_task_paths(cfg)
        task = task_by_id.get(run.task_id)
    logging_id = (task.get("mivais_config") or {}).get("logging_id") if task else None
    va_system_id = (
        (task.get("va_system") if task else None)
        or (cfg.primary_va_system if cfg is not None else None)
        or next(iter(session.vas), None)
    )

    va = cfg.va_systems.get(va_system_id) if (cfg is not None and va_system_id) else None
    if va is not None and not getattr(va, "external", False):
        return VaEventResponse(ok=False, reason="tailer-owns-recording")

    meta = {k: v for k, v in raw.items() if k not in ("t", "type")}
    try:
        await Event(
            study_id=session.study_id,
            session_id=session.id,
            participant_id=participant.id,
            task_id=run.task_id,
            logging_id=logging_id,
            va_system_id=va_system_id,
            t_ms=session.t_ms_now(),
            source=SOURCE_MIVAIS,
            type=event_type,
            meta=meta,
        ).insert()
    except Exception:
        raise HTTPException(500, "Could not record event")

    # Drive auto-check from the same event stream the tailer would feed.
    try:
        auto_check.feed_event(str(session.id), raw)
    except Exception:
        pass
    return VaEventResponse(ok=True)


# ── finish ────────────────────────────────────────────────────────────────

class FinishResponse(NextResponse):
    external_redirect: str | None = None
    completion_code: str | None = None
    participant: dict[str, Any] | None = None
    study: dict[str, Any] | None = None


@router.get("/p/finish", response_model=FinishResponse)
async def finish_page(request: Request) -> FinishResponse:
    participant, study, _session = await _resolve_participant(request)
    if participant is None or study is None:
        return FinishResponse(next="/")
    redirect_tpl = (study.completion_redirect_url or "").strip() if hasattr(study, "completion_redirect_url") else ""
    explicit_code = study.completion_code if hasattr(study, "completion_code") else None
    if redirect_tpl:
        completion_code = explicit_code or study.slug
        try:
            url = redirect_tpl.format(
                anon_id=participant.anon_id,
                external_id=participant.external_id or "",
                completion_code=completion_code,
            )
        except Exception:
            url = redirect_tpl
        return FinishResponse(external_redirect=url, completion_code=completion_code)
    return FinishResponse(
        completion_code=explicit_code,
        participant=participant.model_dump(mode="json"),
        study=study.model_dump(mode="json"),
    )


# ── helpers ───────────────────────────────────────────────────────────────

async def _resolve_participant(request: Request) -> tuple[Participant | None, Study | None, Session | None]:
    pid = request.cookies.get(PARTICIPANT_COOKIE)
    if not pid:
        return None, None, None
    try:
        participant = await Participant.get(PydanticObjectId(pid))
    except Exception:
        return None, None, None
    if participant is None:
        return None, None, None
    study = await Study.get(participant.study_id)
    session = await Session.get(participant.session_id)
    return participant, study, session


def _study_to_config(study: Study) -> StudyConfig:
    """Reconstruct a StudyConfig from the stored YAML so we get typed access."""
    return StudyConfig.model_validate({
        "id": study.slug,
        "name": study.name,
        "version": study.version,
        "mode": study.mode,
        "participants_required": study.participants_required,
        "consent_text_md": study.consent_text_md,
        "consent_text_md_by_lang": getattr(study, "consent_text_md_by_lang", None) or {},
        "va_systems": study.va_systems or {},
        "primary_va_system": study.primary_va_system,
        "roles": study.roles or [],
        "advance_policy": study.advance_policy or "all",
        "block_order": getattr(study, "block_order", None) or "declared",
        "block_orders": getattr(study, "block_orders", None) or [],
        "parameters": getattr(study, "parameters", None) or {},
        "completion_redirect_url": getattr(study, "completion_redirect_url", None),
        "completion_code": getattr(study, "completion_code", None),
        "recording": study.recording or {},
        "ui": study.ui or {},
        "blocks": study.blocks or [],
    })


def _flat_tasks_with_block(cfg: StudyConfig) -> list[tuple[dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], str]] = []
    for block in cfg.blocks:
        for task in block.tasks:
            out.append((task.model_dump(), block.id))
    return out


def _resolve_task_paths(cfg: StudyConfig) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Return ``(tasks_by_id, block_id_by_task_id)`` from the study config.

    Tasks are returned as plain dicts (post-Pydantic-dump) so downstream code
    can mutate them without affecting the cached StudyConfig.
    """
    by_id: dict[str, dict[str, Any]] = {}
    block_id_by_task: dict[str, str] = {}
    for block in cfg.blocks:
        for task in block.tasks:
            td = task.model_dump()
            by_id[task.id] = td
            block_id_by_task[task.id] = block.id
    return by_id, block_id_by_task
