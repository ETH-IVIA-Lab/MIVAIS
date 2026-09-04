"""Regression coverage for session_manager.try_advance_session's
advance.policy: "admin" + timeout_seconds path.

Root cause this covers: a task with `advance: {policy: admin, timeout_seconds:
N}` is documented (every such task.yaml in this repo is commented "…or it
auto-advances after N seconds") to fall back to an automatic advance if the
researcher doesn't click "advance now" in time. Nothing ever evaluated
timeout_seconds — try_advance_session's `admin` branch unconditionally
returned False without `force=True` — so once every participant in a cohort
had submitted, the session hung at that task_index forever: both
participants sit on "waiting for the rest of the cohort" and nothing ever
calls try_advance_session again (task_submit won't fire twice; a researcher
who doesn't notice the live view never hits the force-advance route).
"""
from __future__ import annotations

import contextlib
import secrets
from datetime import timedelta

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


async def _make_cohort(n_participants: int = 2, timeout_seconds: int | None = 1):
    """A running 2-participant multiplayer session, one task, policy=admin."""
    from studio.models import Participant, Session, Study
    from studio.orchestrator.session_manager import _utcnow

    study = Study(
        slug=f"advance-admin-timeout-{secrets.token_hex(6)}",
        name="Advance-policy test",
        mode="multiplayer",
        participants_required=n_participants,
        blocks=[{
            "id": "b",
            "tasks": [{
                "id": "t1",
                "type": "info_screen",
                "advance": {"policy": "admin", "timeout_seconds": timeout_seconds},
            }],
        }],
    )
    await study.insert()

    session = Session(study_id=study.id, mode="multiplayer", status="running", current_task_index=0)
    await session.insert()

    participants = []
    for i in range(n_participants):
        p = Participant(
            session_id=session.id, study_id=study.id, anon_id=f"p_test_{secrets.token_hex(6)}",
            status="in_session",
            task_runs=[{
                "task_id": "t1", "task_index": 0,
                "started_at": _utcnow(), "ended_at": _utcnow(),
            }],
        )
        await p.insert()
        participants.append(p)

    return study, session, participants


class TestAdvancePolicyAdminTimeout:
    async def test_does_not_advance_before_timeout_elapses(self):
        async with studio_db():
            from studio.orchestrator import session_manager
            _study, session, _participants = await _make_cohort(timeout_seconds=120)
            advanced = await session_manager.try_advance_session(session)
            assert advanced is False
            assert session.current_task_index == 0

    async def test_auto_advances_once_timeout_elapses_with_everyone_submitted(self):
        """The bug: this used to return False forever, no matter how much
        (real or simulated) time passed, because the `admin` branch never
        looked at timeout_seconds at all."""
        async with studio_db():
            from studio.orchestrator import session_manager
            study, session, participants = await _make_cohort(timeout_seconds=1)

            # Not yet — the backdated ended_at hasn't been written.
            assert await session_manager.try_advance_session(session) is False

            # Simulate the timeout having elapsed: backdate both submissions.
            from studio.orchestrator.session_manager import _utcnow
            for p in participants:
                p.task_runs[-1].ended_at = _utcnow() - timedelta(seconds=5)
                await p.save()

            advanced = await session_manager.try_advance_session(session)
            assert advanced is True
            assert session.current_task_index == 1

    async def test_does_not_advance_until_every_participant_has_submitted(self):
        """The timeout is a safety net for "admin hasn't clicked", not a way
        to advance while the cohort is still genuinely mid-task — it must
        never fire while somebody hasn't submitted yet, no matter how old the
        other person's submission is."""
        async with studio_db():
            from studio.orchestrator import session_manager
            from studio.orchestrator.session_manager import _utcnow
            study, session, participants = await _make_cohort(n_participants=2, timeout_seconds=1)
            # Only participant 0 has actually finished; backdate ONLY theirs.
            participants[0].task_runs[-1].ended_at = _utcnow() - timedelta(seconds=10)
            await participants[0].save()
            participants[1].task_runs = []  # never started/finished task 0
            await participants[1].save()

            advanced = await session_manager.try_advance_session(session)
            assert advanced is False
            assert session.current_task_index == 0

    async def test_no_timeout_configured_still_requires_force(self):
        """A plain `policy: admin` with no timeout_seconds must keep its
        original behavior — never auto-advances, only force=True does."""
        async with studio_db():
            from studio.orchestrator import session_manager
            from studio.orchestrator.session_manager import _utcnow
            study, session, participants = await _make_cohort(timeout_seconds=None)
            for p in participants:
                p.task_runs[-1].ended_at = _utcnow() - timedelta(days=1)
                await p.save()
            assert await session_manager.try_advance_session(session) is False
            assert await session_manager.try_advance_session(session, force=True) is True
            assert session.current_task_index == 1


class TestSecondsUntilAutoAdvance:
    """The countdown shown on the "waiting for the cohort" banner — added
    because the fix above, on its own, still LOOKS exactly like "stuck
    forever" for however long timeout_seconds is: no code path told the
    waiting participant that a timer was even running."""

    async def test_none_when_not_everyone_has_submitted(self):
        async with studio_db():
            from studio.orchestrator import session_manager
            _study, session, participants = await _make_cohort(n_participants=2, timeout_seconds=120)
            participants[1].task_runs = []
            await participants[1].save()
            assert await session_manager.seconds_until_auto_advance(session) is None

    async def test_none_when_no_timeout_configured(self):
        async with studio_db():
            from studio.orchestrator import session_manager
            _study, session, _participants = await _make_cohort(timeout_seconds=None)
            assert await session_manager.seconds_until_auto_advance(session) is None

    async def test_counts_down_from_the_last_participants_submit_time(self):
        async with studio_db():
            from studio.orchestrator import session_manager
            from studio.orchestrator.session_manager import _utcnow
            _study, session, participants = await _make_cohort(timeout_seconds=120)
            # Both "submitted" at _make_cohort time (~now); back one of them up
            # by 20s so the wait clock starts from the LATER of the two.
            participants[0].task_runs[-1].ended_at = _utcnow() - timedelta(seconds=20)
            await participants[0].save()

            eta = await session_manager.seconds_until_auto_advance(session)
            assert eta is not None
            # ~120s left (waiting_since = participants[1]'s ~now submit), not
            # ~100s (which would mean it wrongly used the EARLIER submit).
            assert 110 <= eta <= 120

    async def test_floors_at_zero_never_goes_negative(self):
        async with studio_db():
            from studio.orchestrator import session_manager
            from studio.orchestrator.session_manager import _utcnow
            _study, session, participants = await _make_cohort(timeout_seconds=1)
            for p in participants:
                p.task_runs[-1].ended_at = _utcnow() - timedelta(seconds=999)
                await p.save()
            eta = await session_manager.seconds_until_auto_advance(session)
            assert eta == 0


class TestParticipantStatePollTriggersAdvance:
    """The other half of the fix: participant_state (/api/p/state, polled
    every few seconds by a waiting participant's client) must itself call
    try_advance_session — otherwise the timeout logic above is correct but
    unreachable in practice, since nothing else re-invokes it once everyone
    has already submitted and stopped POSTing anything."""

    async def test_state_poll_advances_session_past_elapsed_admin_timeout(self, studies_root):
        async with studio_db():
            from datetime import timedelta as _td
            from httpx import ASGITransport, AsyncClient
            from studio.main import app
            from studio.models import Session
            from studio.orchestrator.session_manager import _utcnow

            study, session, participants = await _make_cohort(timeout_seconds=1)
            for p in participants:
                p.task_runs[-1].ended_at = _utcnow() - _td(seconds=5)
                await p.save()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                client.cookies.set("studio_participant", str(participants[0].id))
                r = await client.get("/api/p/state")
                assert r.status_code == 200
                assert r.json()["session_task_index"] == 1

            fresh = await Session.get(session.id)
            assert fresh.current_task_index == 1
