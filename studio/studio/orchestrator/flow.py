"""Conditional-flow + counterbalancing engine.

Two responsibilities:

  1. ``evaluate_condition`` runs a `next:` rule's ``when:`` string against the
     just-submitted answer. It parses with the stdlib ``ast`` module and walks
     the tree with a whitelist of node types — no ``eval``, no function calls
     outside an allow-list. Allowed names: ``answer``, ``score``, ``correct``,
     ``role``, ``params``.

  2. ``build_block_order`` produces the per-participant (or per-session) block
     order from ``study.block_order`` plus an optional ``block_orders:`` list.
     The output is a flat list of task ids — the participant's ``applied_task_order``.

This file is deliberately dependency-free (no Beanie / FastAPI imports) so it
remains unit-testable in isolation.
"""
from __future__ import annotations

import ast
import random
from typing import Any


# ────────────────────────────────────────────────────────────────────────
# Expression DSL
# ────────────────────────────────────────────────────────────────────────

_ALLOWED_NODES: tuple[type, ...] = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp,
    ast.Compare, ast.Name, ast.Constant, ast.Load,
    ast.Attribute, ast.Subscript, ast.Index, ast.Slice,
    ast.List, ast.Tuple, ast.Set, ast.Dict,
    ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.USub, ast.UAdd,
)

_ALLOWED_NAMES = {"answer", "score", "correct", "role", "params", "True", "False", "None"}


class UnsafeExpression(ValueError):
    pass


def _validate_tree(tree: ast.AST) -> None:
    """Walk every node and refuse anything not on the allow-list."""
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpression(
                f"unsupported syntax: {type(node).__name__} "
                f"(line {getattr(node, 'lineno', '?')}). "
                f"Allowed: comparisons, in/not in, and/or/not, attribute/index."
            )
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
            raise UnsafeExpression(
                f"unknown name '{node.id}' (allowed: {sorted(_ALLOWED_NAMES)})"
            )
        # Refuse dunder + leading-underscore attribute access — even when the
        # value happens to be a string/dict/etc. we don't want studies reaching
        # for ``answer.__class__`` and friends.
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise UnsafeExpression(
                f"private attribute access not allowed: {node.attr}"
            )


def evaluate_condition(
    expr: str,
    *,
    answer: Any = None,
    score: Any = None,
    correct: Any = None,
    role: str | None = None,
    params: dict[str, Any] | None = None,
) -> bool:
    """Return True iff the expression evaluates truthy against the bindings.

    The literal string ``"default"`` (any casing) always returns True — that's
    the spelling for catch-all rules.
    """
    if not expr:
        # Empty string / None: no rule is no rule, never fire.
        return False
    s = str(expr).strip()
    if not s:
        return False
    if s.lower() == "default":
        return True

    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"could not parse: {exc}") from exc
    _validate_tree(tree)

    bindings = {
        "answer":  _wrap_attr_access(answer),
        "score":   score,
        "correct": correct,
        "role":    role,
        "params":  _wrap_attr_access(params or {}),
        "True":    True, "False": False, "None": None,
    }
    # eval against the locked-down tree only; globals are explicitly cleared so
    # builtins are unreachable. (We validated the tree above; this is belt-and-braces.)
    try:
        return bool(eval(compile(tree, "<flow>", "eval"), {"__builtins__": {}}, bindings))
    except Exception as exc:  # KeyError, TypeError, AttributeError, etc.
        raise UnsafeExpression(f"runtime error: {exc}") from exc


class _AttrDict(dict):
    """dict that also exposes its keys as attributes — so ``answer.id`` and
    ``answer['id']`` both work in `when:` expressions."""

    def __getattr__(self, k: str) -> Any:
        if k in self:
            return self[k]
        raise AttributeError(k)


def _wrap_attr_access(value: Any) -> Any:
    """Wrap dicts so .key access works. Lists/strs/etc. pass through unchanged."""
    if isinstance(value, dict):
        return _AttrDict({k: _wrap_attr_access(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap_attr_access(v) for v in value]
    return value


# ────────────────────────────────────────────────────────────────────────
# Counterbalancing
# ────────────────────────────────────────────────────────────────────────

def build_block_order(
    *,
    blocks: list[dict[str, Any]],
    strategy: str,
    declared_orderings: list[list[str]] | None,
    participant_rank: int,
    seed: int | None,
) -> tuple[list[str], list[str], int | None]:
    """Resolve which task ids this participant (or session) sees, in order.

    Returns ``(applied_block_ids, applied_task_ids, used_seed)``:
      - applied_block_ids: ordered block ids
      - applied_task_ids: flat list of task ids in that block order
      - used_seed: the seed we actually used (so callers can persist it)

    ``strategy`` is one of {declared, random, round_robin, latin_square}.
    ``declared_orderings`` is the optional `block_orders:` list — if given,
    round_robin / latin_square rotate through these orderings verbatim;
    otherwise we generate orderings procedurally.
    """
    block_ids = [b.get("id") for b in blocks]
    task_lookup: dict[str, list[str]] = {
        b["id"]: [t.get("id") for t in b.get("tasks", [])] for b in blocks
    }

    if strategy == "declared":
        ordering = list(block_ids)
        used_seed = None
    elif strategy == "random":
        used_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        rng = random.Random(used_seed)
        ordering = list(block_ids)
        rng.shuffle(ordering)
    elif strategy == "round_robin":
        used_seed = None
        if declared_orderings:
            ordering = list(declared_orderings[participant_rank % len(declared_orderings)])
        else:
            # Procedural: shift the declared order by participant_rank positions.
            n = len(block_ids)
            if n == 0:
                ordering = []
            else:
                k = participant_rank % n
                ordering = block_ids[k:] + block_ids[:k]
    elif strategy == "latin_square":
        used_seed = None
        if declared_orderings:
            ordering = list(declared_orderings[participant_rank % len(declared_orderings)])
        else:
            n = len(block_ids)
            if n == 0:
                ordering = []
            else:
                row = participant_rank % n
                ordering = [block_ids[(row + j) % n] for j in range(n)]
    else:
        raise ValueError(f"unknown block_order strategy: {strategy}")

    applied_task_ids: list[str] = []
    for bid in ordering:
        applied_task_ids.extend(task_lookup.get(bid, []))
    return ordering, applied_task_ids, used_seed


# ────────────────────────────────────────────────────────────────────────
# Goto resolution: given the current task's `next:` rules and the answer,
# decide what the participant should see next.
# ────────────────────────────────────────────────────────────────────────

def resolve_next(
    rules: list[dict[str, Any]] | None,
    *,
    current_index: int,
    applied_task_order: list[str],
    block_index_by_task: dict[str, int],
    block_id_by_index: list[str],
    answer: Any,
    score: Any,
    correct: Any,
    role: str | None,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute the orchestrator's directive for what happens after task_submit.

    Return shape:
        {
          "kind": "next" | "task" | "block" | "drop" | "end" | "skip_block",
          "index": int | None,
        }

    ``next`` is the default; ``index`` is set when ``kind`` resolves to a
    concrete position in ``applied_task_order``. The orchestrator interprets
    the rest (``drop`` / ``end`` / ``skip_block``) directly.
    """
    if not rules:
        return {"kind": "next", "index": current_index + 1}

    for rule in rules:
        when = rule.get("when", "")
        try:
            if not evaluate_condition(
                when,
                answer=answer, score=score, correct=correct,
                role=role, params=params,
            ):
                continue
        except UnsafeExpression:
            # Skip a broken rule rather than crashing the participant flow.
            continue

        goto = rule.get("goto") or {}
        if goto.get("next_task"):
            return {"kind": "next", "index": current_index + 1}
        if goto.get("action") == "drop":
            return {"kind": "drop", "index": None}
        if goto.get("action") == "end":
            return {"kind": "end", "index": None}
        if goto.get("action") == "skip_block":
            return {"kind": "skip_block", "index": None}
        if goto.get("task"):
            target = goto["task"]
            try:
                idx = applied_task_order.index(target, current_index)
            except ValueError:
                # Not later in the path — look from the start (allow forward jumps).
                try:
                    idx = applied_task_order.index(target)
                except ValueError:
                    continue  # broken ref; try the next rule
            return {"kind": "task", "index": idx}
        if goto.get("block"):
            block = goto["block"]
            # First task in applied_task_order whose block id matches.
            for i, t in enumerate(applied_task_order):
                if block_id_by_index and i < len(block_id_by_index) and block_id_by_index[i] == block:
                    return {"kind": "block", "index": i}
            continue  # block not in this participant's order

    # No rule matched → linear advance.
    return {"kind": "next", "index": current_index + 1}


# ────────────────────────────────────────────────────────────────────────
# Variable substitution
# ────────────────────────────────────────────────────────────────────────

def apply_lang_overrides(task: dict[str, Any], lang: str | None) -> dict[str, Any]:
    """Resolve per-language overrides on a task dict.

    Looks up ``prompt_md_by_lang[lang]`` and ``body_md_by_lang[lang]``.
    Missing locales pass through; existing role overrides should be applied
    *first* (via ``apply_role_overrides``) so role+lang compose correctly.

    ``lang`` follows BCP-47-ish convention (``"en"``, ``"de"``, ``"de-CH"``);
    we try the full code, then the prefix before ``-``, before giving up.
    """
    if not lang:
        return task
    candidates = [lang]
    if "-" in lang:
        candidates.append(lang.split("-")[0])
    out = dict(task)
    pmbl = out.get("prompt_md_by_lang") or {}
    for c in candidates:
        if c in pmbl:
            out["prompt_md"] = pmbl[c]
            break
    bmbl = out.get("body_md_by_lang") or {}
    for c in candidates:
        if c in bmbl:
            out["body_md"] = bmbl[c]
            break
    return out


def resolve_lang(query_lang: str | None, accept_language: str | None, default_lang: str) -> str:
    """Pick the participant-facing locale.

    Priority: ``?lang=`` query param > first acceptable from ``Accept-Language``
    > study/instance default. We don't negotiate weights — we just take the
    first tag in the header. Good enough; researchers who care set ?lang=
    explicitly via the recruitment-platform redirect URL.
    """
    if query_lang and query_lang.strip():
        return query_lang.strip().lower()
    if accept_language:
        first = accept_language.split(",")[0].strip()
        if first:
            return first.split(";")[0].strip().lower()
    return (default_lang or "en").lower()


def apply_role_overrides(task: dict[str, Any], role: str | None) -> dict[str, Any]:
    """Resolve per-role overrides on a task dict.

    - ``prompt_md_by_role[role]`` replaces ``prompt_md`` (and ``body_md`` for
      info_screen — we mirror the override since the participant template
      branches on type).
    - ``world_state.by_role[role]`` replaces the base ``world_state`` block.

    The original task dict is *not* mutated — we return a shallow copy with
    the role-applied fields swapped in.
    """
    if role is None:
        return task
    out = dict(task)
    pmbr = out.get("prompt_md_by_role") or {}
    if role in pmbr:
        override = pmbr[role]
        out["prompt_md"] = override
        if out.get("type") == "info_screen":
            out["body_md"] = override
    ws = out.get("world_state") or {}
    by_role = (ws.get("by_role") or {}) if isinstance(ws, dict) else {}
    if role in by_role:
        out = {**out, "world_state": by_role[role]}
    return out


def substitute_params(value: Any, params: dict[str, Any]) -> Any:
    """Walk a task dict and substitute ``{{ params.<key> }}`` in any string.

    Only flat ``params.X`` lookups are supported (not arbitrary expressions).
    Missing keys are left intact so authors notice them.
    """
    if not params:
        return value
    if isinstance(value, str):
        return _substitute_string(value, params)
    if isinstance(value, list):
        return [substitute_params(v, params) for v in value]
    if isinstance(value, dict):
        return {k: substitute_params(v, params) for k, v in value.items()}
    return value


def _substitute_string(text: str, params: dict[str, Any]) -> str:
    import re
    pattern = re.compile(r"\{\{\s*params\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

    def _replace(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in params:
            return str(params[key])
        return m.group(0)
    return pattern.sub(_replace, text)
