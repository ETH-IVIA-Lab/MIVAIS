"""REST-conventions migration: participant.py route-level tests.

No verb changes here --
these tests cover the genuine-error conversions (_start_or_resume's
400/409s), the typed request bodies, and response_model coverage for the
participant-facing flow. Uses the same client/studio_db patterns as
test_admin_api.py.
"""
from __future__ import annotations

import contextlib
import secrets

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


async def _register_study(studies_root, dir_name: str = "podium-smoke", slug_suffix: str = "") -> "Study":  # noqa: F821
    from studio.config.loader import load_study_dir
    from studio.models import Study
    cfg, _manifest, digest = load_study_dir(studies_root / dir_name)
    slug = cfg.id + slug_suffix
    s = await Study.find_one(Study.slug == slug)
    if s is None:
        s = Study(slug=slug, name=cfg.name, study_dir=dir_name)
    s.name = cfg.name
    s.mode = cfg.mode
    s.consent_text_md = cfg.consent_text_md
    s.va_systems = {k: v.model_dump() for k, v in cfg.va_systems.items()}
    s.primary_va_system = cfg.primary_va_system
    s.roles = [r.model_dump() for r in cfg.roles]
    s.advance_policy = cfg.advance_policy
    s.participants_required = cfg.participants_required
    s.blocks = [block.model_dump() for block in cfg.blocks]
    s.yaml_hash = digest
    await s.save()
    return s


async def _mint_code(study, role: str | None = None):
    from studio.models import Code
    return await Code(code=secrets.token_hex(6).upper(), study_id=study.id, role=role).insert()


class TestJoin:
    async def test_bad_code_returns_400(self, client, studies_root):
        async with studio_db():
            await _register_study(studies_root, slug_suffix="-join-bad")
            r = await client.post("/api/join", json={"code": "NOSUCHCODE"})
            assert r.status_code == 400
            assert r.json() == {"error": "Invalid or expired code."}

    async def test_good_code_sets_cookie_and_returns_next(self, client, studies_root):
        async with studio_db():
            study = await _register_study(studies_root, slug_suffix="-join-good")
            code = await _mint_code(study)
            r = await client.post("/api/join", json={"code": code.code})
            assert r.status_code == 200
            assert r.json()["next"] == "/p/consent"
            assert "studio_participant" in r.cookies

    async def test_code_bound_to_undeclared_role_returns_409(self, client, studies_root):
        async with studio_db():
            study = await _register_study(studies_root, slug_suffix="-join-role409")
            code = await _mint_code(study, role="no-such-role")
            r = await client.post("/api/join", json={"code": code.code})
            assert r.status_code == 409

    async def test_archived_study_rejects_new_joins_with_410(self, client, studies_root):
        async with studio_db():
            study = await _register_study(studies_root, slug_suffix="-join-archived")
            study.archived = True
            await study.save()
            code = await _mint_code(study)
            r = await client.post("/api/join", json={"code": code.code})
            assert r.status_code == 410
            assert "closed" in r.json()["error"]
            # Preflight mirrors the rejection so the pre-join page warns early.
            pf = await client.get(f"/api/p/preflight/{code.code}")
            assert pf.json()["valid_code"] is False

    async def test_archived_study_still_lets_midrun_participant_resume(self, client, studies_root):
        """Archiving closes the door to NEW participants; someone already in
        the study (cookie set, not finished) can still resume via the link."""
        async with studio_db():
            from studio.models import Study
            study = await _register_study(studies_root, slug_suffix="-join-arch-resume")
            # _register_study reuses an existing study doc by slug, so a
            # previous run's archiving would leak in — reset for idempotency.
            study.archived = False
            await study.save()
            code = await _mint_code(study)
            r = await client.post("/api/join", json={"code": code.code})
            assert r.status_code == 200  # joined while active; cookie now set
            study = await Study.find_one(Study.slug == study.slug)
            study.archived = True
            await study.save()
            r2 = await client.post("/api/join", json={"code": code.code})
            assert r2.status_code == 200

    async def test_multiplayer_second_role_code_same_browser_returns_409(self, client, studies_root):
        """Regression: a second, DIFFERENT code entered on a browser that
        already holds an active participant cookie for this study (e.g.
        testing both roles of a multiplayer cohort solo, second code in a
        second tab) must not silently resume the first participant. That
        used to happen because _start_or_resume only checked
        `participant.study_id`/`status`, never whether the newly-submitted
        code was the one that created the cookied participant — so the
        second code's `uses` never incremented, no second Participant was
        ever created, and the cohort sat permanently short of
        `participants_required`, reporting "waiting for the other
        participant" forever."""
        async with studio_db():
            from studio.models import Code, Participant
            # Random suffix, not a fixed one: _attach_to_session's multiplayer
            # path deliberately joins ANY open lobby for the study that still
            # has room (so two independently-minted codes converge without
            # requiring a cohort mint) — a fixed slug would let a leftover
            # lobby session from a PREVIOUS run of this same test (same study
            # doc, reused by slug) absorb this run's join too, inflating the
            # session's participant count for reasons that have nothing to do
            # with whether this fix actually blocked the second code.
            study = await _register_study(studies_root, dir_name="podium-multiplayer", slug_suffix=f"-mp-409-{secrets.token_hex(4)}")
            code_a = await _mint_code(study, role="analyst")
            code_b = await _mint_code(study, role="observer")

            r1 = await client.post("/api/join", json={"code": code_a.code})
            assert r1.status_code == 200
            assert "studio_participant" in r1.cookies

            # Same client => same cookie jar => same browser, per the bug report.
            r2 = await client.post("/api/join", json={"code": code_b.code})
            assert r2.status_code == 409
            assert "different browser" in r2.json()["error"] or "incognito" in r2.json()["error"]

            code_b_fresh = await Code.get(code_b.id)
            assert code_b_fresh.uses == 0, "the second code must not be silently consumed"

            # Scoped to the ONE session this test created, not the whole
            # study — the study doc (and its participants) persist across
            # pytest runs against the same DB via _register_study's
            # find-or-create-by-slug, so a whole-study count would
            # accumulate across reruns instead of reflecting this run alone.
            joined = await Participant.get(r1.cookies["studio_participant"])
            n_in_session = await Participant.find(Participant.session_id == joined.session_id).count()
            assert n_in_session == 1, "no second participant should have been created in this session"

    async def test_multiplayer_same_code_resume_still_works(self, client, studies_root):
        """The fix for the above must not break the legitimate case: the SAME
        code re-entered on the same browser (refresh, reopen the tab) still
        resumes the same participant instead of erroring."""
        async with studio_db():
            study = await _register_study(studies_root, dir_name="podium-multiplayer", slug_suffix=f"-mp-resume-{secrets.token_hex(4)}")
            code = await _mint_code(study, role="analyst")
            r1 = await client.post("/api/join", json={"code": code.code})
            assert r1.status_code == 200
            r2 = await client.post("/api/join", json={"code": code.code})
            assert r2.status_code == 200
            assert r2.json()["next"] == "/p/consent"

    async def test_missing_body_field_defaults_to_empty_code(self, client, studies_root):
        """JoinRequest.code defaults to "" -- an empty JSON body is valid
        input (422 would be wrong here), just an invalid code (400)."""
        async with studio_db():
            await _register_study(studies_root, slug_suffix="-join-empty")
            r = await client.post("/api/join", json={})
            assert r.status_code == 400


class TestConsentAndTaskFlow:
    async def test_full_singleplayer_join_to_task_flow(self, client, studies_root):
        async with studio_db():
            study = await _register_study(studies_root, slug_suffix="-flow")
            code = await _mint_code(study)
            join = await client.post("/api/join", json={"code": code.code})
            assert join.status_code == 200
            assert join.json()["next"] == "/p/consent"

            consent_page = await client.get("/api/p/consent")
            assert consent_page.status_code == 200
            assert consent_page.json()["participant"] is not None

            consent_submit = await client.post("/api/p/consent")
            assert consent_submit.status_code == 200
            assert consent_submit.json()["next"] == "/p/task"

            task = await client.get("/api/p/task")
            assert task.status_code == 200
            body = task.json()
            assert body["task"] is not None
            assert body["task_index"] == 0

    async def test_consent_page_without_cookie_returns_next_root(self, client, studies_root):
        async with studio_db():
            await _register_study(studies_root, slug_suffix="-noconsent")
            r = await client.get("/api/p/consent")
            assert r.status_code == 200
            assert r.json()["next"] == "/"
            assert r.json()["participant"] is None


class TestProlificRecruitment:
    """PID capture + completion round-trip for recruitment platforms."""

    async def test_join_captures_prolific_pid_and_recruitment_params(self, client, studies_root):
        async with studio_db():
            from studio.models import Participant
            study = await _register_study(studies_root, slug_suffix="-prolific-capture")
            code = await _mint_code(study)
            r = await client.post(
                "/api/join?PROLIFIC_PID=PIDX123&STUDY_ID=STY9&SESSION_ID=SES7",
                json={"code": code.code},
            )
            assert r.status_code == 200
            from beanie import PydanticObjectId
            p = await Participant.get(PydanticObjectId(r.cookies["studio_participant"]))
            assert p.external_id == "PIDX123"
            assert p.recruitment == {
                "PROLIFIC_PID": "PIDX123", "STUDY_ID": "STY9", "SESSION_ID": "SES7",
            }

    async def test_resume_backfills_pid_when_first_join_lacked_it(self, client, studies_root):
        async with studio_db():
            from beanie import PydanticObjectId
            from studio.models import Participant
            study = await _register_study(studies_root, slug_suffix="-prolific-backfill")
            code = await _mint_code(study)
            r1 = await client.post("/api/join", json={"code": code.code})
            pid = r1.cookies["studio_participant"]
            # Re-entry through the platform link — same cookie, now with a PID.
            r2 = await client.post(
                "/api/join?PROLIFIC_PID=LATEPID", json={"code": code.code},
            )
            assert r2.status_code == 200
            p = await Participant.get(PydanticObjectId(pid))
            assert p.external_id == "LATEPID"

    async def test_finished_pid_reentry_lands_on_finish_not_a_second_run(self, client, studies_root):
        async with studio_db():
            from beanie import PydanticObjectId
            from studio.models import Participant
            study = await _register_study(studies_root, slug_suffix="-prolific-dup")
            # _register_study reuses the study doc by slug — drop leftover
            # participants from a previous run so the count below is exact.
            await Participant.find(Participant.study_id == study.id).delete()
            code = await _mint_code(study)
            r1 = await client.post(
                "/api/join?PROLIFIC_PID=DONEPID", json={"code": code.code},
            )
            first_id = r1.cookies["studio_participant"]
            p = await Participant.get(PydanticObjectId(first_id))
            p.status = "finished"
            await p.save()
            # Fresh browser (no cookie), same Prolific participant re-clicks the link.
            client.cookies.clear()
            r2 = await client.post(
                "/api/join?PROLIFIC_PID=DONEPID", json={"code": code.code},
            )
            assert r2.status_code == 200
            assert r2.json()["next"] == "/p/finish"
            # Re-attached to the SAME participant — no duplicate run created.
            assert r2.cookies["studio_participant"] == first_id
            n = await Participant.find(Participant.study_id == study.id).count()
            assert n == 1

    async def test_finish_returns_redirect_with_code_filled_in(self, client, studies_root):
        async with studio_db():
            from beanie import PydanticObjectId
            from studio.models import Participant, Study
            study = await _register_study(studies_root, slug_suffix="-prolific-finish")
            study.completion_code = "CC-42"
            study.completion_redirect_url = (
                "https://app.prolific.com/submissions/complete?cc={completion_code}"
            )
            await study.save()
            code = await _mint_code(study)
            r = await client.post("/api/join?PROLIFIC_PID=FINPID", json={"code": code.code})
            p = await Participant.get(PydanticObjectId(r.cookies["studio_participant"]))
            p.status = "finished"
            await p.save()
            fin = await client.get("/api/p/finish")
            assert fin.status_code == 200
            body = fin.json()
            assert body["external_redirect"] == (
                "https://app.prolific.com/submissions/complete?cc=CC-42"
            )
            # The code also ships standalone so the page can display it as a
            # fallback if the top-level redirect is blocked.
            assert body["completion_code"] == "CC-42"

    async def test_finish_without_redirect_still_ships_completion_code(self, client, studies_root):
        async with studio_db():
            from beanie import PydanticObjectId
            from studio.models import Participant
            study = await _register_study(studies_root, slug_suffix="-prolific-codeonly")
            study.completion_code = "TEXT-ONLY-7"
            study.completion_redirect_url = None
            await study.save()
            code = await _mint_code(study)
            r = await client.post("/api/join", json={"code": code.code})
            p = await Participant.get(PydanticObjectId(r.cookies["studio_participant"]))
            p.status = "finished"
            await p.save()
            fin = await client.get("/api/p/finish")
            body = fin.json()
            assert body.get("external_redirect") is None
            assert body["completion_code"] == "TEXT-ONLY-7"


class TestTaskStepsAndVaEvent:
    async def test_check_step_without_active_task_returns_401(self, client):
        r = await client.post("/api/p/task/check_step", json={"step_id": "x"})
        assert r.status_code == 401

    async def test_check_step_missing_step_id_returns_422(self, client):
        r = await client.post("/api/p/task/check_step", json={})
        assert r.status_code == 422

    async def test_va_event_without_active_task_returns_401(self, client):
        r = await client.post("/api/p/va/event", json={"type": "click"})
        assert r.status_code == 401

    async def test_task_steps_state_without_participant_returns_empty(self, client):
        r = await client.get("/api/p/task/steps")
        assert r.status_code == 200
        assert r.json() == {"task_id": None, "checked": []}


class TestWizardValidation:
    async def test_agent_write_without_participant_returns_401(self, client):
        r = await client.post("/api/p/wizard/agent_write", json={"key": "x"})
        assert r.status_code == 401

    async def test_agent_write_missing_key_returns_422(self, client):
        r = await client.post("/api/p/wizard/agent_write", json={})
        assert r.status_code == 422

    async def test_agent_say_missing_text_returns_422(self, client):
        r = await client.post("/api/p/wizard/agent_say", json={})
        assert r.status_code == 422

    async def test_peers_without_participant_returns_401(self, client):
        r = await client.get("/api/p/wizard/peers")
        assert r.status_code == 401


class TestPreflight:
    async def test_unknown_code_reports_invalid(self, client):
        async with studio_db():
            r = await client.get("/api/p/preflight/NOSUCHCODE")
            assert r.status_code == 200
            body = r.json()
            assert body["valid_code"] is False
            assert body["study"] is None

    async def test_known_code_reports_valid(self, client, studies_root):
        async with studio_db():
            study = await _register_study(studies_root, slug_suffix="-preflight")
            code = await _mint_code(study)
            r = await client.get(f"/api/p/preflight/{code.code}")
            assert r.status_code == 200
            body = r.json()
            assert body["valid_code"] is True
            assert body["study"]["slug"] == study.slug
