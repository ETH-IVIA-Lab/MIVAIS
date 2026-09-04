"""REST-conventions migration: admin.py route-level tests.

Covers verb/status-code behavior for routes touched in the migration's
phases, starting with Phase 1 (auth + studies lifecycle). Uses the same
``client``/``studio_db`` patterns as ``test_http.py``/``test_integration.py``.
"""
from __future__ import annotations

import contextlib

import pytest

pytestmark = pytest.mark.mongo


@contextlib.asynccontextmanager
async def studio_db():
    from studio import db
    await db.connect()
    try:
        yield
    finally:
        await db.disconnect()


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient
    from studio.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _studies_dir_override(studies_root):
    """`get_settings().studies_dir` defaults to a CWD-relative `./studies`,
    resolved once and cached (`lru_cache`) at first call — whatever the test
    runner's working directory happened to be. Routes like `register_study`/
    `reload_study` read it directly, so point it at the real fixture
    directory (`studies_root`, already resolved correctly by conftest.py)
    for the duration of each test rather than relying on process CWD.
    """
    from studio.settings import get_settings
    settings = get_settings()
    original = settings.studies_dir
    settings.studies_dir = studies_root
    yield
    settings.studies_dir = original


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """`_login_failures` is a module-level, in-process global (single-worker
    by design, see admin.py) — every test client hits it under the same
    apparent IP, so it must be reset per test or an earlier throttle test
    poisons every later one in the same session.
    """
    from studio.api import admin
    admin._login_failures.clear()
    yield
    admin._login_failures.clear()


async def _make_admin(username: str = "tester", password: str = "s3cret-pass") -> None:
    from studio.auth import hash_password
    from studio.models import AdminUser
    existing = await AdminUser.find_one(AdminUser.username == username)
    if existing is not None:
        return
    await AdminUser(username=username, pw_hash=hash_password(password)).insert()


async def _login(client, username: str = "tester", password: str = "s3cret-pass"):
    return await client.post("/api/admin/login", json={"username": username, "password": password})


async def _register_smoke_study(studies_root, slug_suffix: str = "") -> str:
    """Register podium-smoke (optionally under a throwaway slug) via the real
    register endpoint's underlying logic isn't reused here — we go through
    Study directly, matching test_integration.py's `_ensure_smoke_registered`
    pattern, since register_study's own behavior is what several tests below
    exercise directly via HTTP instead.
    """
    from studio.config.loader import load_study_dir
    from studio.models import Study
    cfg, _manifest, digest = load_study_dir(studies_root / "podium-smoke")
    slug = cfg.id + slug_suffix
    s = await Study.find_one(Study.slug == slug)
    if s is None:
        s = Study(slug=slug, name=cfg.name, study_dir="podium-smoke")
    s.name = cfg.name
    s.mode = cfg.mode
    s.va_systems = {k: v.model_dump() for k, v in cfg.va_systems.items()}
    s.primary_va_system = cfg.primary_va_system
    s.roles = [r.model_dump() for r in cfg.roles]
    s.blocks = [block.model_dump() for block in cfg.blocks]
    s.yaml_hash = digest
    await s.save()
    return slug


class TestLogin:
    async def test_bad_password_returns_401_with_error_body(self, client):
        async with studio_db():
            await _make_admin()
            r = await _login(client, password="wrong")
            assert r.status_code == 401
            assert r.json() == {"error": "Invalid credentials"}

    async def test_good_password_sets_cookie_and_returns_typed_body(self, client):
        async with studio_db():
            await _make_admin()
            r = await _login(client)
            assert r.status_code == 200
            assert r.json() == {"ok": True, "username": "tester"}
            assert "studio_admin" in r.cookies or any(
                "studio_admin" in h for h in r.headers.get_list("set-cookie")
            )

    async def test_throttled_after_max_attempts_returns_429(self, client):
        from studio.settings import get_settings
        async with studio_db():
            await _make_admin()
            max_attempts = get_settings().login_max_attempts
            last = None
            for _ in range(max_attempts + 1):
                last = await _login(client, password="wrong")
            assert last.status_code == 429
            assert last.json() == {"error": "Too many attempts. Try again later."}

    async def test_me_reports_logged_out_then_logged_in(self, client):
        async with studio_db():
            await _make_admin()
            r0 = await client.get("/api/admin/me")
            assert r0.json() == {"username": None}
            await _login(client)
            r1 = await client.get("/api/admin/me")
            assert r1.json() == {"username": "tester"}

    async def test_logout_clears_session(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.post("/api/admin/logout")
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            r2 = await client.get("/api/admin/me")
            assert r2.json() == {"username": None}


class TestStudyLifecycle:
    async def test_patch_archives_and_unarchives(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-archive-test")

            r = await client.patch(f"/api/admin/studies/{slug}", json={"archived": True})
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            detail = await client.get(f"/api/admin/studies/{slug}")
            assert detail.json()["study"]["archived"] is True

            r2 = await client.patch(f"/api/admin/studies/{slug}", json={"archived": False})
            assert r2.status_code == 200
            detail2 = await client.get(f"/api/admin/studies/{slug}")
            assert detail2.json()["study"]["archived"] is False

    async def test_patch_unknown_slug_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.patch("/api/admin/studies/no-such-study", json={"archived": True})
            assert r.status_code == 404
            assert r.json() == {"error": "Study not found"}

    async def test_study_detail_embeds_clean_ids(self, client, studies_root):
        """Empirical check for the AdminJSONResponse + response_model
        interaction: study/codes/sessions are real Beanie documents flowing
        through a typed `response_model=StudyDetailResponse` now, and must
        still surface `id` (not Mongo's `_id`) after AdminJSONResponse's
        render() runs.
        """
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-idcheck")
            r = await client.get(f"/api/admin/studies/{slug}")
            assert r.status_code == 200
            body = r.json()
            assert "id" in body["study"]
            assert "_id" not in body["study"]

    async def test_register_unknown_dir_returns_400(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.post("/api/admin/studies/register", json={"dir_name": "does-not-exist"})
            assert r.status_code == 400

    async def test_register_again_freezes_a_new_version(self, client, studies_root, tmp_path):
        """Using a study never conflicts: each registration freezes a fresh
        read-only copy under studies/_inuse/, versioned -v2, -v3, ..."""
        import shutil
        from studio.settings import get_settings
        root = tmp_path / "studies"
        shutil.copytree(studies_root, root)
        settings = get_settings()
        original = settings.studies_dir
        settings.studies_dir = root
        try:
            async with studio_db():
                await _make_admin()
                await _login(client)
                from studio.models import Study
                # Test DB persists across runs — clear leftover registrations.
                async for st in Study.find({"slug": {"$regex": "^podium-smoke(-v\\d+)?$"}}):
                    await st.delete()

                r1 = await client.post("/api/admin/studies/register", json={"dir_name": "podium-smoke"})
                assert r1.status_code == 200 and r1.json()["slug"] == "podium-smoke"
                r2 = await client.post("/api/admin/studies/register", json={"dir_name": "podium-smoke"})
                assert r2.status_code == 200 and r2.json()["slug"] == "podium-smoke-v2"

                # Both frozen copies exist, self-contained (no _lib refs left).
                for slug in ("podium-smoke", "podium-smoke-v2"):
                    frozen = root / "_inuse" / slug
                    assert (frozen / "study.yaml").is_file()
                    assert "_lib" not in (frozen / "study.yaml").read_text(encoding="utf-8")
                    st = await Study.find_one(Study.slug == slug)
                    assert st is not None and st.study_dir == f"_inuse/{slug}"

                # Frozen copies cannot be registered again.
                r3 = await client.post("/api/admin/studies/register",
                                       json={"dir_name": "_inuse/podium-smoke"})
                assert r3.status_code == 400
        finally:
            settings.studies_dir = original

    async def test_reload_unknown_slug_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.post("/api/admin/studies/no-such-study/reload")
            assert r.status_code == 404


class TestUsers:
    async def test_create_rejects_short_password_with_422(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.post("/api/admin/users", json={"username": "short-pw", "password": "abc"})
            assert r.status_code == 422

    async def test_create_duplicate_username_returns_409(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            await client.post("/api/admin/users", json={"username": "dupe", "password": "longenough1"})
            r = await client.post("/api/admin/users", json={"username": "dupe", "password": "longenough2"})
            assert r.status_code == 409

    async def test_patch_sets_password(self, client):
        from studio.models import AdminUser
        async with studio_db():
            await _make_admin()
            await _login(client)
            target = await AdminUser(username="patch-target", pw_hash="x").insert()
            r = await client.patch(f"/api/admin/users/{target.id}", json={"password": "brand-new-pw"})
            assert r.status_code == 200
            assert r.json()["ok"] is True

    async def test_patch_short_password_returns_422(self, client):
        from studio.models import AdminUser
        async with studio_db():
            await _make_admin()
            await _login(client)
            target = await AdminUser(username="patch-target-2", pw_hash="x").insert()
            r = await client.patch(f"/api/admin/users/{target.id}", json={"password": "abc"})
            assert r.status_code == 422

    async def test_patch_no_fields_returns_400(self, client):
        from studio.models import AdminUser
        async with studio_db():
            await _make_admin()
            await _login(client)
            target = await AdminUser(username="patch-target-3", pw_hash="x").insert()
            r = await client.patch(f"/api/admin/users/{target.id}", json={})
            assert r.status_code == 400

    async def test_delete_self_returns_409(self, client):
        from studio.models import AdminUser
        async with studio_db():
            await _make_admin()
            await _login(client)
            me = await AdminUser.find_one(AdminUser.username == "tester")
            r = await client.delete(f"/api/admin/users/{me.id}")
            assert r.status_code == 409

    async def test_delete_last_admin_returns_409(self, client):
        from studio.models import AdminUser
        async with studio_db():
            # Ensure exactly one admin exists for this check.
            await AdminUser.find().delete()
            await _make_admin()
            await _login(client)
            me = await AdminUser.find_one(AdminUser.username == "tester")
            other = await AdminUser(username="throwaway-victim", pw_hash="x").insert()
            # Delete every other admin first so "tester" is the last one, then
            # try to delete a *different* id — count() <= 1 still trips.
            await other.delete()
            r = await client.delete(f"/api/admin/users/{me.id}")
            assert r.status_code == 409

    async def test_delete_unknown_user_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.delete("/api/admin/users/000000000000000000000000")
            assert r.status_code == 404

    async def test_delete_succeeds_for_non_self_non_last_admin(self, client):
        from studio.models import AdminUser
        async with studio_db():
            await _make_admin()
            await _login(client)
            victim = await AdminUser(username="deletable", pw_hash="x").insert()
            r = await client.delete(f"/api/admin/users/{victim.id}")
            assert r.status_code == 200
            assert r.json()["ok"] is True
            assert await AdminUser.get(victim.id) is None


class TestCodes:
    async def _make_code(self, studies_root):
        import secrets
        from studio.models import Code, Study
        slug = await _register_smoke_study(studies_root, "-codes-test")
        study = await Study.find_one(Study.slug == slug)
        return await Code(code=secrets.token_hex(6).upper(), study_id=study.id).insert()

    async def test_patch_toggles_active(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            code = await self._make_code(studies_root)
            r = await client.patch(f"/api/admin/codes/{code.id}", json={"active": False})
            assert r.status_code == 200
            body = r.json()
            assert body["active"] is False
            assert body["id"] == str(code.id)

    async def test_patch_sets_limits(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            code = await self._make_code(studies_root)
            r = await client.patch(
                f"/api/admin/codes/{code.id}",
                json={"max_uses": 5, "expires_in_hours": 24},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["max_uses"] == 5
            assert body["expires_at"] is not None

    async def test_patch_bad_max_uses_returns_422(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            code = await self._make_code(studies_root)
            r = await client.patch(f"/api/admin/codes/{code.id}", json={"max_uses": "not-a-number"})
            assert r.status_code == 422

    async def test_patch_omitted_field_leaves_unchanged(self, client, studies_root):
        """True partial-PATCH semantics: setting max_uses first, then PATCHing
        only `active`, must not clear max_uses."""
        async with studio_db():
            await _make_admin()
            await _login(client)
            code = await self._make_code(studies_root)
            await client.patch(f"/api/admin/codes/{code.id}", json={"max_uses": 3})
            r = await client.patch(f"/api/admin/codes/{code.id}", json={"active": False})
            assert r.status_code == 200
            assert r.json()["max_uses"] == 3

    async def test_patch_unknown_code_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.patch("/api/admin/codes/000000000000000000000000", json={"active": False})
            assert r.status_code == 404


class TestWebhooks:
    async def _make_hook(self, studies_root):
        from studio.models import Study, WebhookEndpoint
        slug = await _register_smoke_study(studies_root, "-webhooks-test")
        study = await Study.find_one(Study.slug == slug)
        return await WebhookEndpoint(study_id=study.id, url="https://example.test/hook", secret="s").insert()

    async def test_index_never_leaks_secret(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            await self._make_hook(studies_root)
            r = await client.get("/api/admin/webhooks")
            assert r.status_code == 200
            body_text = r.text
            assert '"secret"' not in body_text

    async def test_create_unknown_event_returns_400(self, client, studies_root):
        from studio.models import Study
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-webhooks-create")
            r = await client.post("/api/admin/webhooks", json={
                "study_slug": slug, "url": "https://example.test/hook",
                "events": ["not_a_real_event"],
            })
            assert r.status_code == 400

    async def test_create_returns_hook_without_secret(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-webhooks-create2")
            r = await client.post("/api/admin/webhooks", json={
                "study_slug": slug, "url": "https://example.test/hook",
            })
            assert r.status_code == 200
            assert "secret" not in r.json()["hook"]

    async def test_patch_toggles_active(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            hook = await self._make_hook(studies_root)
            r = await client.patch(f"/api/admin/webhooks/{hook.id}", json={"active": False})
            assert r.status_code == 200
            assert r.json()["active"] is False
            assert "secret" not in r.json()

    async def test_delete_removes_hook_and_audits(self, client, studies_root):
        from studio.models import AuditEntry, WebhookEndpoint
        async with studio_db():
            await _make_admin()
            await _login(client)
            hook = await self._make_hook(studies_root)
            r = await client.delete(f"/api/admin/webhooks/{hook.id}")
            assert r.status_code == 200
            assert await WebhookEndpoint.get(hook.id) is None
            entries = await AuditEntry.find(AuditEntry.action == "webhook.delete").to_list()
            assert any(e.target_id == str(hook.id) for e in entries)

    async def test_delete_unknown_hook_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.delete("/api/admin/webhooks/000000000000000000000000")
            assert r.status_code == 404


async def _make_session(studies_root, slug_suffix: str = "-sessions-test"):
    from studio.models import Session, Study
    slug = await _register_smoke_study(studies_root, slug_suffix)
    study = await Study.find_one(Study.slug == slug)
    return await Session(study_id=study.id).insert()


class TestMarkers:
    async def test_add_returns_marker_with_id(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-markers-add")
            r = await client.post(
                f"/api/admin/sessions/{session.id}/marker",
                json={"t_ms": 1500, "kind": "aha", "label": "got it",
                      "quote": "and THAT is when I saw the fire"},
            )
            assert r.status_code == 200
            marker = r.json()["marker"]
            assert marker["marker_id"]
            assert marker["t_ms"] == 1500
            assert marker["kind"] == "aha"
            assert marker["quote"] == "and THAT is when I saw the fire"

            # quote is optional — markers minted from the playbar omit it
            r2 = await client.post(
                f"/api/admin/sessions/{session.id}/marker",
                json={"t_ms": 2500, "kind": "note"},
            )
            assert r2.status_code == 200
            assert r2.json()["marker"]["quote"] == ""

    async def test_delete_by_id_removes_marker(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-markers-delete")
            add = await client.post(f"/api/admin/sessions/{session.id}/marker", json={"t_ms": 100})
            marker_id = add.json()["marker"]["marker_id"]
            r = await client.delete(f"/api/admin/sessions/{session.id}/marker/{marker_id}")
            assert r.status_code == 200
            detail = await client.get(f"/api/admin/sessions/{session.id}")
            assert detail.json()["session"]["markers"] == []

    async def test_delete_unknown_marker_returns_404(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-markers-404")
            r = await client.delete(f"/api/admin/sessions/{session.id}/marker/no-such-id")
            assert r.status_code == 404

    async def test_delete_has_no_request_body_requirement(self, client, studies_root):
        """The whole point of the marker_id redesign: DELETE carries no body,
        unlike the old (t_ms, author) composite-key POST."""
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-markers-nobody")
            add = await client.post(f"/api/admin/sessions/{session.id}/marker", json={"t_ms": 200})
            marker_id = add.json()["marker"]["marker_id"]
            r = await client.request("DELETE", f"/api/admin/sessions/{session.id}/marker/{marker_id}")
            assert r.status_code == 200

    async def test_legacy_marker_without_id_gets_backfilled_on_read(self, client, studies_root):
        """Simulates data written before this migration: a marker dict with
        no `marker_id`. Reading it via replay/session-detail must lazily
        assign one (self-healing, no migration script needed)."""
        from studio.models import Session
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-markers-legacy")
            session.markers = [{"author": "tester", "t_ms": 50, "kind": "note",
                                 "label": "old data", "wall_clock": "2020-01-01T00:00:00"}]
            await session.save()
            r = await client.get(f"/api/admin/replay/{session.id}")
            assert r.status_code == 200
            markers = r.json()["session"]["markers"]
            assert len(markers) == 1
            assert markers[0]["marker_id"]
            # Backfill must persist, not just appear in this one response.
            reloaded = await Session.get(session.id)
            assert reloaded.markers[0].get("marker_id")


class TestNotes:
    async def test_add_note_returns_note_and_list(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-notes-add")
            r = await client.post(f"/api/admin/sessions/{session.id}/note", json={"text": "checked in"})
            assert r.status_code == 200
            body = r.json()
            assert body["note"]["text"] == "checked in"
            assert len(body["notes"]) == 1

    async def test_empty_text_returns_400(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-notes-empty")
            r = await client.post(f"/api/admin/sessions/{session.id}/note", json={"text": "   "})
            assert r.status_code == 400

    async def test_list_notes(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-notes-list")
            await client.post(f"/api/admin/sessions/{session.id}/note", json={"text": "one"})
            await client.post(f"/api/admin/sessions/{session.id}/note", json={"text": "two"})
            r = await client.get(f"/api/admin/sessions/{session.id}/notes")
            assert r.status_code == 200
            assert len(r.json()["notes"]) == 2


class TestTags:
    async def test_set_tags_returns_sorted_merged_tags(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-tags")
            r = await client.post(f"/api/admin/sessions/{session.id}/tags", json={"tags": "B, a, a"})
            assert r.status_code == 200
            assert r.json()["tags"] == ["a", "b"]

    async def test_set_tags_unknown_session_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.post("/api/admin/sessions/000000000000000000000000/tags", json={"tags": "x"})
            assert r.status_code == 404


class TestSessionGetRoutes:
    async def test_session_detail_embeds_clean_ids(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-detail")
            r = await client.get(f"/api/admin/sessions/{session.id}")
            assert r.status_code == 200
            body = r.json()
            assert "id" in body["session"]
            assert "_id" not in body["session"]

    async def test_sessions_index_lists_session(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-index")
            r = await client.get("/api/admin/sessions")
            assert r.status_code == 200
            ids = [row["session"]["id"] for row in r.json()["rows"]]
            assert str(session.id) in ids

    async def test_live_session_returns_typed_payload(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-live")
            r = await client.get(f"/api/admin/sessions/{session.id}/live")
            assert r.status_code == 200
            assert r.json()["spectator_urls"] == []

    async def test_live_session_poll_returns_typed_payload(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            session = await _make_session(studies_root, "-poll")
            r = await client.get(f"/api/admin/sessions/{session.id}/live/poll")
            assert r.status_code == 200
            body = r.json()
            assert body["session"]["id"] == str(session.id)
            assert body["participants"] == []


class TestPhase5Routes:
    """Final response_model sweep: verb fix (views delete) + error-handling
    fixes on the remaining bare-{"error": ...} routes."""

    async def test_dashboard_returns_typed_payload(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.get("/api/admin/")
            assert r.status_code == 200
            body = r.json()
            assert "per_study" in body and "overview" in body

    async def test_new_study_page_lists_available_studies(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.get("/api/admin/studies/new")
            assert r.status_code == 200
            dirs = [a["dir_name"] for a in r.json()["available"]]
            assert "podium-smoke" in dirs

    async def test_new_code_unknown_role_returns_400(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-newcode-400")
            r = await client.post(f"/api/admin/studies/{slug}/codes", json={"role": "no-such-role"})
            assert r.status_code == 400

    async def test_new_code_success_returns_typed_code(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-newcode-ok")
            r = await client.post(f"/api/admin/studies/{slug}/codes", json={})
            assert r.status_code == 200
            assert len(r.json()["code"]) == 6

    async def test_mint_cohort_unknown_role_returns_400(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-cohort-400")
            r = await client.post(f"/api/admin/studies/{slug}/cohort", json={"roles": "no-such-role"})
            assert r.status_code == 400

    async def test_save_view_empty_name_returns_400(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.post("/api/admin/views/save", json={"name": "  "})
            assert r.status_code == 400

    async def test_save_and_delete_view_via_delete_verb(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            save = await client.post("/api/admin/views/save", json={"name": "my view", "query": "status=running"})
            assert save.status_code == 200
            view_id = save.json()["view"]["id"]
            # Old verb-suffix route must be gone.
            old = await client.post(f"/api/admin/views/{view_id}/delete")
            assert old.status_code == 404
            r = await client.delete(f"/api/admin/views/{view_id}")
            assert r.status_code == 200

    async def test_delete_view_unknown_id_returns_404(self, client):
        async with studio_db():
            await _make_admin()
            await _login(client)
            r = await client.delete("/api/admin/views/000000000000000000000000")
            assert r.status_code == 404

    async def test_compare_index_returns_typed_payload(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-compare")
            r = await client.get(f"/api/admin/compare?studies={slug}")
            assert r.status_code == 200
            assert r.json()["selected_slugs"] == [slug]

    async def test_search_returns_typed_payload(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            await _register_smoke_study(studies_root, "-search")
            r = await client.get("/api/admin/search?q=podium")
            assert r.status_code == 200
            body = r.json()
            assert "studies" in body["results"]

    async def test_irr_returns_typed_payload(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-irr")
            r = await client.get(f"/api/admin/irr?study={slug}")
            assert r.status_code == 200
            assert r.json()["selected_study"] == slug


class TestTaskLibrary:
    @pytest.fixture
    def tmp_studies(self, studies_root, tmp_path):
        """Writable copy of the fixture studies dir — library endpoints WRITE
        files, and the shared fixtures must stay pristine."""
        import shutil
        root = tmp_path / "studies"
        shutil.copytree(studies_root, root)
        from studio.settings import get_settings
        settings = get_settings()
        original = settings.studies_dir
        settings.studies_dir = root
        yield root
        settings.studies_dir = original

    async def test_crud_validation_and_in_use_lock(self, client, tmp_studies):
        async with studio_db():
            await _make_admin()
            await _login(client)
            # The test DB persists across runs; drop a leftover 'libuser'
            # registration so the register step below stays repeatable.
            from studio.models import Study
            stale = await Study.find_one(Study.slug == "libuser")
            if stale is not None:
                await stale.delete()
            content = "id: shared-q\ntype: free_text\nprompt_md: |\n  ## Q\nmin_chars: 1\n"

            # create
            r = await client.put("/api/admin/library/tasks/shared-q.yaml", json={"content": content})
            assert r.status_code == 200, r.text

            # schema-invalid task is rejected with a 400
            bad = await client.put("/api/admin/library/tasks/bad.yaml",
                                   json={"content": "id: x\ntype: not-a-type\n"})
            assert bad.status_code == 400
            noid = await client.put("/api/admin/library/tasks/noid.yaml",
                                    json={"content": "type: info_screen\nbody_md: hi\n"})
            assert noid.status_code == 400
            trav = await client.put("/api/admin/library/tasks/..%2Fevil.yaml", json={"content": content})
            assert trav.status_code in (400, 404)

            # unused: editable, listed unlocked
            lst = (await client.get("/api/admin/library/tasks")).json()["tasks"]
            row = next(t for t in lst if t["file"] == "shared-q.yaml")
            assert row["read_only"] is False and row["used_by"] == []

            # a registered study picks the shared task up via $ref — the
            # registration FREEZES a materialized copy; the library task
            # itself stays fully editable.
            sdir = tmp_studies / "libuser"
            (sdir / "tasks").mkdir(parents=True)
            (sdir / "study.yaml").write_text(
                "id: libuser\nname: Lib user\nmode: singleplayer\n"
                "blocks:\n  - id: main\n    tasks:\n"
                "      - $ref: ../_lib/tasks/shared-q.yaml\n",
                encoding="utf-8",
            )
            reg = await client.post("/api/admin/studies/register", json={"dir_name": "libuser"})
            assert reg.status_code == 200, reg.text
            slug = reg.json()["slug"]

            frozen = tmp_studies / "_inuse" / slug
            assert (frozen / "tasks" / "shared-q.yaml").read_text(encoding="utf-8") == content
            assert "$ref: tasks/shared-q.yaml" in (frozen / "study.yaml").read_text(encoding="utf-8")

            # The library task is STILL editable — and the frozen copy is
            # unaffected by the edit.
            edit = await client.put("/api/admin/library/tasks/shared-q.yaml",
                                    json={"content": content + "rows: 6\n"})
            assert edit.status_code == 200
            assert (frozen / "tasks" / "shared-q.yaml").read_text(encoding="utf-8") == content

            # an unused task can be deleted
            r2 = await client.put("/api/admin/library/tasks/scratch.yaml",
                                  json={"content": content.replace("shared-q", "scratch")})
            assert r2.status_code == 200
            assert (await client.delete("/api/admin/library/tasks/scratch.yaml")).status_code == 200

    async def test_browse_lists_dirs_with_registered_flag(self, client, tmp_studies):
        async with studio_db():
            await _make_admin()
            await _login(client)
            await _register_smoke_study(tmp_studies, "-libbrowse")
            b = (await client.get("/api/admin/library/browse")).json()["studies"]
            by_dir = {e["dir"]: e for e in b}
            assert "_lib" in by_dir and by_dir["_lib"]["has_study_yaml"] is False
            smoke = by_dir["podium-smoke"]
            assert smoke["has_study_yaml"] is True
            assert "study.yaml" in smoke["files"] and any(f.startswith("tasks/") for f in smoke["files"])


class TestSharedReplay:
    """Read-only replay share links: mint → public view → revoke."""

    async def test_share_mint_public_view_revoke_roundtrip(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-share")
            from studio.models import Session, Study
            study = await Study.find_one(Study.slug == slug)
            session = await Session(study_id=study.id, status="completed").insert()

            # Mint — idempotent, same token on re-mint.
            r = await client.post(f"/api/admin/sessions/{session.id}/share")
            assert r.status_code == 200
            token = r.json()["token"]
            assert r.json()["url"] == f"/admin/shared/{token}"
            assert (await client.post(f"/api/admin/sessions/{session.id}/share")).json()["token"] == token

            # The shared endpoint needs NO admin cookie.
            from httpx import ASGITransport, AsyncClient
            from studio.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
                pr = await anon.get(f"/api/shared/replay/{token}")
                assert pr.status_code == 200
                body = pr.json()
                assert body["session"]["id"] == str(session.id)
                assert body["study"]["slug"] == slug
                assert "timeline" in body["payload"]
                # Slim session shape: no process info / notes / snapshot leak.
                assert "vas" not in body["session"] and "notes" not in body["session"]

                # task_va ships with the payload: VA tasks map to a system id,
                # question tasks map to None (drives absent-agent graying).
                task_va = body["payload"]["task_va"]
                assert any(v is None for v in task_va.values())
                assert any(isinstance(v, str) for v in task_va.values())

                # Wrong / revoked tokens don't resolve.
                assert (await anon.get("/api/shared/replay/NOSUCHTOKEN1234567890")).status_code == 404
                assert (await client.delete(f"/api/admin/sessions/{session.id}/share")).status_code == 200
                assert (await anon.get(f"/api/shared/replay/{token}")).status_code == 404

    async def test_short_or_empty_token_is_rejected(self, client):
        async with studio_db():
            from httpx import ASGITransport, AsyncClient
            from studio.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
                assert (await anon.get("/api/shared/replay/short")).status_code == 404


class TestStudyLibrary:
    @pytest.fixture
    def tmp_studies(self, studies_root, tmp_path):
        """Writable copy of the fixture studies dir — library endpoints WRITE
        files, and the shared fixtures must stay pristine."""
        import shutil
        root = tmp_path / "studies"
        shutil.copytree(studies_root, root)
        from studio.settings import get_settings
        settings = get_settings()
        original = settings.studies_dir
        settings.studies_dir = root
        yield root
        settings.studies_dir = original

    async def test_create_edit_use_freezes_readonly_copy(self, client, tmp_studies):
        async with studio_db():
            await _make_admin()
            await _login(client)
            # Test DB persists across runs — drop leftovers for repeatability.
            from studio.models import Session, Study
            async for stale in Study.find({"slug": {"$regex": "^libstudy(-v\\d+)?$"}}):
                await Session.find(Session.study_id == stale.id).delete()
                await stale.delete()

            yaml_v1 = (
                "id: libstudy\nname: Lib Study\nmode: singleplayer\n"
                "consent_text_md: |\n  # Consent\ntasks:\n"
                "  - id: welcome\n    type: info_screen\n    prompt_md: |\n      ## Hi\n"
            )

            # Create a brand-new study dir + study.yaml.
            r = await client.put("/api/admin/library/studies/libstudy", json={"content": yaml_v1})
            assert r.status_code == 200
            assert (tmp_studies / "libstudy" / "study.yaml").is_file()

            # It shows up in the list, not in use yet.
            rows = (await client.get("/api/admin/library/studies")).json()["studies"]
            row = next(s for s in rows if s["dir"] == "libstudy")
            assert row["in_use"] == [] and row["name"] == "Lib Study"

            # Content roundtrip.
            got = (await client.get("/api/admin/library/studies/libstudy")).json()
            assert got["content"] == yaml_v1

            # Garbage is rejected before touching disk.
            assert (await client.put("/api/admin/library/studies/libstudy",
                                     json={"content": "not: [valid"})).status_code == 400
            assert (await client.put("/api/admin/library/studies/libstudy",
                                     json={"content": "name: no id here"})).status_code == 400
            assert (await client.put("/api/admin/library/studies/bad name",
                                     json={"content": yaml_v1})).status_code == 400

            # USE the study: a frozen, self-contained copy appears in _inuse
            # and a Study document points at it.
            reg = await client.post("/api/admin/studies/register", json={"dir_name": "libstudy"})
            assert reg.status_code == 200 and reg.json()["slug"] == "libstudy"
            frozen = tmp_studies / "_inuse" / "libstudy"
            assert (frozen / "study.yaml").is_file()
            study = await Study.find_one(Study.slug == "libstudy")
            assert study is not None and study.study_dir == "_inuse/libstudy"

            # The LIBRARY stays editable — even with an active session running
            # the frozen copy — and the edit never reaches the frozen copy.
            session = await Session(study_id=study.id, status="running").insert()
            frozen_before = (frozen / "study.yaml").read_text(encoding="utf-8")
            r2 = await client.put("/api/admin/library/studies/libstudy",
                                  json={"content": yaml_v1.replace("Lib Study", "Lib Study EDITED")})
            assert r2.status_code == 200
            assert (frozen / "study.yaml").read_text(encoding="utf-8") == frozen_before
            study = await Study.find_one(Study.slug == "libstudy")
            assert study.name == "Lib Study"  # registered copy untouched
            session.status = "completed"
            await session.save()

            # The frozen copy is read-only everywhere: the study YAML editor
            # refuses, and the library save endpoint can't reach _inuse paths.
            y = await client.post("/api/admin/studies/libstudy/yaml",
                                  json={"relative_path": "study.yaml", "content": yaml_v1})
            assert y.status_code == 409
            assert "read-only" in y.json()["error"]

            # In-use listing + read-only view.
            inuse = (await client.get("/api/admin/library/inuse")).json()["studies"]
            entry = next(e for e in inuse if e["slug"] == "libstudy")
            assert entry["registered"] is True
            view = (await client.get("/api/admin/library/inuse/libstudy")).json()
            assert "id: libstudy" in view["content"]

            # Using it AGAIN freezes a second version.
            reg2 = await client.post("/api/admin/studies/register", json={"dir_name": "libstudy"})
            assert reg2.status_code == 200 and reg2.json()["slug"] == "libstudy-v2"
            assert (tmp_studies / "_inuse" / "libstudy-v2" / "study.yaml").is_file()
            # The v2 copy carries the LIBRARY edit; v1 still has the original.
            assert "Lib Study EDITED" in (tmp_studies / "_inuse" / "libstudy-v2" / "study.yaml").read_text(encoding="utf-8")
            rows = (await client.get("/api/admin/library/studies")).json()["studies"]
            row = next(s for s in rows if s["dir"] == "libstudy")
            assert row["in_use"] == ["libstudy", "libstudy-v2"]

    async def test_task_files_inside_a_study_are_editable_and_addable(self, client, tmp_studies):
        async with studio_db():
            await _make_admin()
            await _login(client)

            # podium-smoke ships task files under tasks/ — the view endpoint
            # lists them and serves any of them by ?path=.
            got = (await client.get("/api/admin/library/studies/podium-smoke")).json()
            assert got["path"] == "study.yaml"
            task_files = [f for f in got["files"] if f.startswith("tasks/")]
            assert task_files, got["files"]
            first = task_files[0]
            fgot = (await client.get(
                f"/api/admin/library/studies/podium-smoke?path={first}")).json()
            assert fgot["path"] == first and fgot["content"]

            # Edit that task file in place (append a comment — stays valid).
            r = await client.put("/api/admin/library/studies/podium-smoke",
                                 json={"path": first, "content": fgot["content"] + "\n# edited\n"})
            assert r.status_code == 200
            assert (tmp_studies / "podium-smoke" / first).read_text(encoding="utf-8").endswith("# edited\n")

            # Add a brand-new task file.
            r = await client.put("/api/admin/library/studies/podium-smoke",
                                 json={"path": "tasks/lib-extra.yaml",
                                       "content": "type: free_text\nprompt_md: |\n  ## Q\nmin_chars: 1\n"})
            assert r.status_code == 200
            assert (tmp_studies / "podium-smoke" / "tasks" / "lib-extra.yaml").is_file()

            # Path escapes and non-YAML paths are refused.
            assert (await client.put("/api/admin/library/studies/podium-smoke",
                                     json={"path": "../evil.yaml", "content": "a: 1"})).status_code == 400
            assert (await client.put("/api/admin/library/studies/podium-smoke",
                                     json={"path": "tasks/x.txt", "content": "a: 1"})).status_code == 400

    async def test_saved_but_invalid_study_returns_warning_not_error(self, client, tmp_studies):
        async with studio_db():
            await _make_admin()
            await _login(client)
            # Parses as YAML-with-id but fails full validation (bad task type):
            # the file must be saved, with a warning instead of a hard error.
            bad = "id: libwarn\nname: W\nmode: singleplayer\ntasks:\n  - id: t\n    type: no_such_type\n"
            r = await client.put("/api/admin/library/studies/libwarn", json={"content": bad})
            assert r.status_code == 200
            assert r.json().get("warning")
            assert (tmp_studies / "libwarn" / "study.yaml").read_text(encoding="utf-8") == bad


class TestSessionDelete:
    async def test_delete_cascades_docs_and_media_files(self, client, studies_root, tmp_path):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-sessdel")
            from studio.models import (
                AudioChunk, Event, Participant, Session, Study, Transcript, VideoChunk,
            )
            from studio.settings import get_settings
            study = await Study.find_one(Study.slug == slug)
            session = await Session(study_id=study.id, status="completed").insert()
            p = await Participant(session_id=session.id, study_id=study.id, anon_id="p_del").insert()
            await Event(study_id=study.id, session_id=session.id, t_ms=1,
                        source="studio", type="task_start").insert()
            await AudioChunk(session_id=session.id, participant_id=p.id, chunk_seq=0,
                             chunk_started_wall=session.created_at, file_path="x").insert()

            # Media files on disk under data/{audio,video}/<study>/<session>/.
            settings = get_settings()
            orig_data = settings.data_dir
            settings.data_dir = tmp_path / "data"
            try:
                media = settings.data_dir / "video" / str(study.id) / str(session.id)
                media.mkdir(parents=True)
                (media / "chunk_000000.webm").write_bytes(b"fake")

                r = await client.delete(f"/api/admin/sessions/{session.id}")
                assert r.status_code == 200, r.text
                assert "1 participant" in r.json()["message"]

                assert await Session.get(session.id) is None
                assert await Participant.find(Participant.session_id == session.id).count() == 0
                assert await Event.find(Event.session_id == session.id).count() == 0
                assert await AudioChunk.find(AudioChunk.session_id == session.id).count() == 0
                assert await Transcript.find(Transcript.session_id == session.id).count() == 0
                assert await VideoChunk.find(VideoChunk.session_id == session.id).count() == 0
                assert not media.exists()
            finally:
                settings.data_dir = orig_data

            # Unknown / malformed ids are proper errors, not crashes.
            assert (await client.delete(f"/api/admin/sessions/{session.id}")).status_code == 404
            assert (await client.delete("/api/admin/sessions/not-an-id")).status_code == 400


class TestReplayVideoAlignment:
    """The replay maps playback time ↔ session time piecewise, so a recording
    gap (a chunk that never uploaded) can't drift the event timeline."""

    async def test_segments_and_tmax_survive_a_recording_gap(self, client, studies_root):
        async with studio_db():
            from studio.api.analytics_helpers import replay_payload
            from studio.models import Event, Session, Study, VideoChunk
            slug = await _register_smoke_study(studies_root, "-vidalign")
            study = await Study.find_one(Study.slug == slug)
            session = await Session(study_id=study.id, status="completed").insert()
            await VideoChunk.find(VideoChunk.session_id == session.id).delete()

            # One event early on; the recording runs far past it.
            await Event(study_id=study.id, session_id=session.id, t_ms=1000,
                        source="studio", type="task_start").insert()

            # chunks at 0s and 5s (contiguous), then a 20s GAP, then 30s and 35s.
            starts = [0, 5000, 30000, 35000]
            for seq, t0 in enumerate(starts):
                await VideoChunk(
                    session_id=session.id, participant_id=session.id, run_id="r1",
                    chunk_seq=seq, chunk_started_wall=session.created_at,
                    recorder_started_wall=session.created_at,
                    duration_ms=5000, t_ms_start=t0, t_ms_end=t0 + 5000,
                    file_path=f"/tmp/c{seq}.webm", size_bytes=1,
                ).insert()

            payload = await replay_payload(session)
            v = payload["video"]
            segs = v["segments"]
            assert [s["t_ms"] for s in segs] == starts
            # Playback time only advances over recorded material: the 20s gap
            # is NOT part of the video, so chunk 3 starts at 10s of playback.
            assert [s["video_t_ms"] for s in segs] == [0, 5000, 10000, 15000]
            assert v["duration_ms"] == 20000          # 4 × 5s recorded
            assert v["t_ms_end"] == 40000             # last start + its duration

            # t_max spans the WHOLE recording, not just the last event (1s) —
            # otherwise the scrubber can't reach the rest and the video looks
            # like it broke early.
            assert payload["t_max"] == 40000


class TestSensorIngestTokens:
    """External sensor ingest: admin mints a per-participant token, an
    external (non-browser) client authenticates with it against
    POST /ingest/sensor-chunk instead of the participant cookie."""

    async def test_mint_rejected_when_study_has_not_opted_in(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-sensornotenabled")
            from studio.models import Participant, Session, Study
            study = await Study.find_one(Study.slug == slug)
            assert not (study.recording or {}).get("external_sensor")
            session = await Session(study_id=study.id, status="running").insert()
            p = await Participant(session_id=session.id, study_id=study.id, anon_id="p_sensornotenabled").insert()

            r = await client.post(
                f"/api/admin/sessions/{session.id}/participants/{p.id}/sensor-tokens",
                json={"label": "test rig"},
            )
            assert r.status_code == 400

    async def test_mint_push_and_replay_roundtrip(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-sensorflow")
            from studio.models import Event, Participant, SensorChunk, Session, Study
            study = await Study.find_one(Study.slug == slug)
            study.recording = {**(study.recording or {}), "external_sensor": True}
            await study.save()
            session = await Session(study_id=study.id, status="running").insert()
            p = await Participant(session_id=session.id, study_id=study.id, anon_id="p_sensorflow").insert()

            mint = await client.post(
                f"/api/admin/sessions/{session.id}/participants/{p.id}/sensor-tokens",
                json={"label": "Empatica E4 rig"},
            )
            assert mint.status_code == 200, mint.text
            token = mint.json()["token"]
            assert token.startswith("mvss_")

            listed = await client.get(f"/api/admin/sessions/{session.id}/participants/{p.id}/sensor-tokens")
            assert listed.status_code == 200
            assert len(listed.json()["tokens"]) == 1

            push = await client.post(
                "/ingest/sensor-chunk",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": "eda",
                    "unit": "uS",
                    "seq": 0,
                    "batch_started_wall": "2026-01-01T00:00:00Z",
                    "samples": [
                        {"t_wall": "2026-01-01T00:00:00.000Z", "value": 0.40},
                        {"t_wall": "2026-01-01T00:00:00.500Z", "value": 0.44},
                    ],
                },
            )
            assert push.status_code == 200, push.text
            assert push.json()["channel"] == "eda"
            assert push.json()["n_samples"] == 2

            chunks = await SensorChunk.find(SensorChunk.session_id == session.id).to_list()
            assert len(chunks) == 1
            assert chunks[0].channel == "eda"
            assert chunks[0].unit == "uS"
            assert [s.value for s in chunks[0].samples] == [0.40, 0.44]

            events = await Event.find(
                Event.session_id == session.id, Event.type == "sensor_chunk_received"
            ).to_list()
            assert len(events) == 1
            assert events[0].meta["channel"] == "eda"
            assert events[0].meta["n_samples"] == 2

            from studio.api.analytics_helpers import replay_payload
            payload = await replay_payload(session)
            assert "eda" in payload["sensor_channels"]
            assert len(payload["sensor_channels"]["eda"]) == 2

    async def test_revoked_token_rejected(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-sensorrevoke")
            from studio.models import Participant, Session, Study
            study = await Study.find_one(Study.slug == slug)
            study.recording = {**(study.recording or {}), "external_sensor": True}
            await study.save()
            session = await Session(study_id=study.id, status="running").insert()
            p = await Participant(session_id=session.id, study_id=study.id, anon_id="p_sensorrevoke").insert()

            mint = await client.post(
                f"/api/admin/sessions/{session.id}/participants/{p.id}/sensor-tokens",
                json={"label": "rig"},
            )
            token, token_id = mint.json()["token"], mint.json()["key"]["id"]

            revoke = await client.delete(f"/api/admin/sensor-tokens/{token_id}")
            assert revoke.status_code == 200

            push = await client.post(
                "/ingest/sensor-chunk",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": "eda", "seq": 0, "batch_started_wall": "2026-01-01T00:00:00Z",
                    "samples": [{"t_wall": "2026-01-01T00:00:00Z", "value": 1.0}],
                },
            )
            assert push.status_code == 401

    async def test_push_long_after_completion_succeeds_while_study_active(self, client, studies_root):
        async with studio_db():
            from datetime import datetime, timedelta, timezone
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-sensorgraceok")
            from studio.models import Participant, Session, Study
            study = await Study.find_one(Study.slug == slug)
            study.recording = {**(study.recording or {}), "external_sensor": True}
            await study.save()
            session = await Session(study_id=study.id, status="running").insert()
            p = await Participant(session_id=session.id, study_id=study.id, anon_id="p_sensorgraceok").insert()

            mint = await client.post(
                f"/api/admin/sessions/{session.id}/participants/{p.id}/sensor-tokens",
                json={"label": "rig"},
            )
            token = mint.json()["token"]

            session.status = "completed"
            session.ended_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
            await session.save()

            push = await client.post(
                "/ingest/sensor-chunk",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": "eda", "seq": 0, "batch_started_wall": "2026-01-01T00:00:00Z",
                    "samples": [{"t_wall": "2026-01-01T00:00:00Z", "value": 1.0}],
                },
            )
            assert push.status_code == 200, push.text

    async def test_push_rejected_after_study_archived(self, client, studies_root):
        async with studio_db():
            await _make_admin()
            await _login(client)
            slug = await _register_smoke_study(studies_root, "-sensorarchived")
            from studio.models import Participant, Session, Study
            study = await Study.find_one(Study.slug == slug)
            study.recording = {**(study.recording or {}), "external_sensor": True}
            await study.save()
            session = await Session(study_id=study.id, status="running").insert()
            p = await Participant(session_id=session.id, study_id=study.id, anon_id="p_sensorarchived").insert()

            mint = await client.post(
                f"/api/admin/sessions/{session.id}/participants/{p.id}/sensor-tokens",
                json={"label": "rig"},
            )
            token = mint.json()["token"]

            session.status = "completed"
            await session.save()
            study.archived = True
            await study.save()

            push = await client.post(
                "/ingest/sensor-chunk",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "channel": "eda", "seq": 0, "batch_started_wall": "2026-01-01T00:00:00Z",
                    "samples": [{"t_wall": "2026-01-01T00:00:00Z", "value": 1.0}],
                },
            )
            assert push.status_code == 400
