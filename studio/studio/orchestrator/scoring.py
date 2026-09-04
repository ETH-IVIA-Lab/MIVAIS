"""Ground-truth scoring functions for the supported strategies.

Studies declare scoring on a task via:

    ground_truth:
      type: exact | set_match | ordered_match | regex | custom
      value: <type-specific>
      partial_credit: true | false        # default true for set/ordered

For ``type: custom``, ``value:`` is a dotted path to an importable callable.
The function receives the participant's ``answer`` and must return one of:
  - a 3-tuple ``(score: float, correct: bool, details: dict)``
  - a single ``bool`` (treated as ``(1.0, bool, {})`` / ``(0.0, bool, {})``)
  - a single ``float`` in [0, 1] (treated as ``(f, f >= 0.999, {})``)

Custom callables can live anywhere on ``sys.path``; the convention is
``studio.scoring.custom.<name>:<fn>`` for project-local scorers, where files
under ``studio/scoring/custom/`` are auto-discovered on import.
"""
from __future__ import annotations

import importlib
import logging
import re
from typing import Any

log = logging.getLogger("studio.scoring")


def score_answer(answer: Any, ground_truth: dict[str, Any] | None) -> tuple[float | None, bool | None, dict[str, Any] | None]:
    """Return (score, correct, details). score is 0.0-1.0, or None if no GT."""
    if ground_truth is None:
        return None, None, None
    gt_type = ground_truth.get("type", "exact")
    gt_value = ground_truth.get("value")
    partial = ground_truth.get("partial_credit", True)

    if gt_type == "exact":
        ok = answer == gt_value
        return (1.0 if ok else 0.0), ok, {"strategy": "exact"}

    if gt_type == "set_match" and isinstance(answer, list) and isinstance(gt_value, list):
        a, b = set(answer), set(gt_value)
        if not a and not b:
            return 1.0, True, {"strategy": "set_match", "jaccard": 1.0}
        jaccard = len(a & b) / len(a | b)
        ok = jaccard == 1.0
        score = jaccard if partial else (1.0 if ok else 0.0)
        return score, ok, {"strategy": "set_match", "jaccard": jaccard}

    if gt_type == "ordered_match" and isinstance(answer, list) and isinstance(gt_value, list):
        n = max(len(answer), len(gt_value))
        if n == 0:
            return 1.0, True, {"strategy": "ordered_match", "positions_correct": []}
        positions_correct = [
            i for i in range(min(len(answer), len(gt_value)))
            if answer[i] == gt_value[i]
        ]
        ratio = len(positions_correct) / n
        ok = ratio == 1.0
        score = ratio if partial else (1.0 if ok else 0.0)
        return score, ok, {"strategy": "ordered_match", "positions_correct": positions_correct}

    if gt_type == "regex" and isinstance(answer, str) and isinstance(gt_value, str):
        match = re.search(gt_value, answer)
        ok = match is not None
        return (1.0 if ok else 0.0), ok, {"strategy": "regex"}

    if gt_type == "custom":
        if not isinstance(gt_value, str) or ":" not in gt_value:
            log.warning("custom scoring expected a 'module.path:fn' value, got %r", gt_value)
            return None, None, {"strategy": "custom", "error": "bad-callable"}
        return _run_custom_scorer(gt_value, answer, ground_truth)

    # Unknown strategy: store nothing
    return None, None, None


def _run_custom_scorer(
    path: str, answer: Any, ground_truth: dict[str, Any],
) -> tuple[float | None, bool | None, dict[str, Any] | None]:
    """Import and invoke a ``module.path:function`` scorer.

    Safe in the sense that we let exceptions surface only as ``details["error"]``
    on the result — a failing scorer never breaks the participant flow.
    """
    mod_path, _, fn_name = path.partition(":")
    try:
        module = importlib.import_module(mod_path)
        fn = getattr(module, fn_name)
    except Exception as exc:
        log.exception("custom scorer %s could not be imported: %s", path, exc)
        return None, None, {"strategy": "custom", "error": f"import: {exc}"}

    try:
        result = fn(answer, ground_truth)
    except Exception as exc:
        log.exception("custom scorer %s raised", path)
        return None, None, {"strategy": "custom", "error": f"raised: {exc}"}

    if isinstance(result, tuple) and len(result) == 3:
        score, correct, details = result
        d = dict(details or {})
        d["strategy"] = "custom"
        d.setdefault("callable", path)
        return float(score) if score is not None else None, \
               (bool(correct) if correct is not None else None), \
               d
    if isinstance(result, bool):
        return (1.0 if result else 0.0), result, {"strategy": "custom", "callable": path}
    if isinstance(result, (int, float)):
        s = float(result)
        return s, s >= 0.999, {"strategy": "custom", "callable": path}
    log.warning("custom scorer %s returned unexpected type: %r", path, type(result))
    return None, None, {"strategy": "custom", "error": "unexpected-return"}
