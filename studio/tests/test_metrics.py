"""Unit tests for the declarative metrics engine."""
from __future__ import annotations

from studio.metrics import compute_metrics


def _ev(t_ms, type="user_action", source="mivais", task_id=None, **meta):
    return {"type": type, "source": source, "t_ms": t_ms, "task_id": task_id, "meta": meta}


EVENTS = [
    _ev(0, type="task_start", source="studio", task_id="explore"),
    _ev(2000, action="select_hexagon", task_id="explore"),
    _ev(5000, action="accept_suggestion", task_id="explore"),
    _ev(9000, action="reject_suggestion", task_id="explore"),
    _ev(12000, action="reject_suggestion", task_id="explore"),
    _ev(60000, type="task_end", source="studio", task_id="explore"),
    _ev(61000, type="task_start", source="studio", task_id="quiz"),
    _ev(64000, action="select_hexagon", task_id="quiz"),
    _ev(90000, type="task_end", source="studio", task_id="quiz"),
]


class TestKinds:
    def test_count(self):
        [r] = compute_metrics(
            [{"id": "c", "kind": "count",
              "match": {"event_type": "user_action", "meta": {"action": "select_hexagon"}}}],
            EVENTS,
        )
        assert r["value"] == 2.0 and r["n"] == 2

    def test_count_scoped_to_task(self):
        [r] = compute_metrics(
            [{"id": "c", "kind": "count", "task": "quiz",
              "match": {"event_type": "user_action", "meta": {"action": "select_hexagon"}}}],
            EVENTS,
        )
        assert r["value"] == 1.0

    def test_rate_uses_scope_duration(self):
        # 5 user_actions across the 90s session -> 5 / 1.5min
        [r] = compute_metrics(
            [{"id": "r", "kind": "rate", "match": {"event_type": "user_action"}}],
            EVENTS,
        )
        assert abs(r["value"] - 5 / 1.5) < 0.01
        assert r["unit"] == "events/min"

    def test_latency_pairs_from_to(self):
        # task_start(0) -> first user_action(2000) = 2s; task_start(61000) -> 64000 = 3s
        [r] = compute_metrics(
            [{"id": "l", "kind": "latency",
              "from": {"event_type": "task_start", "source": "studio"},
              "to": {"event_type": "user_action"},
              "aggregate": "median"}],
            EVENTS,
        )
        assert r["value"] == 2.5 and r["n"] == 2 and r["unit"] == "s"

    def test_latency_first_only(self):
        [r] = compute_metrics(
            [{"id": "l", "kind": "latency", "first_only": True,
              "from": {"event_type": "task_start", "source": "studio"},
              "to": {"event_type": "user_action"}}],
            EVENTS,
        )
        assert r["value"] == 2.0 and r["n"] == 1

    def test_ratio_share(self):
        # 1 accepted, 2 rejected -> 1/3
        [r] = compute_metrics(
            [{"id": "a", "kind": "ratio",
              "numerator": {"event_type": "user_action", "meta": {"action": "accept_suggestion"}},
              "denominator": {"event_type": "user_action", "meta": {"action": "reject_suggestion"}}}],
            EVENTS,
        )
        assert abs(r["value"] - 1 / 3) < 0.001
        assert r["detail"] == {"numerator": 1, "denominator": 2}

    def test_no_matches_yields_none_not_crash(self):
        [r] = compute_metrics(
            [{"id": "x", "kind": "latency",
              "from": {"event_type": "never"}, "to": {"event_type": "user_action"}}],
            EVENTS,
        )
        assert r["value"] is None and r["n"] == 0

    def test_python_hook(self):
        [r] = compute_metrics(
            [{"id": "idle", "kind": "python",
              "module": "studio.metrics.custom.example_idle_share:compute",
              "params": {"threshold_s": 10}}],
            EVENTS,
        )
        # gaps > 10s: 12000->60000 (48s), 64000->90000 (26s), total 90s window
        assert r["value"] == round((48000 + 26000) / 90000, 3)

    def test_python_hook_outside_namespace_refused(self):
        [r] = compute_metrics(
            [{"id": "evil", "kind": "python", "module": "os.path:join"}],
            EVENTS,
        )
        assert r["value"] is None and "custom" in r["detail"]["error"]


class TestSchema:
    def test_metric_config_validates_and_dumps_alias(self):
        from studio.config.schemas import MetricConfig
        m = MetricConfig.model_validate({
            "id": "l", "kind": "latency",
            "from": {"event_type": "task_start"},
            "to": {"event_type": "user_action"},
        })
        d = m.engine_dict()
        assert "from" in d and "from_" not in d

    def test_metric_config_missing_fields_rejected(self):
        import pytest
        from studio.config.schemas import MetricConfig
        with pytest.raises(Exception, match="missing: from"):
            MetricConfig.model_validate({"id": "l", "kind": "latency", "to": {"event_type": "x"}})

    def test_demo_proactiveva_metrics_load(self):
        from pathlib import Path
        from studio.config.loader import load_study_dir
        root = Path(__file__).resolve().parent.parent / "studies" / "demo-proactiveva"
        cfg = load_study_dir(root)[0]
        assert {m.id for m in cfg.metrics} == {
            "time_to_first_action", "suggestion_acceptance", "interaction_rate", "notes_added",
        }
