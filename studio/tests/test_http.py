"""End-to-end HTTP checks on the FastAPI app. Uses ``httpx.AsyncClient`` so we
never touch a real network socket. Mongo-backed routes are gated on the
``mongo`` marker; auth-required routes return 303 redirects without it.
"""
from __future__ import annotations

import pytest


@pytest.fixture
async def client():
    """An httpx.AsyncClient bound to the live FastAPI app via ASGITransport.

    Skips the lifespan event so we don't have to bring Mongo up for every
    HTTP-level test. Mongo-dependent routes are still gated on the ``mongo``
    marker via conftest, so the schema-only routes work regardless.
    """
    from httpx import ASGITransport, AsyncClient
    from studio.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.mongo
class TestHealth:
    """Smoke checks that need a real Mongo + a real Beanie init."""

    async def test_health_returns_mongo_ok(self, client):
        # Open the same DB connection the FastAPI lifespan would.
        from studio import db
        await db.connect()
        try:
            r = await client.get("/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] in ("ok", "degraded")
            assert "mongo" in data
            assert "whisper_worker_enabled" in data
        finally:
            await db.disconnect()

    async def test_metrics_emits_prometheus_format(self, client):
        from studio import db
        await db.connect()
        try:
            r = await client.get("/metrics")
            assert r.status_code == 200
            body = r.text
            assert "# HELP" in body
            assert "# TYPE" in body
            # The endpoint emits both `studio_sessions_total` and per-status
            # `studio_sessions{...}` lines. Check the former.
            assert "studio_sessions_total" in body
        finally:
            await db.disconnect()


class TestAuthGate:
    async def test_admin_routes_401_when_unauthed(self, client):
        # /api/admin/* requires auth; unauthenticated requests get a JSON 401
        # (the SPA's own router owns the /admin/login page path).
        r = await client.get("/api/admin/")
        assert r.status_code == 401
        assert "application/json" in (r.headers.get("content-type") or "")

    async def test_admin_me_reports_logged_out(self, client):
        r = await client.get("/api/admin/me")
        assert r.status_code == 200
        assert r.json() == {"username": None}

    @pytest.mark.mongo
    async def test_preflight_serves_json_for_unknown_code(self, client):
        # Participant routes moved to /api/p/* (JSON) — the frontend SPA now
        # owns "/" and every other page path; the FastAPI shell-serving
        # catch-all for those paths lands in a later phase.
        from studio import db
        await db.connect()
        try:
            r = await client.get("/api/p/preflight/NOSUCHCODE")
            assert r.status_code == 200
            assert "application/json" in (r.headers.get("content-type") or "")
            data = r.json()
            assert data["valid_code"] is False
        finally:
            await db.disconnect()


class TestErrorHandling:
    async def test_unknown_top_level_path_serves_spa_shell(self, client):
        # Any path outside /api, /ingest, /static, /assets, /metrics, /health
        # falls through to the SPA shell catch-all — the React app's own
        # router renders its own "not found" view client-side. If the
        # frontend hasn't been built yet (no studio/frontend/dist), this is a
        # 404 instead; both are valid depending on whether `pnpm build` ran.
        r = await client.get("/no-such-page")
        assert r.status_code in (200, 404)

    async def test_404_on_unknown_api_route(self, client):
        r = await client.get("/api/no-such-endpoint")
        assert r.status_code == 404

    async def test_404_on_non_get_to_unknown_api_route(self, client):
        # Regression: the SPA shell catch-all is registered for every HTTP
        # method (see main.py). Starlette resolves 404-vs-405 purely by path
        # at the routing layer before any handler runs, so a GET-only
        # catch-all would make a POST/DELETE/etc. to an unmatched /api/*
        # path (e.g. a since-removed endpoint) match the shell's PATH and
        # get a misleading 405 "Method Not Allowed: GET" instead of 404.
        r = await client.post("/api/no-such-endpoint")
        assert r.status_code == 404
        r2 = await client.delete("/api/admin/no-such-endpoint")
        assert r2.status_code == 404

    async def test_audio_ingest_without_cookie_rejects(self, client):
        # No participant cookie + no multipart body → 401 or 422.
        r = await client.post("/ingest/audio-chunk")
        assert r.status_code in (401, 422)

    async def test_video_ingest_without_cookie_rejects(self, client):
        # No participant cookie + no multipart body → 401 or 422.
        r = await client.post("/ingest/video-chunk")
        assert r.status_code in (401, 422)

    async def test_biometric_ingest_without_cookie_rejects(self, client):
        # No participant cookie + no JSON body → 401 or 422.
        r = await client.post("/ingest/biometric-chunk")
        assert r.status_code in (401, 422)

    async def test_sensor_ingest_without_token_rejects(self, client):
        # No Authorization header + no JSON body → 401 or 422.
        r = await client.post("/ingest/sensor-chunk")
        assert r.status_code in (401, 422)

    async def test_video_serve_requires_admin(self, client):
        # The session recording is admin-only (never exposed on /static).
        r = await client.get("/admin/sessions/000000000000000000000000/video")
        assert r.status_code in (401, 303)
