"""Example custom scorer: partial credit for getting the top 3 right.

Demonstrates the three-tuple return shape:

    (score: float in [0, 1], correct: bool, details: dict)

Use from a study YAML:

    ground_truth:
      type: custom
      value: studio.scoring.custom.example_top_three:score
      # `expected` lives under whatever key your custom function reads; here
      # we read `ground_truth["expected_top"]` so the YAML carries the answer.
      expected_top: [honda_civic, toyota_corolla, vw_dasher]
"""
from __future__ import annotations

from typing import Any


def score(answer: Any, ground_truth: dict[str, Any]) -> tuple[float, bool, dict]:
    """Score the participant's top-3 ranking against an expected top-3 set.

    The score is the fraction of the expected items that appear *anywhere* in
    the participant's top three — order-insensitive within the prefix.
    """
    expected = list(ground_truth.get("expected_top") or [])
    if not isinstance(answer, list) or not expected:
        return 0.0, False, {"reason": "no-answer-or-no-expected"}
    prefix = list(answer[: len(expected)])
    hits = sum(1 for e in expected if e in prefix)
    ratio = hits / len(expected)
    return ratio, ratio >= 0.999, {"prefix": prefix, "hits": hits, "expected": expected}
