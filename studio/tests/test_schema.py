"""Tests for studio.config.schemas + studio.config.loader.

Loads the bundled demo studies end-to-end through the real loader (including
``$ref`` resolution), and checks several validator paths in isolation.
"""
from __future__ import annotations

import pytest

from studio.config.loader import StudyLoadError, load_study_dir
from studio.config.schemas import StudyConfig


# ── Demo-study fixtures ─────────────────────────────────────────────────

class TestDemoStudies:
    def test_podium_smoke_loads(self, smoke_study_cfg):
        cfg = smoke_study_cfg
        assert cfg.id == "podium-smoke"
        assert cfg.mode == "singleplayer"
        # 11 tasks: welcome + attention-check + 6 exercise tasks + reflection + nasa-tlx + thanks
        total = sum(len(b.tasks) for b in cfg.blocks)
        assert total == 11

    def test_podium_smoke_resolves_refs(self, smoke_study_cfg):
        # The intro block pulls in attention-check via $ref. After resolution
        # the task should be a full TaskBase, not a $ref placeholder.
        tasks_by_id = {t.id: t for b in smoke_study_cfg.blocks for t in b.tasks}
        assert "attention-check" in tasks_by_id
        assert tasks_by_id["attention-check"].type == "single_choice"
        # The branch rule survived the load.
        rules = tasks_by_id["attention-check"].next or []
        assert any((r.goto.action == "drop") for r in rules)

    def test_podium_smoke_parameters(self, smoke_study_cfg):
        assert smoke_study_cfg.parameters.get("dataset_name") == "cars"
        assert "study_duration" in smoke_study_cfg.parameters

    def test_podium_multiplayer_loads(self, multiplayer_study_cfg):
        cfg = multiplayer_study_cfg
        assert cfg.mode == "multiplayer"
        assert cfg.participants_required == 2
        # Two roles, two distinct agent_ids.
        role_ids = {r.id for r in cfg.roles}
        assert role_ids == {"analyst", "observer"}

    def test_va_shorthand_promotes_to_va_systems(self, smoke_study_cfg):
        # podium-smoke uses the legacy `va:` field — the loader must promote
        # it into `va_systems = {default: ...}`.
        assert "default" in smoke_study_cfg.va_systems
        assert smoke_study_cfg.primary_va_system == "default"


# ── Validator negative cases ────────────────────────────────────────────

class TestValidators:
    def _study(self, **overrides):
        base = {
            "id": "x", "name": "X", "mode": "singleplayer",
            "blocks": [{"id": "b", "tasks": []}],
        }
        base.update(overrides)
        return base

    def test_multiple_va_systems_requires_primary(self):
        with pytest.raises(Exception):
            StudyConfig.model_validate(self._study(
                va_systems={
                    "a": {"system": "a", "spawn_cmd": "a {port}",
                          "iframe_url": "http://x/{port}/"},
                    "b": {"system": "b", "spawn_cmd": "b {port}",
                          "iframe_url": "http://x/{port}/"},
                },
            ))

    def test_unknown_primary_va_system_rejected(self):
        with pytest.raises(Exception):
            StudyConfig.model_validate(self._study(
                va_systems={"a": {"system": "a", "spawn_cmd": "a {port}",
                                  "iframe_url": "http://x/{port}/"}},
                primary_va_system="b",
            ))

    def test_task_referencing_unknown_va_system_rejected(self):
        with pytest.raises(Exception):
            StudyConfig.model_validate(self._study(
                va_systems={"a": {"system": "a", "spawn_cmd": "a {port}",
                                  "iframe_url": "http://x/{port}/"}},
                primary_va_system="a",
                blocks=[{"id": "b", "tasks": [
                    {"id": "t", "type": "va_interaction", "va_system": "nope"},
                ]}],
            ))

    def test_va_interaction_without_any_va_rejected(self):
        with pytest.raises(Exception):
            StudyConfig.model_validate(self._study(
                blocks=[{"id": "b", "tasks": [
                    {"id": "t", "type": "va_interaction"},
                ]}],
            ))

    def test_multiplayer_branching_rejected(self):
        # `next:` rules in multiplayer would split the cohort; the validator
        # refuses them up front rather than ship undefined behaviour.
        with pytest.raises(Exception):
            StudyConfig.model_validate(self._study(
                mode="multiplayer",
                participants_required=2,
                blocks=[{"id": "b", "tasks": [
                    {"id": "t", "type": "single_choice", "options": [],
                     "next": [{"when": "default", "goto": {"action": "drop"}}]},
                ]}],
            ))

    def test_va_compose_or_spawn_cmd_required(self):
        # A VAConfig with neither spawn_cmd nor compose is invalid.
        with pytest.raises(Exception):
            StudyConfig.model_validate(self._study(
                va_systems={"a": {"system": "a", "iframe_url": "http://x/{port}/"}},
                primary_va_system="a",
            ))

    def test_completion_redirect_url_prolific_shorthand_expands(self):
        cfg = StudyConfig.model_validate(self._study(
            completion_redirect_url="prolific",
            completion_code="ABC123",
        ))
        assert cfg.completion_redirect_url == (
            "https://app.prolific.com/submissions/complete?cc={completion_code}"
        )

    def test_completion_redirect_url_custom_url_untouched(self):
        url = "https://example.com/done?c={completion_code}&p={external_id}"
        cfg = StudyConfig.model_validate(self._study(completion_redirect_url=url))
        assert cfg.completion_redirect_url == url


# ── $ref path safety ────────────────────────────────────────────────────

class TestRefSafety:
    def test_ref_outside_studies_root_is_refused(self, tmp_path):
        # Set up a fake studies_dir with one study whose YAML references
        # a file outside the studies_root via ``../../etc-style`` traversal.
        studies = tmp_path / "studies"
        study_dir = studies / "evil"
        tasks = study_dir / "tasks"
        tasks.mkdir(parents=True)
        (study_dir / "study.yaml").write_text(
            "id: evil\nname: Evil\nmode: singleplayer\n"
            "blocks:\n  - id: b\n    tasks:\n      - $ref: ../../../escape.yaml\n"
        )
        # Even creating the escape file shouldn't matter — the loader rejects
        # the path before reading it.
        (tmp_path / "escape.yaml").write_text("id: x\ntype: info_screen\n")
        with pytest.raises(StudyLoadError):
            load_study_dir(study_dir)

    def test_unknown_task_id_gives_clear_error(self, tmp_path):
        study_dir = tmp_path / "broken"
        tasks = study_dir / "tasks"
        tasks.mkdir(parents=True)
        (study_dir / "study.yaml").write_text(
            "id: broken\nname: Broken\nmode: singleplayer\n"
            "blocks:\n  - id: b\n    tasks:\n      - nonexistent\n"
        )
        with pytest.raises(StudyLoadError, match="nonexistent"):
            load_study_dir(study_dir)
