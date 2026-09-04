"""Mongo-backed integration tests. Auto-skip when Mongo isn't reachable
(see ``conftest.py`` — gated on the ``mongo`` marker).

Each test brings its own DB connection up and tears it down so they don't
trip pytest-asyncio's "Future attached to a different loop" check.
"""
from __future__ import annotations

import contextlib
import pytest

pytestmark = pytest.mark.mongo


@contextlib.asynccontextmanager
async def studio_db():
    """Open the same DB connection the FastAPI lifespan would, scoped to one test."""
    from studio import db
    await db.connect()
    try:
        yield
    finally:
        await db.disconnect()


async def _ensure_smoke_registered(studies_root):
    """Register-or-update podium-smoke so the synthetic bot has an up-to-date
    Study doc — including any task that's been added to the YAML since the
    Mongo doc was first written.
    """
    from studio.config.loader import load_study_dir
    from studio.models import Study

    cfg, _manifest, digest = load_study_dir(studies_root / "podium-smoke")
    s = await Study.find_one(Study.slug == cfg.id)
    if s is None:
        s = Study(slug=cfg.id, name=cfg.name, study_dir="podium-smoke")
    s.name = cfg.name
    s.mode = cfg.mode
    s.consent_text_md = cfg.consent_text_md
    s.va_systems = {k: v.model_dump() for k, v in cfg.va_systems.items()}
    s.primary_va_system = cfg.primary_va_system
    s.roles = [r.model_dump() for r in cfg.roles]
    s.advance_policy = cfg.advance_policy
    s.block_order = cfg.block_order
    s.block_orders = list(cfg.block_orders or [])
    s.parameters = dict(cfg.parameters or {})
    s.recording = cfg.recording.model_dump()
    s.ui = cfg.ui.model_dump()
    s.blocks = [block.model_dump() for block in cfg.blocks]
    s.yaml_hash = digest
    await s.save()
    return s


class TestSyntheticBot:
    async def test_one_ghost_walks_a_study(self, studies_root):
        from studio import qa
        from studio.models import Event, Participant, Session
        async with studio_db():
            await _ensure_smoke_registered(studies_root)
            result = await qa.run_many(slug="podium-smoke", n=1, seed=1234)
            assert result["n"] == 1
            info = result["runs"][0]
            session = await Session.get(info["session_id"])
            assert session is not None
            participant = await Participant.get(info["participant_id"])
            assert participant is not None
            # The bot either finishes or drops on the attention check.
            assert participant.status in ("finished", "dropped")
            # Studio events were recorded.
            n_events = await Event.find(Event.session_id == session.id).count()
            assert n_events >= 1
            synth_events = await Event.find(
                Event.session_id == session.id, Event.type == "synthetic_participant",
            ).to_list()
            assert len(synth_events) == 1
            assert synth_events[0].meta.get("label") == "ghost-0"

    async def test_seed_keeps_task_order_stable(self, studies_root):
        from studio import qa
        from studio.models import Participant
        async with studio_db():
            await _ensure_smoke_registered(studies_root)
            r1 = await qa.run_many(slug="podium-smoke", n=1, seed=42)
            r2 = await qa.run_many(slug="podium-smoke", n=1, seed=42)
            p1 = await Participant.get(r1["runs"][0]["participant_id"])
            p2 = await Participant.get(r2["runs"][0]["participant_id"])
            # block_order=declared on podium-smoke → both must visit the same path.
            assert p1.applied_task_order == p2.applied_task_order
            # Both should include the attention check (which then drops the bot
            # or not depending on the canned answer for single_choice).
            assert "attention-check" in p1.applied_task_order

    async def test_ghosts_tagged_for_filtering(self, studies_root):
        """Ghosts are flagged with a `synthetic_participant` Studio event so
        downstream analytics can exclude them. Verifies the meta payload."""
        from studio import qa
        from studio.models import Event
        async with studio_db():
            await _ensure_smoke_registered(studies_root)
            await qa.run_many(slug="podium-smoke", n=2, seed=7)
            events = await Event.find(Event.type == "synthetic_participant").to_list()
            assert len(events) >= 2
            labels = {e.meta.get("label") for e in events}
            # Each run produces a `ghost-<i>` label.
            assert any(label and label.startswith("ghost-") for label in labels)
