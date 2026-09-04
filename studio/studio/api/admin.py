"""Admin: studies, sessions (catalog + live + replay), codes, exports. JSON API.

Every route here is consumed by the React admin SPA (studio/frontend,
src/admin) via fetch. Mutating routes that used to redirect with
``?error=``/``?ok=`` query params now just return ``{"error": "..."}`` or
``{"ok": true, ...}`` directly.
"""
from __future__ import annotations

import csv
import io
import json
import re as _re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from beanie import PydanticObjectId
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from studio.api.schemas import OkResponse
from studio.api.analytics_helpers import (
    compare_studies,
    dashboard_extras,
    overview_stats,
    participant_journey,
    per_task_drilldown,
    per_task_summary,
    replay_payload,
    session_recording,
    session_status_breakdown,
    sessions_timeseries,
    study_funnel,
    study_stats,
    timeline_density,
)
from studio.auth import create_token, hash_password, verify_password
from studio.auth.deps import ADMIN_COOKIE, optional_admin
from studio.config.loader import StudyLoadError, load_study_dir
from studio.config.loader import _resolve_ref as _loader_resolve_ref
from studio.config.schemas import Task
from studio.config.upload import StudyUploadError, parse_uploaded_study_yaml, stage_study_yaml
from studio.orchestrator.session_manager import session_manager
from studio.models import (
    AdminUser, AudioChunk, AuditEntry, Code, Event, Participant, SavedView, Session, Study, Transcript,
)
from studio.settings import get_settings

def _clean_id_keys(obj: Any) -> Any:
    """Rename Mongo's `_id` key to `id` recursively.

    FastAPI's automatic response serialization (used here since none of these
    routes declare a Pydantic `response_model`) runs `jsonable_encoder` with
    `by_alias=True`, which surfaces Beanie's `_id` alias for every embedded
    Study/Session/Participant/... document instead of the clean `id` field
    name the frontend's TypeScript types (and /api/p/* responses, which use
    an explicit `.model_dump(mode="json")`) assume. Rather than hand-convert
    every embedded document at each call site, this walks the already-encoded
    response body once and normalizes the key.
    """
    if isinstance(obj, dict):
        return {("id" if k == "_id" else k): _clean_id_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_id_keys(v) for v in obj]
    return obj


class AdminJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(_clean_id_keys(content))


router = APIRouter(prefix="/api/admin", tags=["admin"], default_response_class=AdminJSONResponse)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _require_admin(request: Request) -> str:
    me = optional_admin(request)
    if me is None:
        raise HTTPException(401, "Admin login required")
    return me


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


# ── auth ──────────────────────────────────────────────────────────────────


class MeResponse(BaseModel):
    username: str | None


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


class LoginResponse(BaseModel):
    ok: bool = True
    username: str


# Per-IP failed-login throttle (in-process; Studio is single-worker by design).
_login_failures: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_throttled(ip: str) -> bool:
    s = get_settings()
    now = time.monotonic()
    dq = _login_failures[ip]
    while dq and now - dq[0] > s.login_window_seconds:
        dq.popleft()
    return len(dq) >= s.login_max_attempts


@router.get("/me", response_model=MeResponse)
async def admin_me(request: Request) -> MeResponse:
    """The SPA's auth-guard check on load."""
    return MeResponse(username=optional_admin(request))


@router.post("/login", response_model=LoginResponse)
async def login_submit(request: Request, body: LoginRequest, response: Response) -> LoginResponse:
    """Authenticate against the AdminUser collection.

    The bootstrap step in app startup seeds an initial user from
    `STUDIO_ADMIN_USERNAME` / `STUDIO_ADMIN_PASSWORD` on first boot. After
    that, the env values are no longer trusted — only AdminUser docs are.
    """
    ip = _client_ip(request)
    if _login_throttled(ip):
        raise HTTPException(429, "Too many attempts. Try again later.")

    user = await AdminUser.find_one(AdminUser.username == body.username.strip())
    if user is None or not verify_password(body.password, user.pw_hash):
        # Count only failures, so legitimate repeated logins aren't locked out.
        _login_failures[ip].append(time.monotonic())
        raise HTTPException(401, "Invalid credentials")
    _login_failures.pop(ip, None)  # clear on success
    user.last_login = _utcnow_naive()
    await user.save()

    settings = get_settings()
    token = create_token(subject=user.username)
    response.set_cookie(
        ADMIN_COOKIE, token, httponly=True, samesite="lax",
        secure=settings.cookie_secure_effective, path="/",
        max_age=settings.jwt_ttl_minutes * 60,
    )
    await _audit(user.username, "admin.login", "admin_user", str(user.id), {})
    return LoginResponse(username=user.username)


@router.post("/logout", response_model=OkResponse)
async def logout(response: Response) -> OkResponse:
    # delete_cookie must match the attributes used at set time to reliably clear.
    response.delete_cookie(
        ADMIN_COOKIE, path="/", httponly=True, samesite="lax",
        secure=get_settings().cookie_secure_effective,
    )
    return OkResponse()


# ── studies ───────────────────────────────────────────────────────────────


class RegisterStudyRequest(BaseModel):
    dir_name: str = ""


class RegisterStudyResponse(BaseModel):
    ok: bool = True
    slug: str
    code: str


class OkMessageResponse(BaseModel):
    """Shared by routes that succeed with a human-readable status line
    (`reload_study`, `study_yaml_save`) — `warning` is set instead of
    `message` when the save succeeded but a subsequent reload-from-disk did
    not (see `study_yaml_save`).
    """

    ok: bool = True
    message: str | None = None
    warning: str | None = None


class SaveYamlRequest(BaseModel):
    relative_path: str = ""
    content: str = ""


class PatchStudyRequest(BaseModel):
    archived: bool | None = None


class StudyDetailResponse(BaseModel):
    study: Study
    codes: list[Code]
    sessions: list[Session]
    stats: dict[str, Any]
    tasks: list[dict[str, Any]]
    share_base: str


class AdminStudyRow(BaseModel):
    study: Study
    n_sessions: int
    n_completed: int


class OverviewStats(BaseModel):
    n_studies: int
    n_sessions: int
    n_sessions_completed: int
    n_participants: int
    n_participants_finished: int
    n_events: int
    completion_rate: float


class DashboardExtras(BaseModel):
    active_now: int
    sessions_today: int
    sessions_7d: int
    n_abandoned: int
    by_mode: dict[str, int]
    n_markers: int
    n_notes: int
    n_annotations: int
    avg_duration_s: float
    avg_duration_human: str
    n_with_duration: int


class TimeseriesPoint(BaseModel):
    date: str
    label: str
    total: int
    completed: int


class StatusBreakdownEntry(BaseModel):
    status: str
    count: int


class DashboardResponse(BaseModel):
    per_study: list[AdminStudyRow]
    per_study_archived: list[AdminStudyRow]
    overview: OverviewStats
    extras: DashboardExtras
    timeseries: list[TimeseriesPoint]
    status_breakdown: list[StatusBreakdownEntry]


@router.get("/", response_model=DashboardResponse)
async def studies_list(request: Request) -> DashboardResponse:
    await _require_admin(request)
    studies = await Study.find().sort("-created_at").to_list()

    # Per-study mini stats for the table, split into active vs archived.
    per_study: list[AdminStudyRow] = []
    per_study_archived: list[AdminStudyRow] = []
    for study in studies:
        n_sessions = await Session.find(Session.study_id == study.id).count()
        n_completed = await Session.find(
            Session.study_id == study.id, Session.status == "completed"
        ).count()
        row = AdminStudyRow(study=study, n_sessions=n_sessions, n_completed=n_completed)
        (per_study_archived if study.archived else per_study).append(row)

    overview = await overview_stats()
    extras = await dashboard_extras()
    timeseries = await sessions_timeseries(days=14)
    status_breakdown = await session_status_breakdown()

    return DashboardResponse(
        per_study=per_study,
        per_study_archived=per_study_archived,
        overview=OverviewStats(**overview),
        extras=DashboardExtras(**extras),
        timeseries=[TimeseriesPoint(**t) for t in timeseries],
        status_breakdown=[StatusBreakdownEntry(**s) for s in status_breakdown],
    )


class AvailableStudy(BaseModel):
    dir_name: str
    slug: str | None
    name: str | None
    version: int | None
    mode: str | None
    digest: str | None
    status: str
    registered_id: str | None
    error: str | None


class NewStudyPageResponse(BaseModel):
    available: list[AvailableStudy]


@router.get("/studies/new", response_model=NewStudyPageResponse)
async def new_study_page(request: Request) -> NewStudyPageResponse:
    await _require_admin(request)
    available = await _list_available_studies()
    return NewStudyPageResponse(available=[AvailableStudy(**a) for a in available])



_INUSE_DIR = "_inuse"


def _is_inuse_dir(study_dir: str | None) -> bool:
    return bool(study_dir) and study_dir.replace("\\", "/").split("/", 1)[0] == _INUSE_DIR


async def _next_free_slug(base_slug: str, studies_dir: Path) -> str:
    """First free registration slot: ``<id>``, then ``<id>-v2``, ``-v3``, …
    A slot is taken if a Study document holds the slug OR a frozen copy dir
    exists (covers deleted-from-DB-but-still-on-disk leftovers)."""
    n = 1
    while True:
        slug = base_slug if n == 1 else f"{base_slug}-v{n}"
        if (await Study.find_one(Study.slug == slug) is None
                and not (studies_dir / _INUSE_DIR / slug).exists()):
            return slug
        n += 1


def _freeze_study_copy(source: Path, studies_dir: Path, slug: str) -> Path:
    """Materialize a self-contained frozen copy of a library study.

    - the study's own ``tasks/<id>.yaml`` files are copied verbatim
    - every ``$ref`` target (shared ``_lib`` tasks, fragments from other
      studies) is copied into the frozen ``tasks/`` and the ref rewritten to
      point there, so nothing in the copy depends on editable library files
    - ``id:`` is rewritten to the (possibly versioned) registration slug

    Comments inside task files survive (verbatim copy); study.yaml is
    re-serialized (its refs change), so its comments do not.
    """
    import re as _re_mod
    import shutil

    frozen = (studies_dir / _INUSE_DIR / slug).resolve()
    if frozen.exists():
        raise HTTPException(409, f"In-use copy '{slug}' already exists on disk")

    data = yaml.safe_load((source / "study.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise HTTPException(400, "study.yaml must be a mapping")
    data["id"] = slug

    (frozen / "tasks").mkdir(parents=True)
    try:
        def _place(src_file: Path, preferred: str) -> str:
            """Copy ``src_file`` into frozen tasks/ under ``preferred`` (or a
            numbered variant on content clash); reuse identical copies."""
            content = src_file.read_bytes()
            name, i = preferred, 2
            while True:
                target = frozen / "tasks" / f"{name}.yaml"
                if not target.exists():
                    target.write_bytes(content)
                    return name
                if target.read_bytes() == content:
                    return name
                name = f"{preferred}-{i}"
                i += 1

        blocks = data.get("blocks") or []
        # Pass 1: bare-id references — their filename MUST stay the task id.
        for block in blocks:
            for ref in (block.get("tasks") or []):
                if isinstance(ref, str):
                    placed = _place(source / "tasks" / f"{ref}.yaml", ref)
                    if placed != ref:  # id-file clash — cannot happen for valid studies
                        raise HTTPException(500, f"task id clash while freezing '{ref}'")
        # Pass 2: $ref entries — materialize the target and point the ref at it.
        studies_root = studies_dir.resolve()
        for block in blocks:
            for ref in (block.get("tasks") or []):
                if isinstance(ref, dict) and "$ref" in ref:
                    ref_file = _loader_resolve_ref(str(ref["$ref"]), study_base=source.resolve(),
                                                   studies_root=studies_root)
                    stem = _re_mod.sub(r"[^A-Za-z0-9_-]", "-", ref_file.stem) or "task"
                    ref["$ref"] = f"tasks/{_place(ref_file, stem)}.yaml"

        (frozen / "study.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        return frozen
    except Exception:
        shutil.rmtree(frozen, ignore_errors=True)
        raise


async def _register_study_from_dir(me, dir_name: str) -> RegisterStudyResponse:
    """Freeze ``studies/<dir_name>`` into the in-use section and register the copy.

    Shared by both registration paths: picking a library directory, and
    uploading a study.yaml (which writes the file first, then lands here).
    Registration never locks the library — the frozen copy is what sessions
    run and what the preregistration digest covers.
    """
    import shutil

    studies_dir = get_settings().studies_dir
    target = (studies_dir / dir_name).resolve()
    if not _is_inside(target, studies_dir.resolve()) or not target.is_dir():
        raise HTTPException(400, f"Unknown study directory '{dir_name}'")
    if _is_inuse_dir(dir_name):
        raise HTTPException(400, "In-use copies are frozen — register the library study instead")

    try:
        src_config, _m, _d = load_study_dir(target)
    except StudyLoadError as exc:
        raise HTTPException(400, str(exc).replace("\n", " ")[:200])

    slug = await _next_free_slug(src_config.id, studies_dir)
    frozen = _freeze_study_copy(target, studies_dir, slug)
    try:
        config, _manifest, digest = load_study_dir(frozen)
    except StudyLoadError as exc:
        shutil.rmtree(frozen, ignore_errors=True)
        raise HTTPException(500, f"Frozen copy failed to validate: {str(exc)[:200]}")

    study = Study(
        slug=config.id,
        name=config.name,
        version=config.version,
        mode=config.mode,
        participants_required=config.participants_required,
        consent_text_md=config.consent_text_md,
        consent_text_md_by_lang=dict(config.consent_text_md_by_lang or {}),
        va_systems={k: v.model_dump() for k, v in config.va_systems.items()},
        primary_va_system=config.primary_va_system,
        roles=[r.model_dump() for r in config.roles],
        advance_policy=config.advance_policy,
        block_order=config.block_order,
        block_orders=list(config.block_orders or []),
        parameters=dict(config.parameters or {}),
        completion_redirect_url=config.completion_redirect_url,
        completion_code=config.completion_code,
        recording=config.recording.model_dump(),
        ui=config.ui.model_dump(),
        blocks=[block.model_dump() for block in config.blocks],
        metrics=[m.engine_dict() for m in config.metrics],
        replay=config.replay.model_dump(),
        study_dir=f"{_INUSE_DIR}/{slug}",
        yaml_hash=digest,
    )
    await study.insert()
    code = await _generate_code(study.id)
    await _audit(me, "study.register", "study", str(study.id),
                 {"slug": study.slug, "source_dir": dir_name, "first_code": code.code})
    return RegisterStudyResponse(slug=study.slug, code=code.code)


@router.post("/studies/register", response_model=RegisterStudyResponse)
async def register_study(request: Request, body: RegisterStudyRequest) -> RegisterStudyResponse:
    me = await _require_admin(request)
    return await _register_study_from_dir(me, body.dir_name)


@router.post("/studies/register-upload", response_model=RegisterStudyResponse)
async def register_study_upload(
    request: Request,
    file: UploadFile = File(...),
    dir_name: str = Form(""),
) -> RegisterStudyResponse:
    """Register a study by uploading its study.yaml.

    The uploaded file becomes `studies/<dir>/study.yaml`; the individual
    tasks are still read from that directory's `tasks/` folder on disk, so
    the loader reports a precise error if a referenced task file is missing.
    `dir_name` defaults to the `id:` declared inside the uploaded YAML.
    File handling lives in studio.config.upload; this endpoint adds only the
    HTTP shell and the DB-side duplicate check.
    """
    me = await _require_admin(request)

    try:
        text, slug = parse_uploaded_study_yaml(await file.read())
    except StudyUploadError as exc:
        raise HTTPException(exc.status, str(exc))

    if await Study.find_one(Study.slug == slug) is not None:
        raise HTTPException(
            409,
            f"A study with slug '{slug}' is already registered. "
            f"Edit it via its YAML page, or unregister it first.",
        )

    try:
        target_name = stage_study_yaml(text, slug, get_settings().studies_dir, dir_name)
    except StudyUploadError as exc:
        raise HTTPException(exc.status, str(exc))


    return await _register_study_from_dir(me, target_name)


def _sync_study_from_config(study: Study, config, digest: str) -> None:
    """Copy every YAML-derived field from a freshly-loaded StudyConfig onto a
    registered Study document. Single source of truth for the field list —
    used by reload, YAML save, and the study library."""
    study.name = config.name
    study.version = config.version
    study.mode = config.mode
    study.participants_required = config.participants_required
    study.consent_text_md = config.consent_text_md
    study.consent_text_md_by_lang = dict(config.consent_text_md_by_lang or {})
    study.va_systems = {k: v.model_dump() for k, v in config.va_systems.items()}
    study.primary_va_system = config.primary_va_system
    study.roles = [r.model_dump() for r in config.roles]
    study.advance_policy = config.advance_policy
    study.block_order = config.block_order
    study.block_orders = list(config.block_orders or [])
    study.parameters = dict(config.parameters or {})
    study.completion_redirect_url = config.completion_redirect_url
    study.completion_code = config.completion_code
    study.recording = config.recording.model_dump()
    study.ui = config.ui.model_dump()
    study.blocks = [block.model_dump() for block in config.blocks]
    study.metrics = [m.engine_dict() for m in config.metrics]
    study.replay = config.replay.model_dump()
    study.yaml_hash = digest


class YamlFileOut(BaseModel):
    path: str
    content: str


class StudyYamlResponse(BaseModel):
    study: Study
    files: list[YamlFileOut]


@router.get("/studies/{slug}/yaml", response_model=StudyYamlResponse)
async def study_yaml_view(request: Request, slug: str) -> StudyYamlResponse:
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    base = (get_settings().studies_dir / (study.study_dir or slug)).resolve()
    files: list[YamlFileOut] = []
    if base.is_dir():
        for p in sorted(base.rglob("*.yaml")):
            try:
                rel = str(p.relative_to(base)).replace("\\", "/")
                files.append(YamlFileOut(path=rel, content=p.read_text(encoding="utf-8")))
            except Exception:
                continue
    return StudyYamlResponse(study=study, files=files)


@router.post("/studies/{slug}/yaml", response_model=OkMessageResponse)
async def study_yaml_save(request: Request, slug: str, body: SaveYamlRequest) -> OkMessageResponse:
    """Save a single YAML file under the study directory, then reload.

    Limited to files that are already present in the directory — we won't
    accept arbitrary new paths through this endpoint.
    """
    me = await _require_admin(request)
    relative_path = body.relative_path
    content = body.content

    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    if _is_inuse_dir(study.study_dir):
        raise HTTPException(
            409,
            "This study runs from a frozen in-use copy and is read-only. "
            "Edit the study in the Library and register a new version instead.",
        )
    base = (get_settings().studies_dir / (study.study_dir or slug)).resolve()
    target = (base / relative_path).resolve()
    if not _is_inside(target, base) or not target.is_file() or target.suffix != ".yaml":
        raise HTTPException(400, "Unknown file")
    target.write_text(content, encoding="utf-8")
    await _audit(me, "study.edit_yaml", "study", str(study.id),
                 {"slug": slug, "file": relative_path, "bytes": len(content)})
    # Best-effort reload from disk; surfaces validation errors to the editor.
    try:
        config, _manifest, digest = load_study_dir(base)
        _sync_study_from_config(study, config, digest)
        await study.save()
        return OkMessageResponse(message="Saved and reloaded")
    except StudyLoadError as exc:
        return OkMessageResponse(warning=f"Saved but reload failed: {str(exc)[:200]}")


_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".ogg"}
_VIDEO_MAX_BYTES = 500 * 1024 * 1024  # 500MB — generous for a task-intro clip, small enough to not fill the disk


class UploadVideoResponse(BaseModel):
    url: str
    filename: str


async def _store_uploaded_video(dir_name: str, file: UploadFile) -> tuple[str, str, int]:
    """Stream ``file`` to ``<data_dir>/task_videos/<dir_name>/`` and return
    ``(url, dest_name, bytes_written)``. Shared by the registered-study and
    library upload endpoints — the namespace is keyed by directory/slug name
    only, independent of any DB record, so both call sites can write into it.

    Deliberately under ``data_dir`` (served at /media, see main.py), not the
    app's static/ dir: static/ ships inside the Docker image and is baked
    fresh on every deploy, while data_dir is the persistent PVC — a video
    saved under static/ would silently vanish on the next redeploy.

    Files are content-addressed by a random name (not the original filename)
    to avoid clobbering/traversal; the original name is only used to derive
    the extension.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported video type '{suffix}'. Use one of: {', '.join(sorted(_VIDEO_EXTENSIONS))}")

    dest_dir = get_settings().data_dir / "task_videos" / dir_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{secrets.token_hex(16)}{suffix}"
    dest_path = dest_dir / dest_name

    written = 0
    try:
        with dest_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > _VIDEO_MAX_BYTES:
                    raise HTTPException(413, f"Video exceeds the {_VIDEO_MAX_BYTES // (1024 * 1024)}MB limit")
                out.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return f"/media/{dir_name}/{dest_name}", dest_name, written


@router.post("/studies/{slug}/upload-video", response_model=UploadVideoResponse)
async def upload_study_video(request: Request, slug: str, file: UploadFile = File(...)) -> UploadVideoResponse:
    """Store a researcher-uploaded video under /static so a task's
    `video_url` (see InfoScreenTask) can reference it same-origin.

    Reload is NOT triggered here — the researcher still has to paste the
    returned url into a task's `video_url` and save that YAML.
    """
    me = await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")

    url, dest_name, written = await _store_uploaded_video(slug, file)
    await _audit(me, "study.upload_video", "study", str(study.id),
                 {"slug": slug, "filename": file.filename, "bytes": written, "url": url})
    return UploadVideoResponse(url=url, filename=file.filename or dest_name)


@router.post("/library/studies/{dir_name}/upload-video", response_model=UploadVideoResponse)
async def upload_library_video(request: Request, dir_name: str, file: UploadFile = File(...)) -> UploadVideoResponse:
    """Same as ``upload_study_video`` but for a library entry that may not
    (yet) be registered — keyed by directory name, validated the same way
    the other library routes validate ``dir_name``."""
    me = await _require_admin(request)
    _library_study_dir(dir_name)  # raises 400 if dir_name is not a safe slug

    url, dest_name, written = await _store_uploaded_video(dir_name, file)
    await _audit(me, "library.upload_video", "library", dir_name,
                 {"dir": dir_name, "filename": file.filename, "bytes": written, "url": url})
    return UploadVideoResponse(url=url, filename=file.filename or dest_name)


@router.post("/studies/{slug}/reload", response_model=OkMessageResponse)
async def reload_study(request: Request, slug: str) -> OkMessageResponse:
    me = await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    if not study.study_dir:
        raise HTTPException(400, f"Study '{slug}' has no source directory to reload from")

    studies_dir = get_settings().studies_dir
    target = (studies_dir / study.study_dir).resolve()
    if not _is_inside(target, studies_dir.resolve()) or not target.is_dir():
        raise HTTPException(400, f"Source directory '{study.study_dir}' is gone")

    try:
        config, _manifest, digest = load_study_dir(target)
    except StudyLoadError as exc:
        raise HTTPException(400, str(exc).replace("\n", " ")[:200])

    if config.id != study.slug:
        raise HTTPException(
            409,
            f"Reload would change slug from '{study.slug}' to '{config.id}'; "
            f"register as new study instead",
        )

    _sync_study_from_config(study, config, digest)
    await study.save()
    await _audit(me, "study.reload", "study", str(study.id),
                 {"slug": study.slug, "digest": digest[:16]})
    return OkMessageResponse(message=f"Reloaded '{slug}' from disk")


# ── behavioral metrics (declared in study.yaml `metrics:`) ───────────────────

@router.get("/studies/{slug}/metrics")
async def study_metrics(request: Request, slug: str) -> JSONResponse:
    """Per-participant values + aggregates for the study's declared metrics.

    Computed lazily from the persisted event stream — editing the study's
    `metrics:` block changes the numbers retroactively on the next call.
    """
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    from studio.metrics.service import compute_study_metrics
    return JSONResponse(await compute_study_metrics(study))


# ── API keys (auth for the public read-only /api/v1) ─────────────────────────

class ApiKeyRow(BaseModel):
    id: str
    name: str
    prefix: str
    created_by: str
    created_at: str
    last_used_at: str | None
    revoked: bool


class MintApiKeyRequest(BaseModel):
    name: str = ""


class MintApiKeyResponse(BaseModel):
    key: ApiKeyRow
    # The raw token — returned exactly ONCE, never retrievable again.
    token: str


def _api_key_row(k) -> ApiKeyRow:
    return ApiKeyRow(
        id=str(k.id), name=k.name, prefix=k.prefix, created_by=k.created_by,
        created_at=k.created_at.isoformat(),
        last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        revoked=k.revoked,
    )


@router.get("/apikeys")
async def apikeys_list(request: Request) -> JSONResponse:
    await _require_admin(request)
    from studio.models import ApiKey
    keys = await ApiKey.find().sort("-created_at").to_list()
    return JSONResponse({"keys": [_api_key_row(k).model_dump() for k in keys]})


@router.post("/apikeys", response_model=MintApiKeyResponse)
async def apikeys_mint(request: Request, body: MintApiKeyRequest) -> MintApiKeyResponse:
    me = await _require_admin(request)
    from studio.models import ApiKey
    from studio.models.api_key import hash_token, mint_token
    token = mint_token()
    key = ApiKey(
        name=(body.name or "unnamed").strip()[:80],
        token_hash=hash_token(token),
        prefix=token[:12],
        created_by=me,
    )
    await key.insert()
    await _audit(me, "apikey.mint", "apikey", str(key.id), {"name": key.name, "prefix": key.prefix})
    return MintApiKeyResponse(key=_api_key_row(key), token=token)


@router.delete("/apikeys/{key_id}", response_model=OkResponse)
async def apikeys_revoke(request: Request, key_id: str) -> OkResponse:
    me = await _require_admin(request)
    from studio.models import ApiKey
    try:
        kid = PydanticObjectId(key_id)
    except Exception:
        raise HTTPException(400, "Invalid key id")
    key = await ApiKey.get(kid)
    if key is None:
        raise HTTPException(404, "Key not found")
    key.revoked = True
    await key.save()
    await _audit(me, "apikey.revoke", "apikey", str(key.id), {"name": key.name, "prefix": key.prefix})
    return OkResponse()


# ── sensor ingest tokens (auth for POST /ingest/sensor-chunk) ────────────────

class SensorTokenRow(BaseModel):
    id: str
    label: str
    prefix: str
    created_by: str
    created_at: str
    last_used_at: str | None
    revoked: bool


class MintSensorTokenRequest(BaseModel):
    label: str = ""


class MintSensorTokenResponse(BaseModel):
    key: SensorTokenRow
    # The raw token — returned exactly ONCE, never retrievable again.
    token: str


def _sensor_token_row(t) -> SensorTokenRow:
    return SensorTokenRow(
        id=str(t.id), label=t.label, prefix=t.prefix, created_by=t.created_by,
        created_at=t.created_at.isoformat(),
        last_used_at=t.last_used_at.isoformat() if t.last_used_at else None,
        revoked=t.revoked,
    )


@router.get("/sessions/{session_id}/participants/{participant_id}/sensor-tokens")
async def sensor_tokens_list(request: Request, session_id: str, participant_id: str) -> JSONResponse:
    await _require_admin(request)
    try:
        sid, pid = PydanticObjectId(session_id), PydanticObjectId(participant_id)
    except Exception:
        raise HTTPException(400, "Invalid session or participant id")
    from studio.models import SensorIngestToken
    tokens = (
        await SensorIngestToken.find(
            SensorIngestToken.session_id == sid, SensorIngestToken.participant_id == pid
        )
        .sort("-created_at")
        .to_list()
    )
    return JSONResponse({"tokens": [_sensor_token_row(t).model_dump() for t in tokens]})


@router.post(
    "/sessions/{session_id}/participants/{participant_id}/sensor-tokens",
    response_model=MintSensorTokenResponse,
)
async def sensor_tokens_mint(
    request: Request, session_id: str, participant_id: str, body: MintSensorTokenRequest
) -> MintSensorTokenResponse:
    me = await _require_admin(request)
    try:
        sid, pid = PydanticObjectId(session_id), PydanticObjectId(participant_id)
    except Exception:
        raise HTTPException(400, "Invalid session or participant id")

    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    participant = await Participant.get(pid)
    if participant is None or participant.session_id != sid:
        raise HTTPException(404, "Participant not found in this session")
    study = await Study.get(session.study_id)
    if study is None:
        raise HTTPException(404, "Study not found")
    if not (study.recording or {}).get("external_sensor", False):
        raise HTTPException(
            400,
            "External sensor streaming is disabled for this study — "
            "set recording.external_sensor: true in the study YAML",
        )

    from studio.models import SensorIngestToken
    from studio.models.api_key import hash_token, mint_token
    token = mint_token(prefix="mvss_")
    sensor_token = SensorIngestToken(
        session_id=sid,
        participant_id=pid,
        label=(body.label or "unnamed").strip()[:80],
        token_hash=hash_token(token),
        prefix=token[:12],
        created_by=me,
    )
    await sensor_token.insert()
    await _audit(
        me, "sensortoken.mint", "sensor_ingest_token", str(sensor_token.id),
        {"label": sensor_token.label, "session_id": session_id, "participant_id": participant_id},
    )
    return MintSensorTokenResponse(key=_sensor_token_row(sensor_token), token=token)


@router.delete("/sensor-tokens/{token_id}", response_model=OkResponse)
async def sensor_tokens_revoke(request: Request, token_id: str) -> OkResponse:
    me = await _require_admin(request)
    from studio.models import SensorIngestToken
    try:
        tid = PydanticObjectId(token_id)
    except Exception:
        raise HTTPException(400, "Invalid token id")
    sensor_token = await SensorIngestToken.get(tid)
    if sensor_token is None:
        raise HTTPException(404, "Token not found")
    sensor_token.revoked = True
    await sensor_token.save()
    await _audit(me, "sensortoken.revoke", "sensor_ingest_token", str(sensor_token.id), {"label": sensor_token.label})
    return OkResponse()


# ── task library (shared tasks under studies/_lib/tasks) ─────────────────────
#
# One cross-study pool: any study can pull a library task via
#   - $ref: ../_lib/tasks/<file>.yaml
# Always editable: registration freezes a COPY of every referenced task into
# the study's _inuse snapshot, so editing here never changes a registered
# study. Deletion is still refused while a legacy live-dir registration
# references the file (its loader would break).

_TASK_FILE_RE = _re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*\.yaml$")


def _lib_tasks_dir() -> Path:
    d = (get_settings().studies_dir / "_lib" / "tasks").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lib_task_path(name: str) -> Path:
    """Resolve a library task filename, refusing anything path-like."""
    if not _TASK_FILE_RE.match(name):
        raise HTTPException(400, "Task filename must match <letters-digits-dashes>.yaml")
    return _lib_tasks_dir() / name


async def _lib_task_usage() -> dict[str, list[str]]:
    """Map ``<file>.yaml`` → sorted study slugs for every registered study
    whose resolved manifest consumed that shared task."""
    usage: dict[str, set[str]] = {}
    studies_dir = get_settings().studies_dir.resolve()
    for study in await Study.find().to_list():
        base = (studies_dir / (study.study_dir or study.slug)).resolve()
        if not _is_inside(base, studies_dir) or not base.is_dir():
            continue
        try:
            _cfg, manifest, _digest = load_study_dir(base)
        except StudyLoadError:
            continue  # broken on disk ≠ using the task right now
        for key in manifest:
            norm = key.replace("\\", "/")
            if "_lib/tasks/" in norm:
                usage.setdefault(norm.rsplit("/", 1)[-1], set()).add(study.slug)
    return {k: sorted(v) for k, v in usage.items()}


def _validate_task_yaml(content: str, name: str) -> dict:
    """Parse + schema-validate one task file; raise 400 with a precise error."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"Invalid YAML: {str(exc)[:200]}")
    if not isinstance(data, dict):
        raise HTTPException(400, "A task file must be a YAML mapping")
    if not data.get("id"):
        raise HTTPException(400, "Task must declare an `id` (studies reference it)")
    if not data.get("type"):
        raise HTTPException(400, "Task must declare a `type`")
    try:
        TypeAdapter(Task).validate_python(data)
    except Exception as exc:
        raise HTTPException(400, f"Task does not match the schema: {str(exc)[:300]}")
    return data


class LibraryTaskRow(BaseModel):
    file: str                 # "foo.yaml" (shared) or "tasks/foo.yaml" (study-local)
    dir: str | None = None    # None = shared _lib pool; else the study dir
    task_id: str | None
    type: str | None
    used_by: list[str]
    read_only: bool           # delete-lock only — editing is always allowed


class LibraryTasksResponse(BaseModel):
    tasks: list[LibraryTaskRow]
    ref_prefix: str = "../_lib/tasks/"


class LibraryTaskContentResponse(BaseModel):
    file: str
    content: str
    used_by: list[str]
    read_only: bool


class SaveLibraryTaskRequest(BaseModel):
    content: str = ""


@router.get("/library/tasks", response_model=LibraryTasksResponse)
async def library_tasks(request: Request) -> LibraryTasksResponse:
    await _require_admin(request)
    usage = await _lib_task_usage()
    rows: list[LibraryTaskRow] = []
    for p in sorted(_lib_tasks_dir().glob("*.yaml")):
        task_id = task_type = None
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                task_id = data.get("id")
                task_type = data.get("type")
        except Exception:
            pass
        used = usage.get(p.name, [])
        rows.append(LibraryTaskRow(
            file=p.name, dir=None, task_id=task_id, type=task_type,
            used_by=used, read_only=bool(used),
        ))
    studies_dir = get_settings().studies_dir.resolve()
    if studies_dir.is_dir():
        for d in sorted(studies_dir.iterdir()):
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            for p in sorted((d / "tasks").glob("*.yaml")):
                task_id = task_type = None
                try:
                    data = yaml.safe_load(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        task_id = data.get("id") or p.stem
                        task_type = data.get("type")
                except Exception:
                    pass
                rows.append(LibraryTaskRow(
                    file=f"tasks/{p.name}", dir=d.name, task_id=task_id,
                    type=task_type, used_by=[], read_only=False,
                ))
    return LibraryTasksResponse(tasks=rows)


@router.get("/library/tasks/{name}", response_model=LibraryTaskContentResponse)
async def library_task_view(request: Request, name: str) -> LibraryTaskContentResponse:
    await _require_admin(request)
    path = _lib_task_path(name)
    if not path.is_file():
        raise HTTPException(404, "Task not found")
    used = (await _lib_task_usage()).get(name, [])
    return LibraryTaskContentResponse(
        file=name, content=path.read_text(encoding="utf-8"),
        used_by=used, read_only=bool(used),
    )


@router.put("/library/tasks/{name}", response_model=OkMessageResponse)
async def library_task_save(request: Request, name: str, body: SaveLibraryTaskRequest) -> OkMessageResponse:
    """Create or update a library task. Always allowed — registered studies
    run from frozen in-use copies, so edits here never reach them."""
    me = await _require_admin(request)
    path = _lib_task_path(name)
    _validate_task_yaml(body.content, name)
    existed = path.is_file()
    path.write_text(body.content, encoding="utf-8")
    await _audit(me, "library.task_update" if existed else "library.task_create",
                 "library", name, {"bytes": len(body.content)})
    return OkMessageResponse(message=("Updated " if existed else "Created ") + name)


@router.delete("/library/tasks/{name}", response_model=OkResponse)
async def library_task_delete(request: Request, name: str) -> OkResponse:
    me = await _require_admin(request)
    path = _lib_task_path(name)
    if not path.is_file():
        raise HTTPException(404, "Task not found")
    used = (await _lib_task_usage()).get(name, [])
    if used:
        raise HTTPException(
            409,
            f"'{name}' is used by registered stud{'y' if len(used) == 1 else 'ies'} "
            f"{', '.join(used)} and cannot be deleted.",
        )
    path.unlink()
    await _audit(me, "library.task_delete", "library", name, {})
    return OkResponse()


# ── study library (every studies/<dir>/study.yaml) ─────────────────────────────

_STUDY_DIR_RE = _re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _library_study_dir(dir_name: str) -> Path:
    if not _STUDY_DIR_RE.match(dir_name):
        raise HTTPException(400, "Study directory must match <letters-digits-dashes>")
    return get_settings().studies_dir.resolve() / dir_name


def _inuse_root() -> Path:
    return get_settings().studies_dir.resolve() / _INUSE_DIR


def _inuse_copies_of(study_id: str | None) -> list[str]:
    """Frozen-copy slugs registered from a library study with this id
    (``<id>``, ``<id>-v2``, ...)."""
    if not study_id:
        return []
    root = _inuse_root()
    if not root.is_dir():
        return []
    pat = _re.compile(_re.escape(study_id) + r"(-v\d+)?$")
    return sorted(d.name for d in root.iterdir() if d.is_dir() and pat.match(d.name))


class LibraryStudyRow(BaseModel):
    dir: str
    study_id: str | None      # `id:` inside the YAML
    name: str | None
    mode: str | None
    in_use: list[str]         # frozen-copy slugs registered from this study


class LibraryStudiesResponse(BaseModel):
    studies: list[LibraryStudyRow]


class LibraryStudyContentResponse(BaseModel):
    dir: str
    path: str = "study.yaml"
    files: list[str] = []
    content: str
    in_use: list[str] = []


class SaveLibraryStudyRequest(BaseModel):
    content: str = ""
    # Relative YAML path inside the study dir; default study.yaml.
    path: str = "study.yaml"


@router.get("/library/studies", response_model=LibraryStudiesResponse)
async def library_studies(request: Request) -> LibraryStudiesResponse:
    await _require_admin(request)
    studies_dir = get_settings().studies_dir.resolve()
    rows: list[LibraryStudyRow] = []
    if studies_dir.is_dir():
        for d in sorted(studies_dir.iterdir()):
            yaml_path = d / "study.yaml"
            if not d.is_dir() or d.name.startswith((".", "_")) or not yaml_path.is_file():
                continue
            study_id = name = mode = None
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    study_id = data.get("id")
                    name = data.get("name")
                    mode = data.get("mode")
            except Exception:
                pass
            rows.append(LibraryStudyRow(
                dir=d.name, study_id=study_id, name=name, mode=mode,
                in_use=_inuse_copies_of(study_id),
            ))
    return LibraryStudiesResponse(studies=rows)


def _library_study_file(dir_name: str, relative_path: str) -> Path:
    """Resolve a YAML file path inside a study dir, refusing escapes."""
    base = _library_study_dir(dir_name)
    target = (base / relative_path).resolve()
    if not _is_inside(target, base) or target.suffix != ".yaml":
        raise HTTPException(400, "File must be a .yaml path inside the study directory")
    return target


def _study_dir_files(base: Path) -> list[str]:
    if not base.is_dir():
        return []
    return sorted(
        str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*.yaml")
    )


@router.get("/library/studies/{dir_name}", response_model=LibraryStudyContentResponse)
async def library_study_view(request: Request, dir_name: str, path: str = "study.yaml") -> LibraryStudyContentResponse:
    """One YAML file of a study dir (``?path=`` — default study.yaml), plus the
    dir's full file list so the editor can offer every file."""
    await _require_admin(request)
    base = _library_study_dir(dir_name)
    target = _library_study_file(dir_name, path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    study_id = None
    try:
        d = yaml.safe_load((base / "study.yaml").read_text(encoding="utf-8"))
        study_id = d.get("id") if isinstance(d, dict) else None
    except Exception:
        pass
    return LibraryStudyContentResponse(
        dir=dir_name, path=str(target.relative_to(base)).replace("\\", "/"),
        content=target.read_text(encoding="utf-8"),
        files=_study_dir_files(base),
        in_use=_inuse_copies_of(study_id),
    )


@router.put("/library/studies/{dir_name}", response_model=OkMessageResponse)
async def library_study_save(request: Request, dir_name: str, body: SaveLibraryStudyRequest) -> OkMessageResponse:
    """Create or update any YAML file of ``studies/<dir>`` (``body.path``,
    default study.yaml — so a new study's first save also creates the dir).

    The library is ALWAYS writable: registered studies run from their frozen
    in-use copies, so nothing here can affect a live session. A full-
    validation failure keeps the file but returns a warning.
    """
    me = await _require_admin(request)
    base = _library_study_dir(dir_name)
    relative_path = (body.path or "study.yaml").strip()
    target = _library_study_file(dir_name, relative_path)

    try:
        data = yaml.safe_load(body.content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"Invalid YAML: {str(exc)[:200]}")
    if relative_path == "study.yaml":
        if not isinstance(data, dict) or not data.get("id"):
            raise HTTPException(400, "A study.yaml must be a YAML mapping with an `id`")
    elif not isinstance(data, dict):
        raise HTTPException(400, "A task file must be a YAML mapping")

    existed = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    await _audit(me, "library.study_update" if existed else "library.study_create",
                 "library", f"{dir_name}/{relative_path}", {"bytes": len(body.content)})

    try:
        load_study_dir(base)
    except StudyLoadError as exc:
        return OkMessageResponse(
            warning=f"Saved, but the study does not validate yet: {str(exc)[:200]}")
    return OkMessageResponse(message=("Updated " if existed else "Created ") + f"{dir_name}/{relative_path}")


# ── in-use section (frozen registered copies — read-only) ──────────────────

class InUseRow(BaseModel):
    slug: str
    name: str | None
    mode: str | None
    registered: bool          # a Study document exists for this copy
    archived: bool


class InUseListResponse(BaseModel):
    studies: list[InUseRow]


@router.get("/library/inuse", response_model=InUseListResponse)
async def library_inuse(request: Request) -> InUseListResponse:
    await _require_admin(request)
    root = _inuse_root()
    by_slug = {s.slug: s for s in await Study.find().to_list()}
    rows: list[InUseRow] = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            yaml_path = d / "study.yaml"
            if not d.is_dir() or not yaml_path.is_file():
                continue
            name = mode = None
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    name = data.get("name")
                    mode = data.get("mode")
            except Exception:
                pass
            reg = by_slug.get(d.name)
            rows.append(InUseRow(
                slug=d.name, name=name, mode=mode,
                registered=reg is not None,
                archived=bool(reg.archived) if reg is not None else False,
            ))
    return InUseListResponse(studies=rows)


@router.get("/library/inuse/{slug}", response_model=LibraryStudyContentResponse)
async def library_inuse_view(request: Request, slug: str, path: str = "study.yaml") -> LibraryStudyContentResponse:
    """Read-only view of one file of a frozen in-use copy."""
    await _require_admin(request)
    if not _STUDY_DIR_RE.match(slug):
        raise HTTPException(400, "Invalid in-use slug")
    base = (_inuse_root() / slug).resolve()
    target = (base / path).resolve()
    if not _is_inside(target, base) or target.suffix != ".yaml":
        raise HTTPException(400, "File must be a .yaml path inside the copy")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return LibraryStudyContentResponse(
        dir=f"{_INUSE_DIR}/{slug}",
        path=str(target.relative_to(base)).replace("\\", "/"),
        content=target.read_text(encoding="utf-8"),
        files=_study_dir_files(base),
        in_use=[slug],
    )



class BrowseDirEntry(BaseModel):
    dir: str
    registered_slug: str | None
    has_study_yaml: bool
    files: list[str]


class LibraryBrowseResponse(BaseModel):
    studies: list[BrowseDirEntry]


@router.get("/library/browse", response_model=LibraryBrowseResponse)
async def library_browse(request: Request) -> LibraryBrowseResponse:
    """Read-only view of the studies directory: every study dir, its YAML
    files, and whether it is registered."""
    await _require_admin(request)
    studies_dir = get_settings().studies_dir.resolve()
    by_dir = {s.study_dir or s.slug: s.slug for s in await Study.find().to_list()}
    entries: list[BrowseDirEntry] = []
    if studies_dir.is_dir():
        for d in sorted(studies_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            files = sorted(
                str(p.relative_to(d)).replace("\\", "/")
                for p in d.rglob("*.yaml")
            )
            entries.append(BrowseDirEntry(
                dir=d.name,
                registered_slug=by_dir.get(d.name),
                has_study_yaml=(d / "study.yaml").is_file(),
                files=files,
            ))
    return LibraryBrowseResponse(studies=entries)


@router.get("/studies/{slug}", response_model=StudyDetailResponse)
async def study_detail(request: Request, slug: str) -> StudyDetailResponse:
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    codes = await Code.find(Code.study_id == study.id).sort("-created_at").to_list()
    sessions = await Session.find(Session.study_id == study.id).sort("-created_at").limit(50).to_list()
    stats = await study_stats(study)
    tasks = await per_task_summary(study)
    # Base for shareable participant join links (<base>/s/<CODE>). Prefer the
    # configured public URL; otherwise use the host the admin is on right now.
    share_base = (get_settings().public_base_url or str(request.base_url)).rstrip("/")
    return StudyDetailResponse(
        study=study, codes=codes, sessions=sessions, stats=stats, tasks=tasks,
        share_base=share_base,
    )


class NewCodeRequest(BaseModel):
    role: str = ""


class NewCodeResponse(BaseModel):
    ok: bool = True
    code: str


@router.post("/studies/{slug}/codes", response_model=NewCodeResponse)
async def new_code(request: Request, slug: str, body: NewCodeRequest) -> NewCodeResponse:
    await _require_admin(request)
    role_id = body.role.strip() or None
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    if role_id:
        known = {r.get("id") for r in (study.roles or [])}
        if role_id not in known:
            raise HTTPException(400, f"Unknown role '{role_id}'")
    code = await _generate_code(study.id, role=role_id)
    return NewCodeResponse(code=code.code)


class AdvanceResponse(BaseModel):
    advanced: bool
    current_task_index: int


@router.post("/sessions/{session_id}/advance", response_model=AdvanceResponse)
async def admin_advance_session(request: Request, session_id: str) -> AdvanceResponse:
    """Manual advance trigger for studies/tasks with advance.policy=admin."""
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    advanced = await session_manager.try_advance_session(session, force=True)
    return AdvanceResponse(advanced=advanced, current_task_index=session.current_task_index)


@router.patch("/studies/{slug}", response_model=OkResponse)
async def patch_study(request: Request, slug: str, body: PatchStudyRequest) -> OkResponse:
    me = await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    if body.archived is not None:
        study.archived = body.archived
        await study.save()
        action = "study.archive" if body.archived else "study.unarchive"
        await _audit(me, action, "study", str(study.id), {"slug": slug})
    return OkResponse()


# ── sessions ──────────────────────────────────────────────────────────────

class ReplaySessionResponse(BaseModel):
    session: Session
    study: Study | None
    payload: dict[str, Any]


@router.get("/replay/{session_id}", response_model=ReplaySessionResponse)
async def replay_session(request: Request, session_id: str) -> ReplaySessionResponse:
    """Scrubbable replay of a session's recording."""
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    if _backfill_marker_ids(session):
        await session.save()
    study = await Study.get(session.study_id)
    payload = await replay_payload(session)
    return ReplaySessionResponse(session=session, study=study, payload=payload)


class ShareLinkResponse(BaseModel):
    token: str
    url: str


@router.post("/sessions/{session_id}/share", response_model=ShareLinkResponse)
async def session_share_create(request: Request, session_id: str) -> ShareLinkResponse:
    """Mint (or return the existing) read-only replay share link for a session.

    Anyone with the link can view the replay timeline + recording — no admin
    login — so treat it like an unlisted URL. Idempotent: re-minting returns
    the same token; use DELETE to revoke and invalidate old links.
    """
    me = await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    if not session.share_token:
        import secrets
        session.share_token = secrets.token_urlsafe(24)
        await session.save()
        await _audit(me, "session.share", "session", str(session.id), {})
    return ShareLinkResponse(
        token=session.share_token,
        url=f"/admin/shared/{session.share_token}",
    )


@router.delete("/sessions/{session_id}/share", response_model=OkResponse)
async def session_share_revoke(request: Request, session_id: str) -> OkResponse:
    """Revoke a session's replay share link — old URLs stop working immediately."""
    me = await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    if session.share_token:
        session.share_token = None
        await session.save()
        await _audit(me, "session.unshare", "session", str(session.id), {})
    return OkResponse()


class ReplayStartResponse(BaseModel):
    iframe_url: str
    va_system_id: str
    replay_ws_url: str
    port: int | None


@router.post("/replay/{session_id}/start", response_model=ReplayStartResponse)
async def replay_session_start(
    request: Request,
    session_id: str,
    va_system_id: str | None = None,
) -> ReplayStartResponse:
    """Spawn a fresh replay VA for this session and return its iframe + WS URLs.

    Uses the original session's study to know how to spawn the VA. The
    replay VA is keyed in the spawner under session_id ``replay:<session_id>``
    so it is independent of any live session running for the same study.

    For studies with multiple `va_systems:`, pass `va_system_id` to pick which
    one to replay; defaults to the study's primary.
    """
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    original = await Session.get(sid)
    if original is None:
        raise HTTPException(404, "Session not found")
    study = await Study.get(original.study_id)
    if study is None or not study.va_systems:
        raise HTTPException(400, "Session has no VA configured")

    resolved_va_system = va_system_id or study.primary_va_system
    if not resolved_va_system or resolved_va_system not in study.va_systems:
        raise HTTPException(
            400,
            f"Unknown va_system_id '{resolved_va_system}'; "
            f"known: {sorted(study.va_systems)}",
        )

    from studio.orchestrator.va_spawner import va_spawner
    spawn_key = f"replay:{session_id}"
    running = va_spawner.get(spawn_key, resolved_va_system)
    if running is None:
        from studio.config.schemas import VAConfig
        va_cfg = VAConfig.model_validate(study.va_systems[resolved_va_system])
        # Use a separate recording dir per replay so the throwaway JSONL
        # the spawned VA produces does not collide with the original.
        rec_dir = Path(va_cfg.recording_dir_override) if va_cfg.recording_dir_override else \
                  get_settings().data_dir / "replay" / session_id / resolved_va_system
        running = await va_spawner.spawn(
            session_id=spawn_key,
            va_system_id=resolved_va_system,
            va=va_cfg,
            variant_name="default",
            recording_dir=rec_dir,
        )
    from studio.orchestrator.va_client import _ws_url_from_iframe
    return ReplayStartResponse(
        iframe_url=running.iframe_url,
        va_system_id=running.va_system_id,
        replay_ws_url=_ws_url_from_iframe(running.iframe_url, f"replay-{session_id}"),
        port=running.port,
    )


class ReplayStopResponse(BaseModel):
    stopped: bool = True


@router.post("/replay/{session_id}/stop", response_model=ReplayStopResponse)
async def replay_session_stop(request: Request, session_id: str) -> ReplayStopResponse:
    """Tear down every replay VA spawned for this session."""
    await _require_admin(request)
    from studio.orchestrator.va_spawner import va_spawner
    await va_spawner.stop_session(f"replay:{session_id}")
    return ReplayStopResponse()


class SessionDetailResponse(BaseModel):
    session: Session
    study: Study | None
    recording: dict[str, Any]
    density: list[dict[str, int]]
    payload: dict[str, Any]


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def session_detail(request: Request, session_id: str) -> SessionDetailResponse:
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    if _backfill_marker_ids(session):
        await session.save()
    study = await Study.get(session.study_id)
    recording = await session_recording(session)
    density = timeline_density(recording["events"])
    # Same data the replay viewer uses — drives the static, lane-based activity
    # timeline (per-user / per-agent rows) on this page.
    payload = await replay_payload(session)

    return SessionDetailResponse(
        session=session, study=study, recording=recording, density=density, payload=payload,
    )


@router.delete("/sessions/{session_id}", response_model=OkMessageResponse)
async def delete_session(request: Request, session_id: str) -> OkMessageResponse:
    """Delete a session and EVERYTHING it produced: participants, events,
    transcripts, audio/video/biometric chunks (documents AND media files on
    disk). Active sessions get their VAs stopped and tailers closed first.
    Irreversible — the UI must confirm before calling this."""
    import shutil

    me = await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")

    # A still-active session: shut its machinery down before removing data.
    if session.status in ("lobby", "spawning", "running"):
        from studio.orchestrator import ws_collector
        try:
            await session_manager.stop_session_vas(session)
        except Exception:
            pass  # best-effort — spawned processes may already be gone
        try:
            await ws_collector.stop_session(str(session.id))
        except Exception:
            pass

    # Cascade: every collection keyed by this session.
    from studio.models import AudioChunk, BiometricChunk, Transcript, VideoChunk
    n_participants = await Participant.find(Participant.session_id == sid).count()
    n_events = await Event.find(Event.session_id == sid).count()
    await Participant.find(Participant.session_id == sid).delete()
    await Event.find(Event.session_id == sid).delete()
    await Transcript.find(Transcript.session_id == sid).delete()
    await AudioChunk.find(AudioChunk.session_id == sid).delete()
    await VideoChunk.find(VideoChunk.session_id == sid).delete()
    await BiometricChunk.find(BiometricChunk.session_id == sid).delete()

    # Codes bound to this multiplayer lobby may form a fresh one afterwards.
    await Code.find(Code.multiplayer_session_id == sid).update(
        {"$set": {"multiplayer_session_id": None}})

    # Media files on disk: data/{audio,video}/<study_id>/<session_id>/...
    data_dir = get_settings().data_dir
    for kind in ("audio", "video"):
        shutil.rmtree(data_dir / kind / str(session.study_id) / str(sid), ignore_errors=True)

    await session.delete()
    await _audit(me, "session.delete", "session", str(sid),
                 {"study_id": str(session.study_id), "status": session.status,
                  "participants": n_participants, "events": n_events})
    return OkMessageResponse(
        message=f"Deleted session ({n_participants} participant(s), {n_events} event(s), media files removed)")


# ── admin user management ────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    username: str
    created_at: datetime
    last_login: datetime | None


class UsersListResponse(BaseModel):
    users: list[UserOut]
    me: str


class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(min_length=8)


class PatchUserRequest(BaseModel):
    password: str | None = Field(None, min_length=8)


@router.get("/users", response_model=UsersListResponse)
async def users_list(request: Request) -> UsersListResponse:
    me = await _require_admin(request)
    users = await AdminUser.find().sort("created_at").to_list()
    # Never serialize pw_hash to the client, admin-only surface or not.
    safe_users = [
        UserOut(id=str(u.id), username=u.username, created_at=u.created_at, last_login=u.last_login)
        for u in users
    ]
    return UsersListResponse(users=safe_users, me=me)


@router.post("/users", response_model=OkMessageResponse)
async def users_create(request: Request, body: CreateUserRequest) -> OkMessageResponse:
    actor = await _require_admin(request)
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Username and password required")
    if await AdminUser.find_one(AdminUser.username == username) is not None:
        raise HTTPException(409, f"Username '{username}' already exists")
    user = AdminUser(username=username, pw_hash=hash_password(body.password))
    await user.insert()
    await _audit(actor, "admin_user.create", "admin_user", str(user.id), {"username": username})
    return OkMessageResponse(message=f"Created user '{username}'")


@router.patch("/users/{user_id}", response_model=OkMessageResponse)
async def users_patch(request: Request, user_id: str, body: PatchUserRequest) -> OkMessageResponse:
    actor = await _require_admin(request)
    try:
        user = await AdminUser.get(PydanticObjectId(user_id))
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if user is None:
        raise HTTPException(404, "User not found")
    if body.password is None:
        raise HTTPException(400, "Nothing to update")
    user.pw_hash = hash_password(body.password)
    await user.save()
    await _audit(actor, "admin_user.set_password", "admin_user", str(user.id), {"username": user.username})
    return OkMessageResponse(message=f"Password updated for '{user.username}'")


@router.delete("/users/{user_id}", response_model=OkMessageResponse)
async def users_delete(request: Request, user_id: str) -> OkMessageResponse:
    actor = await _require_admin(request)
    try:
        user = await AdminUser.get(PydanticObjectId(user_id))
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if user is None:
        raise HTTPException(404, "User not found")
    if user.username == actor:
        raise HTTPException(409, "Cannot delete yourself")
    if await AdminUser.find().count() <= 1:
        raise HTTPException(409, "Cannot delete the last admin")
    username = user.username
    await user.delete()
    await _audit(actor, "admin_user.delete", "admin_user", user_id, {"username": username})
    return OkMessageResponse(message=f"Deleted '{username}'")


# ── audit log surface ────────────────────────────────────────────────────

class AuditIndexResponse(BaseModel):
    entries: list[AuditEntry]


@router.get("/audit", response_model=AuditIndexResponse)
async def audit_index(request: Request) -> AuditIndexResponse:
    await _require_admin(request)
    entries = await AuditEntry.find().sort("-ts").limit(500).to_list()
    return AuditIndexResponse(entries=entries)


# ── analytics: per-task + cross-study ────────────────────────────────────

class StudyPreviewResponse(BaseModel):
    study: Study
    task_id: str
    rendered: dict[str, Any]
    role_id: str | None
    all_tasks: list[tuple[str, str]]
    all_roles: list[dict[str, Any]]


@router.get("/studies/{slug}/preview", response_model=StudyPreviewResponse)
async def study_preview(
    request: Request,
    slug: str,
    role: str = Query(""),
    task: str = Query(""),
) -> StudyPreviewResponse:
    """Render one task as a chosen role without joining the study.

    No participant cookie is touched, no events are logged, no VA is spawned.
    Used by researchers to verify per-role content + `{{ params.X }}`
    substitution before fielding the study.
    """
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")

    from studio.config.schemas import StudyConfig
    from studio.orchestrator import flow

    cfg = StudyConfig.model_validate({
        "id": study.slug, "name": study.name, "version": study.version,
        "mode": study.mode, "participants_required": study.participants_required,
        "consent_text_md": study.consent_text_md,
        "va_systems": study.va_systems or {},
        "primary_va_system": study.primary_va_system,
        "roles": study.roles or [], "advance_policy": study.advance_policy or "all",
        "block_order": getattr(study, "block_order", None) or "declared",
        "block_orders": getattr(study, "block_orders", None) or [],
        "parameters": getattr(study, "parameters", None) or {},
        "completion_redirect_url": getattr(study, "completion_redirect_url", None),
        "completion_code": getattr(study, "completion_code", None),
        "recording": study.recording or {}, "ui": study.ui or {},
        "blocks": study.blocks or [],
    })
    # Default: first task, first declared role.
    task_id = task or (cfg.blocks[0].tasks[0].id if cfg.blocks and cfg.blocks[0].tasks else "")
    role_id = role or (cfg.effective_roles()[0].id if cfg.effective_roles() else None)

    task_by_id: dict[str, dict] = {}
    block_id_by_task: dict[str, str] = {}
    for block in cfg.blocks:
        for t in block.tasks:
            task_by_id[t.id] = t.model_dump()
            block_id_by_task[t.id] = block.id

    if task_id and task_id not in task_by_id:
        raise HTTPException(400, f"Unknown task id '{task_id}'")

    rendered = task_by_id.get(task_id, {}) if task_id else {}
    if rendered:
        rendered = flow.apply_role_overrides(rendered, role_id)
        rendered = flow.substitute_params(rendered, cfg.parameters or {})

    return StudyPreviewResponse(
        study=study,
        task_id=task_id,
        rendered=rendered,
        role_id=role_id,
        all_tasks=[(t["id"], block_id_by_task[t["id"]]) for t in task_by_id.values()],
        all_roles=[r.model_dump() for r in cfg.effective_roles()],
    )


class StudyTaskDrilldownResponse(BaseModel):
    study: Study
    payload: dict[str, Any]
    task_id: str


@router.get("/studies/{slug}/task/{task_id}", response_model=StudyTaskDrilldownResponse)
async def study_task_drilldown(request: Request, slug: str, task_id: str) -> StudyTaskDrilldownResponse:
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    payload = await per_task_drilldown(study, task_id)
    return StudyTaskDrilldownResponse(study=study, payload=payload, task_id=task_id)


class ParticipantDetailResponse(BaseModel):
    payload: dict[str, Any]


@router.get("/participants/{participant_id}", response_model=ParticipantDetailResponse)
async def participant_detail(request: Request, participant_id: str) -> ParticipantDetailResponse:
    await _require_admin(request)
    try:
        pid = PydanticObjectId(participant_id)
    except Exception:
        raise HTTPException(400, "Invalid participant id")
    participant = await Participant.get(pid)
    if participant is None:
        raise HTTPException(404, "Participant not found")
    payload = await participant_journey(participant)
    return ParticipantDetailResponse(payload=payload)


class StudyFunnelResponse(BaseModel):
    study: Study
    stages: list[dict[str, Any]]


@router.get("/studies/{slug}/funnel", response_model=StudyFunnelResponse)
async def study_funnel_view(request: Request, slug: str) -> StudyFunnelResponse:
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    stages = await study_funnel(study)
    return StudyFunnelResponse(study=study, stages=stages)


class CompareIndexResponse(BaseModel):
    all_studies: list[Study]
    payload: dict[str, Any] | None
    selected_slugs: list[str]
    task_id: str
    shared_task_ids: list[str]


@router.get("/compare", response_model=CompareIndexResponse)
async def compare_index(
    request: Request,
    studies: str = Query(""),
    task_id: str = Query(""),
) -> CompareIndexResponse:
    await _require_admin(request)
    slugs = [s.strip() for s in studies.split(",") if s.strip()]
    all_studies = await Study.find().sort("-created_at").to_list()
    payload = None
    if slugs:
        payload = await compare_studies(slugs, task_id=task_id or None)
    # Suggested shared task ids: tasks that appear in every selected study.
    shared_task_ids: list[str] = []
    if slugs and payload and payload["studies"]:
        task_sets = []
        for s in payload["studies"]:
            ids = {t.get("id") for b in (s.blocks or []) for t in b.get("tasks", [])}
            task_sets.append(ids)
        if task_sets:
            shared_task_ids = sorted(set.intersection(*task_sets))
    return CompareIndexResponse(
        all_studies=all_studies,
        payload=payload,
        selected_slugs=slugs,
        task_id=task_id,
        shared_task_ids=shared_task_ids,
    )


# ── sessions catalog ─────────────────────────────────────────────────────

class SessionRow(BaseModel):
    session: Session
    study: Study | None
    n_participants: int
    n_finished: int


class SessionsIndexResponse(BaseModel):
    rows: list[SessionRow]
    all_studies: list[Study]
    study_filter: str
    status_filter: str
    tag_filter: str
    saved_views: list[SavedView]
    all_tags: list[str]
    current_query: str


@router.get("/sessions", response_model=SessionsIndexResponse)
async def sessions_index(
    request: Request,
    study: str = Query(""),
    status_f: str = Query("", alias="status"),
    tag: str = Query(""),
) -> SessionsIndexResponse:
    me = await _require_admin(request)
    q: dict = {}
    if study:
        s = await Study.find_one(Study.slug == study)
        if s is not None:
            q["study_id"] = s.id
    if status_f:
        q["status"] = status_f
    if tag:
        q["tags"] = tag.strip().lower()
    sessions = await Session.find(q).sort("-created_at").limit(200).to_list() if q \
        else await Session.find().sort("-created_at").limit(200).to_list()
    # join study name + participant counts for the list view
    studies = {s.id: s for s in await Study.find().to_list()}
    rows: list[SessionRow] = []
    for sess in sessions:
        n_part = await Participant.find(Participant.session_id == sess.id).count()
        n_finished = await Participant.find(Participant.session_id == sess.id, Participant.status == "finished").count()
        rows.append(SessionRow(
            session=sess, study=studies.get(sess.study_id),
            n_participants=n_part, n_finished=n_finished,
        ))
    all_studies = sorted(studies.values(), key=lambda s: s.created_at, reverse=True)

    # Saved views: load this admin's presets for the sessions surface.
    saved_views = await SavedView.find(
        SavedView.owner_username == me,
        SavedView.surface == "sessions",
    ).sort("-created_at").to_list()

    # Distinct tags seen across all sessions for filter autocomplete.
    all_tags: set[str] = set()
    for s_ in sessions:
        for t in (s_.tags or []):
            all_tags.add(t)

    return SessionsIndexResponse(
        rows=rows, all_studies=all_studies,
        study_filter=study, status_filter=status_f, tag_filter=tag,
        saved_views=saved_views, all_tags=sorted(all_tags),
        current_query=str(request.url.query),
    )


# ── saved views ─────────────────────────────────────────────────────────

class SaveViewRequest(BaseModel):
    name: str = ""
    query: str = ""
    surface: str = "sessions"


class SaveViewResponse(BaseModel):
    ok: bool = True
    view: SavedView


@router.post("/views/save", response_model=SaveViewResponse)
async def save_view(request: Request, body: SaveViewRequest) -> SaveViewResponse:
    me = await _require_admin(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name required")
    view = SavedView(owner_username=me, name=name, query=body.query, surface=body.surface)
    await view.insert()
    await _audit(me, "view.save", "saved_view", str(view.id), {"name": view.name, "query": body.query})
    return SaveViewResponse(view=view)


@router.delete("/views/{view_id}", response_model=OkResponse)
async def delete_view(request: Request, view_id: str) -> OkResponse:
    me = await _require_admin(request)
    try:
        view = await SavedView.get(PydanticObjectId(view_id))
    except Exception:
        raise HTTPException(400, "Invalid view id")
    if view is None or view.owner_username != me:
        raise HTTPException(404, "View not found")
    await view.delete()
    await _audit(me, "view.delete", "saved_view", view_id, {"name": view.name})
    return OkResponse()


# ── live session view ────────────────────────────────────────────────────

class SpectatorUrl(BaseModel):
    va_system_id: str
    url: str


class LiveSessionResponse(BaseModel):
    session: Session
    study: Study | None
    spectator_urls: list[SpectatorUrl]


@router.get("/sessions/{session_id}/live", response_model=LiveSessionResponse)
async def live_session(request: Request, session_id: str) -> LiveSessionResponse:
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    study = await Study.get(session.study_id)
    spectator_urls: list[SpectatorUrl] = []
    for va_system_id, info in (session.vas or {}).items():
        base = info.iframe_url or ""
        if not base:
            continue
        sep = "&" if "?" in base else "?"
        spectator_urls.append(SpectatorUrl(va_system_id=va_system_id, url=f"{base}{sep}role=studio_spectator"))
    return LiveSessionResponse(session=session, study=study, spectator_urls=spectator_urls)


class LiveSessionSummary(BaseModel):
    id: str
    status: str
    mode: str
    current_task_index: int


class LiveParticipant(BaseModel):
    id: str
    anon_id: str
    role: str | None
    status: str
    task_index: int
    current_task_id: str | None
    checked_steps: list[str]
    vu: float


class LiveEvent(BaseModel):
    t_ms: int
    source: str
    type: str
    task_id: str | None
    va_system_id: str | None
    meta: dict[str, Any]


class LiveTranscriptPreview(BaseModel):
    t_ms_start: int
    text: str
    language: str | None
    participant_anon: str | None
    role: str | None


class LiveSessionPollResponse(BaseModel):
    session: LiveSessionSummary
    participants: list[LiveParticipant]
    events: list[LiveEvent]
    audio_chunks: int
    transcripts: int
    recent_transcripts: list[LiveTranscriptPreview]


@router.get("/sessions/{session_id}/live/poll", response_model=LiveSessionPollResponse)
async def live_session_poll(request: Request, session_id: str) -> LiveSessionPollResponse:
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    participants = await Participant.find(Participant.session_id == sid).to_list()
    p_by_id = {p.id: p for p in participants}
    # Last 60 events for the running stream.
    events = await Event.find(Event.session_id == sid).sort("-t_ms").limit(60).to_list()
    events.reverse()
    n_chunks = await AudioChunk.find(AudioChunk.session_id == sid).count()
    n_transcripts = await Transcript.find(Transcript.session_id == sid).count()
    # Rolling transcript preview — last 12 segments by t_ms_start, oldest first.
    latest = await Transcript.find(Transcript.session_id == sid).sort("-t_ms_start").limit(12).to_list()
    latest.reverse()
    transcripts_payload = []
    for t in latest:
        p = p_by_id.get(t.participant_id)
        transcripts_payload.append({
            "t_ms_start": t.t_ms_start,
            "text": t.text,
            "language": t.language,
            "participant_anon": p.anon_id if p else None,
            "role": p.role if p else None,
        })
    vu: dict[str, float] = {}
    recent_chunks = await AudioChunk.find(
        AudioChunk.session_id == sid,
    ).sort("-t_ms_start").limit(40).to_list()
    seen_pids: set = set()
    for c in recent_chunks:
        if c.participant_id in seen_pids:
            continue
        if c.envelope:
            vu[str(c.participant_id)] = sum(c.envelope) / len(c.envelope)
            seen_pids.add(c.participant_id)

    return LiveSessionPollResponse(
        session=LiveSessionSummary(
            id=str(session.id), status=session.status, mode=session.mode,
            current_task_index=session.current_task_index,
        ),
        participants=[
            LiveParticipant(
                id=str(p.id), anon_id=p.anon_id, role=p.role, status=p.status,
                task_index=(p.task_runs[-1].task_index if p.task_runs else 0),
                current_task_id=(p.task_runs[-1].task_id if p.task_runs else None),
                checked_steps=(p.task_runs[-1].checked_steps if p.task_runs else []),
                vu=round(vu.get(str(p.id), 0.0), 3),
            )
            for p in participants
        ],
        events=[
            LiveEvent(
                t_ms=e.t_ms, source=e.source, type=e.type,
                task_id=e.task_id, va_system_id=e.va_system_id,
                meta={k: v for k, v in (e.meta or {}).items()
                      if k not in ("world_state", "audit_log")},
            )
            for e in events
        ],
        audio_chunks=n_chunks,
        transcripts=n_transcripts,
        recent_transcripts=[LiveTranscriptPreview(**t) for t in transcripts_payload],
    )


# ── cohort link (multiplayer) ────────────────────────────────────────────

class MintCohortRequest(BaseModel):
    roles: str = ""


class MintCohortResponse(BaseModel):
    ok: bool = True
    codes: list[str]


@router.post("/studies/{slug}/cohort", response_model=MintCohortResponse)
async def mint_cohort(request: Request, slug: str, body: MintCohortRequest) -> MintCohortResponse:
    me = await _require_admin(request)
    # Comma-separated role ids; empty = mint participants_required unbound codes.
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")

    role_ids = [r.strip() for r in body.roles.split(",") if r.strip()]
    known = {r.get("id") for r in (study.roles or [])}
    for r in role_ids:
        if r not in known:
            raise HTTPException(400, f"Unknown role '{r}'")
    n = len(role_ids) if role_ids else (study.participants_required or 1)
    cohort_session = await session_manager.create_multiplayer_session(study)
    minted: list[str] = []
    for i in range(n):
        role = role_ids[i] if role_ids else None
        c = await _generate_code(study.id, role=role)
        c.multiplayer_session_id = cohort_session.id
        await c.save()
        minted.append(c.code)
    await _audit(me, "code.mint_cohort", "study", str(study.id),
                 {"slug": slug, "roles": role_ids or [None] * n, "codes": minted,
                  "session_id": str(cohort_session.id)})
    return MintCohortResponse(codes=minted)


# ── code management ─────────────────────────────────────────────────────

class PatchCodeRequest(BaseModel):
    """True partial-PATCH semantics: a field is only changed if the caller
    actually sent it (checked via `model_fields_set`, not just "is not
    None") — sending `expires_in_hours: null` clears the expiry, while
    omitting it entirely leaves the current expiry untouched.
    """

    active: bool | None = None
    max_uses: int | None = None
    expires_in_hours: int | None = None


class CodeOut(BaseModel):
    id: str
    active: bool
    max_uses: int | None
    expires_at: datetime | None


@router.patch("/codes/{code_id}", response_model=CodeOut)
async def patch_code(request: Request, code_id: str, body: PatchCodeRequest) -> CodeOut:
    me = await _require_admin(request)
    try:
        code = await Code.get(PydanticObjectId(code_id))
    except Exception:
        raise HTTPException(400, "Invalid code id")
    if code is None:
        raise HTTPException(404, "Code not found")

    fields = body.model_fields_set
    if "active" in fields and body.active is not None:
        code.active = body.active
        await _audit(me, "code.toggle", "code", str(code.id),
                     {"code": code.code, "active": code.active})
    if "max_uses" in fields:
        code.max_uses = body.max_uses
    if "expires_in_hours" in fields:
        code.expires_at = (
            _utcnow_naive() + timedelta(hours=body.expires_in_hours)
            if body.expires_in_hours is not None else None
        )
    if "max_uses" in fields or "expires_in_hours" in fields:
        await _audit(me, "code.set_limit", "code", str(code.id),
                     {"code": code.code, "max_uses": code.max_uses,
                      "expires_at": code.expires_at.isoformat() if code.expires_at else None})

    await code.save()
    return CodeOut(id=str(code.id), active=code.active, max_uses=code.max_uses, expires_at=code.expires_at)


# ── exports ─────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/export.jsonl")
async def export_session_jsonl(request: Request, session_id: str) -> StreamingResponse:
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")

    participants = await Participant.find(Participant.session_id == sid).to_list()
    events = await Event.find(Event.session_id == sid).sort("+t_ms").to_list()
    transcripts = await Transcript.find(Transcript.session_id == sid).sort("+t_ms_start").to_list()

    async def stream():
        def line(obj):
            return json.dumps(obj, default=str) + "\n"
        yield line({"kind": "session", "data": session.model_dump(mode="json")})
        for p in participants:
            yield line({"kind": "participant", "data": p.model_dump(mode="json")})
        for e in events:
            yield line({"kind": "event", "data": e.model_dump(mode="json")})
        for t in transcripts:
            yield line({"kind": "transcript", "data": t.model_dump(mode="json")})

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="session_{session_id}.jsonl"'},
    )


@router.get("/sessions/{session_id}/export.csv")
async def export_session_csv(request: Request, session_id: str) -> StreamingResponse:
    """Per-task answer + score + duration for every participant in this session."""
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    participants = await Participant.find(Participant.session_id == sid).to_list()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "participant_anon", "external_id", "role",
        "task_index", "task_id", "started_at", "ended_at", "duration_ms",
        "answer", "score", "correct", "timed_out", "skipped", "checked_steps",
    ])
    for p in participants:
        for r in p.task_runs:
            w.writerow([
                p.anon_id, p.external_id or "", p.role or "",
                r.task_index, r.task_id,
                r.started_at.isoformat() if r.started_at else "",
                r.ended_at.isoformat() if r.ended_at else "",
                r.duration_ms or "",
                json.dumps(r.answer, default=str) if r.answer is not None else "",
                r.score if r.score is not None else "",
                "" if r.correct is None else ("true" if r.correct else "false"),
                "true" if r.timed_out else "false",
                "true" if r.skipped else "false",
                "|".join(r.checked_steps or []),
            ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="session_{session_id}.csv"'},
    )


@router.get("/studies/{slug}/export.parquet")
async def export_study_parquet(request: Request, slug: str) -> StreamingResponse:
    """Every task_run for every participant in every session, as a Parquet file.

    Researchers can read this directly with pandas/polars/duckdb for thesis
    figures without scraping the CSV. Columns mirror the CSV export.
    """
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    try:
        import pyarrow as pa  # lazy
        import pyarrow.parquet as pq
    except Exception:
        raise HTTPException(500, "pyarrow not installed; `pip install pyarrow` to enable Parquet export")

    participants = await Participant.find(Participant.study_id == study.id).to_list()
    cols: dict[str, list] = {
        "session_id": [], "participant_anon": [], "external_id": [], "role": [],
        "task_index": [], "task_id": [],
        "duration_ms": [], "answer_json": [], "score": [],
        "correct": [], "timed_out": [], "skipped": [],
        "started_at": [], "ended_at": [], "checked_steps": [],
    }
    for p in participants:
        for r in p.task_runs:
            cols["session_id"].append(str(p.session_id))
            cols["participant_anon"].append(p.anon_id)
            # Recruitment-platform id (e.g. Prolific PID) for data ↔ payment reconciliation.
            cols["external_id"].append(p.external_id or "")
            cols["role"].append(p.role or "")
            cols["task_index"].append(int(r.task_index))
            cols["task_id"].append(r.task_id)
            cols["duration_ms"].append(int(r.duration_ms) if r.duration_ms else None)
            cols["answer_json"].append(json.dumps(r.answer, default=str) if r.answer is not None else None)
            cols["score"].append(float(r.score) if r.score is not None else None)
            cols["correct"].append(bool(r.correct) if r.correct is not None else None)
            cols["timed_out"].append(bool(r.timed_out))
            cols["skipped"].append(bool(r.skipped))
            cols["started_at"].append(r.started_at)
            cols["ended_at"].append(r.ended_at)
            cols["checked_steps"].append(list(r.checked_steps or []))

    table = pa.table(cols)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    await _audit(optional_admin(request), "study.export_parquet", "study", str(study.id),
                 {"slug": slug, "rows": len(cols["session_id"])})
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="study_{slug}.parquet"'},
    )


@router.get("/studies/{slug}/preregistration.json")
async def export_prereg(request: Request, slug: str) -> StreamingResponse:
    """Pre-registration bundle: a frozen, hashed JSON snapshot of the study.

    Researchers commit this file to OSF / Zenodo *before* running participants;
    the ``manifest_digest`` is recomputed by the loader on every register/reload,
    so any later edit to a study or task file changes the digest and the diff
    is auditable. The ``signature`` is an HMAC over the JSON body keyed on the
    JWT secret — useful as a quick tamper check on a local archive.
    """
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")

    bundle = {
        "kind": "mivais-studio.preregistration",
        "version": 1,
        "exported_at": _utcnow_naive().isoformat(),
        "exporter": optional_admin(request),
        "study": {
            "slug": study.slug,
            "name": study.name,
            "version": study.version,
            "mode": study.mode,
            "participants_required": study.participants_required,
            "consent_text_md": study.consent_text_md,
            "va_systems": dict(study.va_systems or {}),
            "primary_va_system": study.primary_va_system,
            "roles": list(study.roles or []),
            "advance_policy": study.advance_policy,
            "block_order": getattr(study, "block_order", "declared"),
            "block_orders": list(getattr(study, "block_orders", None) or []),
            "parameters": dict(getattr(study, "parameters", None) or {}),
            "completion_redirect_url": getattr(study, "completion_redirect_url", None),
            "completion_code": getattr(study, "completion_code", None),
            "recording": dict(study.recording or {}),
            "ui": dict(study.ui or {}),
            "blocks": list(study.blocks or []),
            "manifest_digest": study.yaml_hash,
        },
    }
    body = json.dumps(bundle, indent=2, sort_keys=True, default=str).encode("utf-8")
    # Sign with the JWT secret; receivers verify by recomputing the HMAC.
    import hmac, hashlib
    secret = get_settings().jwt_secret.encode("utf-8")
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
    full = json.dumps(
        {**bundle, "signature": f"sha256={sig}"}, indent=2, sort_keys=True, default=str,
    )
    await _audit(optional_admin(request), "study.export_preregistration", "study", str(study.id),
                 {"slug": slug, "digest": study.yaml_hash[:16]})
    return StreamingResponse(
        iter([full]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{slug}-prereg.json"'},
    )


@router.get("/studies/{slug}/export.csv")
async def export_study_csv(request: Request, slug: str) -> StreamingResponse:
    """Every task_run for every participant in every session of this study."""
    await _require_admin(request)
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    participants = await Participant.find(Participant.study_id == study.id).to_list()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "session_id", "participant_anon", "external_id", "role",
        "task_index", "task_id",
        "duration_ms", "answer", "score", "correct", "timed_out", "skipped",
    ])
    for p in participants:
        for r in p.task_runs:
            w.writerow([
                str(p.session_id), p.anon_id, p.external_id or "", p.role or "",
                r.task_index, r.task_id,
                r.duration_ms or "",
                json.dumps(r.answer, default=str) if r.answer is not None else "",
                r.score if r.score is not None else "",
                "" if r.correct is None else ("true" if r.correct else "false"),
                "true" if r.timed_out else "false",
                "true" if r.skipped else "false",
            ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="study_{slug}.csv"'},
    )


# ── full-text search ────────────────────────────────────────────────────

class SearchResponse(BaseModel):
    q: str
    results: dict[str, list[dict[str, Any]]]
    total: int


@router.get("/search", response_model=SearchResponse)
async def search_view(request: Request, q: str = Query("")) -> SearchResponse:
    """Cross-collection text search: studies, sessions (tags + notes), transcripts.

    Uses Mongo's $regex with case-insensitive match — adequate for the volumes
    Studio handles. Heavy deployments should add per-collection text indexes.
    """
    await _require_admin(request)
    q_str = q.strip()
    results: dict[str, list[dict]] = {"studies": [], "sessions": [], "transcripts": []}
    if q_str:
        import re as _re
        pattern = _re.compile(_re.escape(q_str), _re.IGNORECASE)
        pat_str = pattern.pattern

        studies = await Study.find({
            "$or": [
                {"slug": {"$regex": pat_str, "$options": "i"}},
                {"name": {"$regex": pat_str, "$options": "i"}},
                {"consent_text_md": {"$regex": pat_str, "$options": "i"}},
            ]
        }).limit(50).to_list()
        for s in studies:
            results["studies"].append({"id": str(s.id), "slug": s.slug,
                                        "name": s.name, "mode": s.mode})

        sessions = await Session.find({
            "$or": [
                {"tags": {"$regex": pat_str, "$options": "i"}},
                {"notes.text": {"$regex": pat_str, "$options": "i"}},
                {"failure_reason": {"$regex": pat_str, "$options": "i"}},
            ]
        }).limit(50).to_list()
        study_by_id = {s.id: s for s in await Study.find().to_list()}
        for sess in sessions:
            study = study_by_id.get(sess.study_id)
            snippet = None
            for n in (sess.notes or []):
                if pattern.search(n.get("text") or ""):
                    txt = n["text"]
                    snippet = txt[:160] + ("…" if len(txt) > 160 else "")
                    break
            results["sessions"].append({
                "id": str(sess.id),
                "status": sess.status,
                "study_name": study.name if study else "—",
                "study_slug": study.slug if study else "",
                "tags": list(sess.tags or []),
                "snippet": snippet,
                "created_at": sess.created_at.strftime("%Y-%m-%d %H:%M") if sess.created_at else "—",
            })

        tx = await Transcript.find({
            "text": {"$regex": pat_str, "$options": "i"},
        }).sort("-created_at").limit(50).to_list()
        for t in tx:
            txt = t.text or ""
            m = pattern.search(txt)
            start = max(0, (m.start() if m else 0) - 40)
            snippet = ("…" if start > 0 else "") + txt[start:start + 200]
            results["transcripts"].append({
                "session_id": str(t.session_id),
                "participant_id": str(t.participant_id),
                "t_ms_start": t.t_ms_start,
                "language": t.language,
                "snippet": snippet,
            })
    return SearchResponse(q=q_str, results=results, total=sum(len(v) for v in results.values()))


# ── session tags ────────────────────────────────────────────────────────

class SetTagsRequest(BaseModel):
    tags: str = ""


class SetTagsResponse(BaseModel):
    ok: bool = True
    tags: list[str]


@router.post("/sessions/{session_id}/tags", response_model=SetTagsResponse)
async def set_session_tags(request: Request, session_id: str, body: SetTagsRequest) -> SetTagsResponse:
    me = await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    new_tags = sorted({t.strip().lower() for t in body.tags.split(",") if t.strip()})
    by_author = dict(session.tags_by_author or {})
    by_author[me] = new_tags
    session.tags = sorted({t for ts in by_author.values() for t in ts})
    session.tags_by_author = by_author
    await session.save()
    await _audit(me, "session.set_tags", "session", str(session.id), {"tags": new_tags, "as": me})
    return SetTagsResponse(tags=session.tags)


# ── inter-rater reliability ─────────────────────────────────────────────

class IrrResponse(BaseModel):
    all_studies: list[Study]
    selected_study: str
    raters: list[str]
    all_tags: list[str]
    selected_a: str
    selected_b: str
    selected_tag: str
    result: dict[str, Any] | None


@router.get("/irr", response_model=IrrResponse)
async def irr_view(
    request: Request,
    study: str = Query(""),
    tag: str = Query(""),
    a: str = Query(""),
    b: str = Query(""),
) -> IrrResponse:
    await _require_admin(request)
    q: dict = {}
    if study:
        s = await Study.find_one(Study.slug == study)
        if s is not None:
            q["study_id"] = s.id
    sessions = await Session.find(q).to_list() if q else await Session.find().to_list()
    raters: set[str] = set()
    all_tags: set[str] = set()
    for s in sessions:
        tba = s.tags_by_author or {}
        raters.update(tba.keys())
        for ts in tba.values():
            all_tags.update(ts)
    result = None
    if a and b and tag and a != b:
        from studio.stats import cohens_kappa
        paired_a, paired_b = [], []
        for s in sessions:
            tba = s.tags_by_author or {}
            if a in tba and b in tba:
                paired_a.append(tag in tba[a])
                paired_b.append(tag in tba[b])
        result = cohens_kappa(paired_a, paired_b)
        result.update({"paired_n": len(paired_a), "tag": tag, "a": a, "b": b})

    all_studies = await Study.find().sort("-created_at").to_list()
    return IrrResponse(
        all_studies=all_studies,
        selected_study=study,
        raters=sorted(raters),
        all_tags=sorted(all_tags),
        selected_a=a, selected_b=b, selected_tag=tag,
        result=result,
    )


# ── session annotations ─────────────────────────────────────────────────

class AddMarkerRequest(BaseModel):
    t_ms: int
    kind: str = "note"
    label: str = ""
    quote: str = ""


class MarkerOut(BaseModel):
    marker_id: str
    author: str
    t_ms: int
    kind: str
    label: str
    quote: str = ""
    wall_clock: str


class AddMarkerResponse(BaseModel):
    ok: bool = True
    marker: MarkerOut


class AddNoteRequest(BaseModel):
    text: str
    t_ms: int | None = None


class NoteOut(BaseModel):
    author: str
    t_ms: int
    wall_clock: str
    text: str


class AddNoteResponse(BaseModel):
    ok: bool = True
    note: NoteOut
    notes: list[NoteOut]


class ListNotesResponse(BaseModel):
    notes: list[NoteOut]


def _backfill_marker_ids(session: Session) -> bool:
    """Markers created before this migration have no `marker_id` (the
    delete route used to match on a `(t_ms, author)` composite key from the
    request body instead). Assign real ids lazily on read rather than
    running a one-off migration script -- self-healing, no ops step.
    """
    changed = False
    for m in session.markers or []:
        if not m.get("marker_id"):
            m["marker_id"] = secrets.token_urlsafe(8)
            changed = True
    return changed


@router.post("/sessions/{session_id}/marker", response_model=AddMarkerResponse)
async def add_session_marker(request: Request, session_id: str, body: AddMarkerRequest) -> AddMarkerResponse:
    """Drop a marker on the replay timeline at ``t_ms``. Returns the new marker.

    Called by the replay viewer so the admin doesn't lose their place. The
    marker is also logged as an audit entry so we know who placed it.
    """
    me = await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    marker = {
        "marker_id": secrets.token_urlsafe(8),
        "author": me,
        "t_ms": max(0, body.t_ms),
        "kind": (body.kind or "note").strip().lower()[:32],
        "label": (body.label or "").strip()[:200],
        "quote": (body.quote or "").strip()[:500],
        "wall_clock": _utcnow_naive().isoformat(),
    }
    session.markers = list(session.markers or []) + [marker]
    await session.save()
    await _audit(me, "session.marker", "session", str(session.id),
                 {"t_ms": marker["t_ms"], "kind": marker["kind"]})
    return AddMarkerResponse(marker=MarkerOut(**marker))


@router.delete("/sessions/{session_id}/marker/{marker_id}", response_model=OkResponse)
async def delete_session_marker(request: Request, session_id: str, marker_id: str) -> OkResponse:
    me = await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    _backfill_marker_ids(session)
    before = len(session.markers or [])
    session.markers = [m for m in (session.markers or []) if m.get("marker_id") != marker_id]
    if len(session.markers) == before:
        raise HTTPException(404, "Marker not found")
    await session.save()
    await _audit(me, "session.marker_delete", "session", str(session.id), {"marker_id": marker_id})
    return OkResponse()


@router.post("/sessions/{session_id}/note", response_model=AddNoteResponse)
async def add_session_note(request: Request, session_id: str, body: AddNoteRequest) -> AddNoteResponse:
    """Append a shared admin note. Used by both the session-detail page and
    the replay viewer's chat panel."""
    me = await _require_admin(request)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Note text required")
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    note = {
        "author": me or "admin",
        "t_ms": body.t_ms if body.t_ms is not None else session.t_ms_now(),
        "wall_clock": _utcnow_naive().isoformat(),
        "text": text,
    }
    session.notes.append(note)
    await session.save()
    await _audit(me, "session.note", "session", str(session.id), {"text": text[:140]})
    return AddNoteResponse(note=NoteOut(**note), notes=[NoteOut(**n) for n in session.notes or []])


@router.get("/sessions/{session_id}/notes", response_model=ListNotesResponse)
async def list_session_notes(request: Request, session_id: str) -> ListNotesResponse:
    """Notes for the replay chat panel (polled so admins see each other live)."""
    await _require_admin(request)
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(400, "Invalid session id")
    session = await Session.get(sid)
    if session is None:
        raise HTTPException(404, "Session not found")
    return ListNotesResponse(notes=[NoteOut(**n) for n in session.notes or []])


# ── webhooks ────────────────────────────────────────────────────────────

class WebhookOut(BaseModel):
    """Webhook payload minus `secret` — never leaves the server (matches the
    original template, which never rendered it either). An explicit
    allowlist rather than `response_model=WebhookEndpoint` on purpose: a
    future field added to the Beanie document won't silently leak through
    here the way it would with a direct model reference.
    """

    id: str
    study_id: str
    url: str
    events: list[str]
    kind: str
    active: bool
    description: str
    created_at: datetime
    last_delivery_at: datetime | None
    last_delivery_status: int | None
    delivery_count: int
    failure_count: int


def _safe_hook(h: Any) -> WebhookOut:
    return WebhookOut(
        id=str(h.id), study_id=str(h.study_id), url=h.url,
        events=h.events, kind=h.kind, active=h.active,
        description=h.description, created_at=h.created_at,
        last_delivery_at=h.last_delivery_at, last_delivery_status=h.last_delivery_status,
        delivery_count=h.delivery_count, failure_count=h.failure_count,
    )


class StudyRef(BaseModel):
    id: str
    slug: str
    name: str


class WebhookRow(BaseModel):
    hook: WebhookOut
    study: StudyRef | None


class WebhooksIndexResponse(BaseModel):
    rows: list[WebhookRow]
    all_studies: list[StudyRef]


class CreateWebhookRequest(BaseModel):
    study_slug: str
    url: str
    events: list[str] = ["session_completed"]
    kind: str = "studio"
    description: str = ""


class CreateWebhookResponse(BaseModel):
    ok: bool = True
    hook: WebhookOut


class PatchWebhookRequest(BaseModel):
    active: bool


@router.get("/webhooks", response_model=WebhooksIndexResponse)
async def webhooks_index(request: Request) -> WebhooksIndexResponse:
    await _require_admin(request)
    from studio.models import WebhookEndpoint
    hooks = await WebhookEndpoint.find().sort("-created_at").to_list()
    studies = {s.id: s for s in await Study.find().to_list()}
    rows = [
        WebhookRow(
            hook=_safe_hook(h),
            study=StudyRef(id=str(s.id), slug=s.slug, name=s.name) if (s := studies.get(h.study_id)) else None,
        )
        for h in hooks
    ]
    all_studies = [
        StudyRef(id=str(s.id), slug=s.slug, name=s.name)
        for s in sorted(studies.values(), key=lambda s: s.created_at, reverse=True)
    ]
    return WebhooksIndexResponse(rows=rows, all_studies=all_studies)


@router.post("/webhooks", response_model=CreateWebhookResponse)
async def webhooks_create(request: Request, body: CreateWebhookRequest) -> CreateWebhookResponse:
    me = await _require_admin(request)
    url = body.url.strip()
    description = body.description.strip()

    study = await Study.find_one(Study.slug == body.study_slug)
    if study is None:
        raise HTTPException(404, "Study not found")
    from studio.models import WebhookEndpoint
    from studio.models.webhook import WEBHOOK_EVENTS
    evs = [e.strip() for e in body.events if e.strip()]
    bad = [e for e in evs if e not in WEBHOOK_EVENTS]
    if bad:
        raise HTTPException(400, f"Unknown event(s): {','.join(bad)}")
    hook = WebhookEndpoint(
        study_id=study.id,
        url=url,
        secret=secrets.token_urlsafe(32),
        events=evs or ["session_completed"],
        kind=(body.kind if body.kind in ("studio", "discord") else "studio"),
        description=description,
    )
    await hook.insert()
    await _audit(me, "webhook.create", "webhook", str(hook.id),
                 {"study": body.study_slug, "url": hook.url, "events": hook.events})
    return CreateWebhookResponse(hook=_safe_hook(hook))


@router.patch("/webhooks/{hook_id}", response_model=WebhookOut)
async def webhooks_patch(request: Request, hook_id: str, body: PatchWebhookRequest) -> WebhookOut:
    me = await _require_admin(request)
    from studio.models import WebhookEndpoint
    try:
        hook = await WebhookEndpoint.get(PydanticObjectId(hook_id))
    except Exception:
        raise HTTPException(400, "Invalid id")
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    hook.active = body.active
    await hook.save()
    await _audit(me, "webhook.toggle", "webhook", str(hook.id), {"active": hook.active})
    return _safe_hook(hook)


@router.delete("/webhooks/{hook_id}", response_model=OkResponse)
async def webhooks_delete(request: Request, hook_id: str) -> OkResponse:
    me = await _require_admin(request)
    from studio.models import WebhookEndpoint
    try:
        hook = await WebhookEndpoint.get(PydanticObjectId(hook_id))
    except Exception:
        raise HTTPException(400, "Invalid id")
    if hook is None:
        raise HTTPException(404, "Webhook not found")
    await hook.delete()
    await _audit(me, "webhook.delete", "webhook", hook_id, {"url": hook.url})
    return OkResponse()


async def _generate_code(study_id: PydanticObjectId, role: str | None = None) -> Code:
    """Generate a unique 6-character code (uppercase letters + digits, no ambiguous chars)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
    for _ in range(20):
        candidate = "".join(secrets.choice(alphabet) for _ in range(6))
        if await Code.find_one(Code.code == candidate) is None:
            code = Code(code=candidate, study_id=study_id, role=role)
            await code.insert()
            return code
    raise RuntimeError("could not allocate a unique code after 20 attempts")


# ── audit log helper ─────────────────────────────────────────────────────

async def _audit(
    actor: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    meta: dict | None = None,
) -> None:
    """Best-effort write to the audit_log collection. Never raises."""
    from studio.models import AuditEntry
    try:
        await AuditEntry(
            actor_username=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=meta or {},
        ).insert()
    except Exception:
        # Auditing is observation-only; never break the request because of it.
        pass


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


async def _list_available_studies() -> list[dict]:
    """Scan settings.studies_dir and pair each on-disk study with its DB state.

    Returns a list of dicts with keys: dir_name, slug, name, version, mode,
    digest, status, registered_id, error. Status is one of:
      - "not_registered" — directory loads cleanly but no Study with that slug
      - "in_sync"        — Study exists and yaml_hash matches the directory
      - "out_of_sync"    — Study exists but the directory's hash differs
      - "error"          — directory failed to load (see `error` for the message)
    """
    settings = get_settings()
    base = settings.studies_dir
    if not base.exists():
        return []

    items: list[dict] = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if not (entry / "study.yaml").is_file():
            continue
        try:
            config, _manifest, digest = load_study_dir(entry)
        except StudyLoadError as exc:
            items.append({
                "dir_name": entry.name,
                "slug": None, "name": None, "version": None, "mode": None,
                "digest": None,
                "status": "error",
                "registered_id": None,
                "error": str(exc),
            })
            continue

        existing = await Study.find_one(Study.slug == config.id)
        if existing is None:
            status_str, registered_id = "not_registered", None
        elif existing.yaml_hash == digest:
            status_str, registered_id = "in_sync", str(existing.id)
        else:
            status_str, registered_id = "out_of_sync", str(existing.id)

        items.append({
            "dir_name": entry.name,
            "slug": config.id,
            "name": config.name,
            "version": config.version,
            "mode": config.mode,
            "digest": digest,
            "status": status_str,
            "registered_id": registered_id,
            "error": None,
        })
    return items
