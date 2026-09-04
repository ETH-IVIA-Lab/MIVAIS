"""MIVAIS Studio — FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from studio import db
from studio.api import admin, audio, biometric, i18n, participant, public, sensor, setup, shared, video
from studio.audio.transcribe import whisper_worker
from studio.orchestrator import ws_collector
from studio.orchestrator.va_spawner import va_spawner
from studio.settings import get_settings

log = logging.getLogger("studio")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.studies_dir.mkdir(parents=True, exist_ok=True)
    if settings.studies_seed_dir is not None:
        from studio.config.sync_studies import sync_studies_from_seed
        sync_studies_from_seed(settings.studies_seed_dir, settings.studies_dir)
    await db.connect()
    log.info("connected to mongo at %s/%s", settings.mongo_url, settings.mongo_db)
    from studio.auth import ensure_bootstrap_admin
    await ensure_bootstrap_admin()
    await whisper_worker.start()

    
    try:
        from studio.orchestrator.session_manager import session_manager
        result = await session_manager.recover_interrupted_sessions()
        if result["recovered"] or result["interrupted"]:
            log.info(
                "session recovery: %d resumed, %d interrupted, %d lobby kept",
                result["recovered"], result["interrupted"], result["lobby_kept"],
            )
    except Exception:
        log.exception("session recovery failed")


    try:
        from studio.models import AudioChunk
        pending = await AudioChunk.find(
            AudioChunk.transcribed == False,    # noqa: E712
            AudioChunk.transcribe_error == None, # noqa: E711
        ).limit(500).to_list()
        if pending:
            for c in pending:
                whisper_worker.enqueue(c.id)
            log.info("whisper re-enqueue: %d chunk(s) restored", len(pending))
    except Exception:
        log.exception("whisper re-enqueue failed")
    yield
    await whisper_worker.stop()
    await ws_collector.stop_all()
    await va_spawner.stop_all()
    await db.disconnect()
    log.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MIVAIS Studio",
        version="0.1.0",
        lifespan=lifespan,
    )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    media_dir = get_settings().data_dir / "task_videos"
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    app.include_router(participant.router)   # /api/join, /api/p/*
    app.include_router(setup.router)         # /api/setup — public build-your-own-VA tutorial
    app.include_router(admin.router)         # /api/admin/*
    app.include_router(i18n.router)          # /api/i18n/<lang>.json
    app.include_router(audio.router)         # /ingest/audio-chunk
    app.include_router(video.router)         # /ingest/video-chunk, /admin/sessions/*/video
    app.include_router(biometric.router)     # /ingest/biometric-chunk
    app.include_router(sensor.router)        # /ingest/sensor-chunk — external sensor sources
    app.include_router(public.router)        # /api/v1/* — read-only API for external tools
    app.include_router(shared.router)        # /api/shared/* — token-gated read-only replay

    @app.get("/metrics", response_model=None, include_in_schema=False)
    async def metrics():
        """Prometheus-format counters + gauges.

        Scrape this endpoint from your Prometheus / Grafana stack. The output
        is plain text (``text/plain; version=0.0.4``) following the exposition
        format — no client library dependency. Counters are computed live from
        Mongo on every scrape; cheap enough for the volumes Studio sees.
        """
        from fastapi import Response
        from studio.models import (
            Study, Session, Participant, Event, AudioChunk, Transcript, AuditEntry,
        )
        try:
            n_studies     = await Study.find().count()
            n_sessions    = await Session.find().count()
            n_running     = await Session.find(Session.status == "running").count()
            n_lobby       = await Session.find(Session.status == "lobby").count()
            n_interrupted = await Session.find(Session.status == "interrupted").count()
            n_completed   = await Session.find(Session.status == "completed").count()
            n_participants = await Participant.find().count()
            n_finished    = await Participant.find(Participant.status == "finished").count()
            n_dropped     = await Participant.find(Participant.status == "dropped").count()
            n_events      = await Event.find().count()
            n_audio       = await AudioChunk.find().count()
            n_audio_pending = await AudioChunk.find(
                AudioChunk.transcribed == False,    # noqa: E712
                AudioChunk.transcribe_error == None, # noqa: E711
            ).count()
            n_transcripts = await Transcript.find().count()
            n_audit       = await AuditEntry.find().count()
        except Exception:
            return Response("# studio metrics: mongo unreachable\n",
                            media_type="text/plain; version=0.0.4")

        lines = [
            "# HELP studio_studies_total Number of registered studies.",
            "# TYPE studio_studies_total gauge",
            f"studio_studies_total {n_studies}",
            "# HELP studio_sessions_total Total sessions ever created.",
            "# TYPE studio_sessions_total counter",
            f"studio_sessions_total {n_sessions}",
            "# HELP studio_sessions Number of sessions in each status.",
            "# TYPE studio_sessions gauge",
            f'studio_sessions{{status="running"}} {n_running}',
            f'studio_sessions{{status="lobby"}} {n_lobby}',
            f'studio_sessions{{status="completed"}} {n_completed}',
            f'studio_sessions{{status="interrupted"}} {n_interrupted}',
            "# HELP studio_participants_total Total participants ever joined.",
            "# TYPE studio_participants_total counter",
            f"studio_participants_total {n_participants}",
            "# HELP studio_participants Number of participants in terminal statuses.",
            "# TYPE studio_participants gauge",
            f'studio_participants{{status="finished"}} {n_finished}',
            f'studio_participants{{status="dropped"}} {n_dropped}',
            "# HELP studio_events_total Total events recorded across all sessions.",
            "# TYPE studio_events_total counter",
            f"studio_events_total {n_events}",
            "# HELP studio_audio_chunks_total Audio chunks received.",
            "# TYPE studio_audio_chunks_total counter",
            f"studio_audio_chunks_total {n_audio}",
            "# HELP studio_audio_pending Audio chunks waiting for the Whisper worker.",
            "# TYPE studio_audio_pending gauge",
            f"studio_audio_pending {n_audio_pending}",
            "# HELP studio_transcripts_total Transcripts produced by the Whisper worker.",
            "# TYPE studio_transcripts_total counter",
            f"studio_transcripts_total {n_transcripts}",
            "# HELP studio_audit_total Admin actions recorded in the audit log.",
            "# TYPE studio_audit_total counter",
            f"studio_audit_total {n_audit}",
        ]
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @app.get("/health")
    async def health() -> dict:
        """Lightweight liveness + readiness probe."""
        import time
        try:
            # Ping Mongo cheaply via the Beanie session.
            from studio.models import Study
            await Study.find().limit(1).to_list()
            mongo_ok = True
        except Exception:
            mongo_ok = False
        return {
            "status": "ok" if mongo_ok else "degraded",
            "mongo": mongo_ok,
            "whisper_worker_enabled": get_settings().whisper_worker_enabled,
            "ts": int(time.time() * 1000),
        }

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        # Every route in the app is JSON now (the React SPA owns rendering).
        if 400 <= exc.status_code < 600:
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        raise exc

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "validation", "detail": exc.errors()}, status_code=422)

    
    _RESERVED_PREFIXES = ("api/", "ingest/", "static/", "assets/")
    _RESERVED_EXACT = ("metrics", "health")
    _SHELL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

    @app.api_route("/{full_path:path}", methods=_SHELL_METHODS, include_in_schema=False)
    async def serve_shell(request: Request, full_path: str):
        if full_path in _RESERVED_EXACT or full_path.startswith(_RESERVED_PREFIXES):
            raise HTTPException(404, "Not found")
        if request.method != "GET":
            raise HTTPException(404, "Not found")
        if not (frontend_dist / "index.html").is_file():
            raise HTTPException(404, "Frontend not built — run `pnpm --filter studio-frontend build`")
        if full_path == "admin" or full_path.startswith("admin/"):
            return FileResponse(str(frontend_dist / "admin.html"))
        return FileResponse(str(frontend_dist / "index.html"))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("studio.main:app", host="0.0.0.0", port=8000, reload=True)
