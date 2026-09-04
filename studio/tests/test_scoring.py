"""Tests for studio.orchestrator.scoring — the five ground-truth strategies.

All synchronous + pure-Python, no Mongo.
"""
from __future__ import annotations

import pytest

from studio.orchestrator.scoring import score_answer


class TestNoGroundTruth:
    def test_returns_triple_none(self):
        assert score_answer("anything", None) == (None, None, None)


class TestExact:
    def test_match(self):
        score, correct, details = score_answer("civic", {"type": "exact", "value": "civic"})
        assert score == 1.0
        assert correct is True
        assert details["strategy"] == "exact"

    def test_mismatch(self):
        score, correct, _ = score_answer("accord", {"type": "exact", "value": "civic"})
        assert score == 0.0
        assert correct is False

    def test_works_on_lists_too(self):
        # exact uses == on the raw value.
        score, correct, _ = score_answer([1, 2], {"type": "exact", "value": [1, 2]})
        assert (score, correct) == (1.0, True)


class TestSetMatch:
    def test_perfect_match(self):
        score, correct, details = score_answer(
            ["a", "b"], {"type": "set_match", "value": ["a", "b"]},
        )
        assert score == 1.0
        assert correct is True
        assert details["jaccard"] == 1.0

    def test_partial_match_with_partial_credit(self):
        score, correct, details = score_answer(
            ["a", "b", "c"], {"type": "set_match", "value": ["a", "b"]},
        )
        # Jaccard = 2 / 3
        assert pytest.approx(score, abs=1e-6) == 2 / 3
        assert correct is False  # not exactly 1.0
        assert details["jaccard"] == pytest.approx(2 / 3)

    def test_partial_match_without_partial_credit(self):
        # partial_credit=False → score is 0 unless exact.
        score, correct, _ = score_answer(
            ["a", "b", "c"], {"type": "set_match", "value": ["a", "b"], "partial_credit": False},
        )
        assert score == 0.0
        assert correct is False

    def test_empty_sets_match(self):
        score, correct, _ = score_answer(
            [], {"type": "set_match", "value": []},
        )
        assert (score, correct) == (1.0, True)


class TestOrderedMatch:
    def test_perfect(self):
        score, correct, _ = score_answer(
            [3, 1, 4, 2, 5], {"type": "ordered_match", "value": [3, 1, 4, 2, 5]},
        )
        assert (score, correct) == (1.0, True)

    def test_partial(self):
        # 2 of 5 positions correct → 0.4.
        score, correct, details = score_answer(
            [3, 1, 5, 2, 4], {"type": "ordered_match", "value": [3, 1, 4, 2, 5]},
        )
        assert score == pytest.approx(0.6)
        assert correct is False
        assert details["positions_correct"] == [0, 1, 3]


class TestRegex:
    def test_match(self):
        score, correct, _ = score_answer(
            "I noticed some latency", {"type": "regex", "value": r"(?i)\b(latency|delay|slow)\b"},
        )
        assert (score, correct) == (1.0, True)

    def test_no_match(self):
        score, correct, _ = score_answer(
            "I liked it", {"type": "regex", "value": r"(?i)\bbroken\b"},
        )
        assert (score, correct) == (0.0, False)


class TestCustomScoring:
    """Verifies the custom-scorer plugin loader handles all three return shapes
    and that broken scorers degrade gracefully without crashing the request."""

    def test_three_tuple_return(self):
        gt = {
            "type": "custom",
            "value": "studio.scoring.custom.example_top_three:score",
            "expected_top": ["a", "b", "c"],
        }
        # All three expected items are in the prefix → 1.0.
        score, correct, details = score_answer(["a", "b", "c", "x"], gt)
        assert score == 1.0
        assert correct is True
        assert details["strategy"] == "custom"
        assert details["hits"] == 3

    def test_partial_score(self):
        gt = {
            "type": "custom",
            "value": "studio.scoring.custom.example_top_three:score",
            "expected_top": ["a", "b", "c"],
        }
        score, correct, details = score_answer(["a", "b", "x"], gt)
        assert score == pytest.approx(2 / 3)
        assert correct is False

    def test_zero_score(self):
        gt = {
            "type": "custom",
            "value": "studio.scoring.custom.example_top_three:score",
            "expected_top": ["a", "b", "c"],
        }
        score, correct, _ = score_answer(["x", "y", "z"], gt)
        assert score == 0.0
        assert correct is False

    def test_bad_callable_path_returns_error_details(self):
        gt = {"type": "custom", "value": "no.such.module:fn"}
        score, correct, details = score_answer("anything", gt)
        assert score is None
        assert correct is None
        assert details["strategy"] == "custom"
        assert "error" in details

    def test_malformed_callable_returns_error(self):
        gt = {"type": "custom", "value": "not-a-callable-path-format"}
        score, correct, details = score_answer("anything", gt)
        assert score is None
        assert correct is None
        assert details["error"] == "bad-callable"
