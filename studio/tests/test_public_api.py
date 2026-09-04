"""Route-level tests for the public read-only /api/v1 (external-tool access)."""
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
    from studio.settings import get_settings
    settings = get_settings()
    original = settings.studies_dir
    settings.studies_dir = studies_root
    yield
    settings.studies_dir = original


async def _make_admin_and_key(client) -> str:
    """Bootstrap an admin, log in, mint an API key; return the raw token."""
    from studio.auth import hash_password
    from studio.models import AdminUser
    if await AdminUser.find_one(AdminUser.username == "tester") is None:
        await AdminUser(username="tester", password_hash=hash_password("s3cret-pass")).insert()
    r = await client.post("/api/admin/login", json={"username": "tester", "password": "s3cret-pass"})
    assert r.status_code == 200, r.text
    r = await client.post("/api/admin/apikeys", json={"name": "pytest"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _seed_study_session(studies_root):
    """Registered study + one session + participant + a few events."""
    from studio.config.loader import load_study_dir
    from studio.models import Event, Participant, Session, Study

    cfg, _m, digest = load_study_dir(studies_root / "podium-smoke")
    slug = "podium-smoke-v1api"
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        study = Study(slug=slug, name=cfg.name, study_dir="podium-smoke")
    study.blocks = [b.model_dump() for b in cfg.blocks]
    study.metrics = [
        {"id": "n_actions", "label": "Actions", "kind": "count",
         "match": {"event_type": "user_action"}},
        {"id": "t_first", "kind": "latency",
         "from": {"event_type": "task_start"}, "to": {"event_type": "user_action"}},
    ]
    study.yaml_hash = digest
    await study.save()

    session = await Session(study_id=study.id, mode="singleplayer", status="completed").insert()
    p = await Participant(
        session_id=session.id, study_id=study.id,
        anon_id=f"p_{str(session.id)[-6:]}",
    ).insert()
    for t, typ, meta in [
        (0, "task_start", {}),
        (3000, "user_action", {"action": "set_nudges"}),
        (7000, "user_action", {"action": "drop_order"}),
        (9000, "task_end", {}),
    ]:
        await Event(
            study_id=study.id, session_id=session.id,
            participant_id=p.id if typ == "user_action" else None,
            t_ms=t, source="studio" if typ.startswith("task") else "mivais",
            type=typ, meta=meta, task_id="ex1-find-mpg",
        ).insert()
    return study, session, p


class TestAuth:
    async def test_missing_token_401(self, client):
        async with studio_db():
            r = await client.get("/api/v1/studies")
            assert r.status_code == 401

    async def test_bad_token_401(self, client):
        async with studio_db():
            r = await client.get("/api/v1/studies", headers={"Authorization": "Bearer mvs_nope"})
            assert r.status_code == 401

    async def test_revoked_key_401(self, client):
        async with studio_db():
            token = await _make_admin_and_key(client)
            keys = (await client.get("/api/admin/apikeys")).json()["keys"]
            latest = keys[0]
            await client.delete(f"/api/admin/apikeys/{latest['id']}")
            r = await client.get("/api/v1/studies", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401


class TestReads:
    async def test_full_read_path(self, client, studies_root):
        async with studio_db():
            token = await _make_admin_and_key(client)
            study, session, p = await _seed_study_session(studies_root)
            H = {"Authorization": f"Bearer {token}"}

            studies = (await client.get("/api/v1/studies", headers=H)).json()["studies"]
            assert any(s["slug"] == study.slug for s in studies)

            detail = (await client.get(f"/api/v1/studies/{study.slug}", headers=H)).json()["study"]
            assert detail["n_sessions"] >= 1 and detail["metrics"]

            sess = (await client.get(f"/api/v1/studies/{study.slug}/sessions", headers=H)).json()
            assert sess["total"] >= 1

            sdetail = (await client.get(f"/api/v1/sessions/{session.id}", headers=H)).json()["session"]
            assert sdetail["study_slug"] == study.slug
            assert sdetail["participants"][0]["anon_id"] == p.anon_id

            events = (await client.get(f"/api/v1/sessions/{session.id}/events", headers=H)).json()
            assert events["total"] == 4
            filtered = (await client.get(
                f"/api/v1/sessions/{session.id}/events?type=user_action", headers=H)).json()
            assert filtered["total"] == 2

            answers = (await client.get(f"/api/v1/sessions/{session.id}/answers", headers=H)).json()
            assert answers["participants"][0]["anon_id"] == p.anon_id

            metrics = (await client.get(f"/api/v1/sessions/{session.id}/metrics", headers=H)).json()
            vals = {m["id"]: m["value"] for m in metrics["participants"][0]["metrics"]}
            assert vals["n_actions"] == 2.0
            assert vals["t_first"] == 3.0  # task_start(0) -> first user_action(3000)

            agg = (await client.get(f"/api/v1/studies/{study.slug}/metrics", headers=H)).json()
            n_actions = next(m for m in agg["metrics"] if m["id"] == "n_actions")
            assert n_actions["n_participants"] >= 1

            ann = (await client.get(f"/api/v1/sessions/{session.id}/annotations", headers=H)).json()
            assert ann == {"markers": [], "notes": [], "tags": [], "tags_by_author": {}}

            tr = (await client.get(f"/api/v1/sessions/{session.id}/transcript", headers=H)).json()
            assert tr["status"] in ("none", "disabled")
