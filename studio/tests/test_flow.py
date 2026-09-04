"""Tests for studio.orchestrator.flow — the expression DSL, counterbalancing,
role/language overrides, branching resolution, and variable substitution.

These are pure-Python and don't need Mongo.
"""
from __future__ import annotations

import pytest

from studio.orchestrator import flow
from studio.orchestrator.flow import UnsafeExpression


# ── expression DSL ──────────────────────────────────────────────────────

class TestExpressionDSL:
    def test_equality(self):
        assert flow.evaluate_condition("answer == 'red'", answer="red") is True
        assert flow.evaluate_condition("answer == 'red'", answer="green") is False

    def test_inequality_and_comparisons(self):
        assert flow.evaluate_condition("answer != 'red'", answer="green") is True
        assert flow.evaluate_condition("score < 0.5", score=0.3) is True
        assert flow.evaluate_condition("score >= 0.5", score=0.5) is True

    def test_attribute_access_on_dict_answer(self):
        assert flow.evaluate_condition(
            "answer.id == 'civic'", answer={"id": "civic"},
        ) is True

    def test_subscript_access_on_dict_answer(self):
        # ``answer['id']`` works too.
        assert flow.evaluate_condition(
            "answer['id'] == 'civic'", answer={"id": "civic"},
        ) is True

    def test_in_and_not_in(self):
        assert flow.evaluate_condition("answer in ['a','b']", answer="a") is True
        assert flow.evaluate_condition("answer not in ['a','b']", answer="c") is True

    def test_boolean_logic(self):
        assert flow.evaluate_condition(
            "correct and score > 0.7", correct=True, score=0.8,
        ) is True
        assert flow.evaluate_condition(
            "correct or score > 0.9", correct=False, score=0.5,
        ) is False

    def test_unary_not(self):
        assert flow.evaluate_condition("not correct", correct=False) is True

    def test_params_access(self):
        assert flow.evaluate_condition(
            "params.difficulty == 'hard'", params={"difficulty": "hard"},
        ) is True

    def test_default_keyword_always_true(self):
        assert flow.evaluate_condition("default") is True
        assert flow.evaluate_condition("DEFAULT") is True

    def test_empty_or_none_expression_is_false(self):
        assert flow.evaluate_condition("") is False
        assert flow.evaluate_condition(None) is False  # type: ignore[arg-type]

    @pytest.mark.parametrize("expr", [
        "__import__('os').system('x')",
        "open('etc/passwd')",
        "lambda x: x",
        "answer if 1 else 2",          # ternary
        "answer.__class__",            # dunder
        "[x for x in range(3)]",       # comprehension
        "yield 1",                     # statement
    ])
    def test_rejects_unsafe_expressions(self, expr):
        with pytest.raises(UnsafeExpression):
            flow.evaluate_condition(expr, answer="x")

    def test_unknown_name_rejected(self):
        with pytest.raises(UnsafeExpression):
            flow.evaluate_condition("os == 'x'", answer="x")


# ── counterbalancing ────────────────────────────────────────────────────

class TestCounterbalancing:
    blocks = [
        {"id": "b1", "tasks": [{"id": "t1"}, {"id": "t2"}]},
        {"id": "b2", "tasks": [{"id": "t3"}]},
        {"id": "b3", "tasks": [{"id": "t4"}, {"id": "t5"}]},
    ]

    def test_declared_is_stable(self):
        order, tasks, seed = flow.build_block_order(
            blocks=self.blocks, strategy="declared",
            declared_orderings=None, participant_rank=0, seed=None,
        )
        assert order == ["b1", "b2", "b3"]
        assert tasks == ["t1", "t2", "t3", "t4", "t5"]
        assert seed is None

    def test_random_records_seed(self):
        _order, _tasks, seed = flow.build_block_order(
            blocks=self.blocks, strategy="random",
            declared_orderings=None, participant_rank=0, seed=42,
        )
        # Same seed → same order, regardless of participant_rank.
        order2, _, seed2 = flow.build_block_order(
            blocks=self.blocks, strategy="random",
            declared_orderings=None, participant_rank=999, seed=42,
        )
        assert seed == seed2 == 42
        assert _order == order2  # deterministic given the seed

    def test_round_robin_rotates(self):
        rotations = []
        for rank in range(3):
            order, _, _ = flow.build_block_order(
                blocks=self.blocks, strategy="round_robin",
                declared_orderings=None, participant_rank=rank, seed=None,
            )
            rotations.append(tuple(order))
        # Each rank gets a distinct rotation of the declared order.
        assert len(set(rotations)) == 3

    def test_latin_square_distinct_rows(self):
        rows = []
        for rank in range(3):
            order, _, _ = flow.build_block_order(
                blocks=self.blocks, strategy="latin_square",
                declared_orderings=None, participant_rank=rank, seed=None,
            )
            rows.append(tuple(order))
        # Latin square N×N has N distinct orderings.
        assert len(set(rows)) == 3

    def test_declared_orderings_used_verbatim(self):
        explicit = [["b3", "b1", "b2"], ["b1", "b3", "b2"]]
        order, _, _ = flow.build_block_order(
            blocks=self.blocks, strategy="round_robin",
            declared_orderings=explicit, participant_rank=0, seed=None,
        )
        assert order == explicit[0]
        order, _, _ = flow.build_block_order(
            blocks=self.blocks, strategy="round_robin",
            declared_orderings=explicit, participant_rank=1, seed=None,
        )
        assert order == explicit[1]


# ── role / language overrides ───────────────────────────────────────────

class TestRoleOverrides:
    base_task = {
        "id": "t",
        "type": "free_text",
        "prompt_md": "Default prompt",
        "prompt_md_by_role": {
            "wizard": "WIZARD: drive the bot",
            "subject": "SUBJECT: complete the task",
        },
        "world_state": {
            "mode": "continue",
            "set": {"x": 1},
            "by_role": {
                "wizard": {"mode": "continue", "set": {"wizard_canary": True}},
            },
        },
    }

    def test_no_role_returns_unchanged(self):
        out = flow.apply_role_overrides(self.base_task, None)
        assert out["prompt_md"] == "Default prompt"

    def test_role_swaps_prompt(self):
        assert flow.apply_role_overrides(self.base_task, "wizard")["prompt_md"] \
            == "WIZARD: drive the bot"
        assert flow.apply_role_overrides(self.base_task, "subject")["prompt_md"] \
            == "SUBJECT: complete the task"

    def test_unknown_role_falls_back(self):
        out = flow.apply_role_overrides(self.base_task, "observer")
        assert out["prompt_md"] == "Default prompt"

    def test_world_state_swap(self):
        ws = flow.apply_role_overrides(self.base_task, "wizard")["world_state"]
        assert ws == {"mode": "continue", "set": {"wizard_canary": True}}

    def test_info_screen_mirrors_body_md(self):
        task = {"id": "i", "type": "info_screen", "prompt_md_by_role": {"w": "X"}}
        out = flow.apply_role_overrides(task, "w")
        assert out["prompt_md"] == "X"
        assert out["body_md"] == "X"


class TestLanguageOverrides:
    base_task = {
        "id": "t",
        "type": "free_text",
        "prompt_md": "Default English",
        "prompt_md_by_lang": {"de": "Deutsch", "fr": "Français"},
    }

    def test_known_lang(self):
        assert flow.apply_lang_overrides(self.base_task, "de")["prompt_md"] == "Deutsch"

    def test_region_falls_back_to_prefix(self):
        assert flow.apply_lang_overrides(self.base_task, "de-CH")["prompt_md"] == "Deutsch"

    def test_unknown_lang_falls_back(self):
        assert flow.apply_lang_overrides(self.base_task, "ja")["prompt_md"] == "Default English"

    def test_none_lang_returns_unchanged(self):
        assert flow.apply_lang_overrides(self.base_task, None) is self.base_task


class TestResolveLang:
    def test_query_param_wins(self):
        assert flow.resolve_lang("de", "en-US,en", "en") == "de"

    def test_accept_language_first_choice(self):
        assert flow.resolve_lang(None, "fr-FR,fr;q=0.9,en;q=0.5", "en") == "fr-fr"

    def test_default_when_both_empty(self):
        assert flow.resolve_lang(None, None, "en") == "en"

    def test_empty_string_falls_through(self):
        assert flow.resolve_lang("", "", "en") == "en"


# ── variable substitution ──────────────────────────────────────────────

class TestSubstituteParams:
    def test_simple_replacement(self):
        out = flow.substitute_params("Hello {{ params.name }}", {"name": "World"})
        assert out == "Hello World"

    def test_walks_dicts_and_lists(self):
        task = {
            "prompt_md": "Pick from {{ params.dataset }} cars",
            "options": [{"label": "top-{{ params.dataset }}"}],
        }
        out = flow.substitute_params(task, {"dataset": "fast"})
        assert out["prompt_md"] == "Pick from fast cars"
        assert out["options"][0]["label"] == "top-fast"

    def test_missing_key_left_intact(self):
        out = flow.substitute_params("{{ params.missing }}", {"x": 1})
        assert out == "{{ params.missing }}"

    def test_empty_params_passes_through(self):
        out = flow.substitute_params("static text", {})
        assert out == "static text"

    def test_whitespace_tolerance(self):
        out = flow.substitute_params("{{   params.x   }}", {"x": "y"})
        assert out == "y"


# ── resolve_next ────────────────────────────────────────────────────────

class TestResolveNext:
    applied = ["t1", "t2", "t3", "t4", "t5"]
    block_id_by_index = ["b1", "b1", "b2", "b3", "b3"]

    def _call(self, rules, **kw):
        defaults = dict(
            current_index=0, applied_task_order=self.applied,
            block_index_by_task={t: i for i, t in enumerate(self.applied)},
            block_id_by_index=self.block_id_by_index,
            answer=None, score=None, correct=None, role=None, params=None,
        )
        defaults.update(kw)
        return flow.resolve_next(rules, **defaults)

    def test_no_rules_advances_linearly(self):
        assert self._call(None) == {"kind": "next", "index": 1}
        assert self._call([], current_index=2) == {"kind": "next", "index": 3}

    def test_branch_to_specific_task(self):
        rules = [{"when": "answer == 'red'", "goto": {"task": "t4"}}]
        assert self._call(rules, answer="red") == {"kind": "task", "index": 3}

    def test_drop_action(self):
        rules = [{"when": "not correct", "goto": {"action": "drop"}}]
        assert self._call(rules, correct=False) == {"kind": "drop", "index": None}

    def test_skip_block(self):
        rules = [{"when": "default", "goto": {"action": "skip_block"}}]
        assert self._call(rules, current_index=0) == {"kind": "skip_block", "index": None}

    def test_unknown_target_skips_rule(self):
        # A goto.task that doesn't exist in `applied` is skipped; we fall through.
        rules = [
            {"when": "default", "goto": {"task": "nonexistent"}},
        ]
        # No matching rule → linear advance.
        assert self._call(rules) == {"kind": "next", "index": 1}

    def test_broken_expression_skips_rule(self):
        # A rule whose expression is unsafe → silently skipped.
        rules = [
            {"when": "__import__('os')", "goto": {"action": "drop"}},
            {"when": "default", "goto": {"next_task": True}},
        ]
        assert self._call(rules) == {"kind": "next", "index": 1}
