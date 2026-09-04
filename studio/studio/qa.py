"""
Synthetic-participant QA driver.

"""
from __future__ import annotations

import asyncio
import random
from typing import Any

from studio.config.schemas import StudyConfig
from studio.models import Participant, Session, Study
from studio.orchestrator import flow, session_manager


def canned_answer(task: dict[str, Any], rng: random.Random) -> Any:
    """Return a plausible-looking answer for any task type."""
    ttype = task.get("type")
    if ttype == "info_screen":
        return None
    if ttype == "single_choice":
        opts = task.get("options") or []
        return (rng.choice(opts) or {}).get("id") if opts else None
    if ttype == "multi_choice":
        opts = task.get("options") or []
        if not opts:
            return []
        k = rng.randint(1, max(1, len(opts) // 2))
        return [o.get("id") for o in rng.sample(opts, k)]
    if ttype == "likert":
        scale = task.get("scale") or {}
        lo, hi = int(scale.get("min", 1)), int(scale.get("max", 7))
        items = task.get("items") or []
        return {it.get("id"): rng.randint(lo, hi) for it in items if it.get("id")}
    if ttype == "slider":
        lo = float(task.get("min", 0))
        hi = float(task.get("max", 100))
        return round(rng.uniform(lo, hi), 2)
    if ttype == "number_input":
        lo = float(task.get("min") if task.get("min") is not None else 0)
        hi = float(task.get("max") if task.get("max") is not None else lo + 100)
        return round(rng.uniform(lo, hi), 2)
    if ttype == "free_text":
        lo = int(task.get("min_chars") or 0)
        # Always exceed the minimum by a small margin.
        return "Synthetic answer." + (" " + ("Lorem ipsum dolor. " * 3) if lo > 16 else "")
    if ttype == "va_interaction":
        # Skip the VA bit; record an empty capture.
        return None
    return None


async def run_one(
    study: Study,
    cfg: StudyConfig,
    rng: random.Random,
    role_id: str | None,
    label: str = "synthetic",
) -> dict[str, Any]:
    """Walk a single synthetic participant through ``study`` and return a summary."""
    session = await session_manager.create_singleplayer_session(study)
    participant = await session_manager.register_participant(
        session, user_agent=f"studio-qa/{label}", ip_hash=None,
        code_id=None, role=role_id,
    )
    # Tag both for downstream filtering.
    await session_manager._record_event(
        session.study_id, session.id, type="synthetic_participant",
        participant_id=participant.id, task_id=None,
        meta={"label": label, "seed": getattr(participant, "shuffle_seed", None)},
    )
    await session_manager.record_consent(participant)

    safety = max(8, 4 * len(participant.applied_task_order or []))
    visited: list[dict[str, Any]] = []
    for _ in range(safety):
        fresh = await Participant.get(participant.id)
        if fresh is None or fresh.status in ("finished", "dropped"):
            break
        applied = list(fresh.applied_task_order or [])
        if not applied:
            applied = [t.id for b in cfg.blocks for t in b.tasks]
        cursor = fresh.flow_pointer or 0
        if cursor >= len(applied):
            await session_manager.finish_participant(fresh, session)
            break
        task_id = applied[cursor]
        task = next(
            (t.model_dump() for blk in cfg.blocks for t in blk.tasks if t.id == task_id),
            None,
        )
        if task is None:
            await session_manager.finish_participant(fresh, session)
            break

        # start_task + tick any required steps + submit canned answer.
        block_id = next(
            (b.id for b in cfg.blocks if any(t.id == task_id for t in b.tasks)),
            "",
        )
        await session_manager.start_task(
            fresh, session, task, cursor, block_id, study_config=cfg,
        )
        # Tick required steps so the gate accepts the submission.
        for step in (task.get("task_steps") or []):
            if step.get("required") and step.get("id"):
                await session_manager.record_step_checked(
                    await Participant.get(participant.id) or fresh,
                    session, task, step["id"], source="auto",
                )
        answer = canned_answer(task, rng)
        await session_manager.end_task(
            await Participant.get(participant.id) or fresh,
            session, task, answer, block_id, skipped=False,
        )
        # Apply conditional flow same as the live participant route.
        from studio.models.participant import TaskRun
        latest = await Participant.get(participant.id)
        if latest and latest.task_runs:
            await _resolve_singleplayer_next_ghost(latest, cfg, task)
        visited.append({"task_id": task_id, "answer": answer})

    # Finish if not already.
    final = await Participant.get(participant.id)
    if final and final.status not in ("finished", "dropped"):
        await session_manager.finish_participant(final, session)

    return {
        "session_id": str(session.id),
        "participant_id": str(participant.id),
        "anon_id": participant.anon_id,
        "role": role_id,
        "task_count": len(visited),
        "shuffle_seed": getattr(participant, "shuffle_seed", None),
    }


async def _resolve_singleplayer_next_ghost(
    participant: Participant, cfg: StudyConfig, task: dict[str, Any],
) -> None:
    """Mirror participant.py's `_resolve_singleplayer_next` for the ghost driver.

    We don't import that function directly because it depends on the request
    helpers — easier to repeat the small dispatch here.
    """
    applied = list(participant.applied_task_order or [])
    if not applied:
        return
    cursor = participant.flow_pointer or 0
    block_id_by_task = {t.id: b.id for b in cfg.blocks for t in b.tasks}
    block_id_by_index = [block_id_by_task.get(tid, "") for tid in applied]
    run = participant.task_runs[-1]
    directive = flow.resolve_next(
        task.get("next"),
        current_index=cursor,
        applied_task_order=applied,
        block_index_by_task={t: i for i, t in enumerate(applied)},
        block_id_by_index=block_id_by_index,
        answer=run.answer, score=run.score, correct=run.correct,
        role=participant.role, params=cfg.parameters or {},
    )
    fresh = await Participant.get(participant.id) or participant
    if directive["kind"] == "drop":
        fresh.status = "dropped"
        fresh.flow_pointer = len(applied)
    elif directive["kind"] == "end":
        fresh.flow_pointer = len(applied)
    elif directive["kind"] == "skip_block":
        cur_block = block_id_by_task.get(applied[cursor], "") if cursor < len(applied) else ""
        next_idx = cursor + 1
        while next_idx < len(applied) and block_id_by_task.get(applied[next_idx], "") == cur_block:
            next_idx += 1
        fresh.flow_pointer = next_idx
    else:
        fresh.flow_pointer = directive.get("index") or (cursor + 1)
    await fresh.save()


async def run_many(
    slug: str, n: int = 5, seed: int | None = None, role: str | None = None,
) -> dict[str, Any]:
    """Drive N synthetic participants through ``slug`` and return summaries.

    Multiplayer studies are refused — see module docstring.
    """
    study = await Study.find_one(Study.slug == slug)
    if study is None:
        raise ValueError(f"unknown study: {slug}")
    if study.mode != "singleplayer":
        raise ValueError("synthetic participants only support singleplayer studies")

    from studio.api.participant import _study_to_config
    cfg = _study_to_config(study)

    rng = random.Random(seed if seed is not None else 0xc0ffee)
    runs: list[dict[str, Any]] = []
    for i in range(max(1, n)):
        # Each ghost gets its own RNG branch so seeds inside the study (random
        # block_order) still diverge between ghosts but stay reproducible.
        sub = random.Random(rng.randint(0, 2**31 - 1))
        info = await run_one(study, cfg, sub, role_id=role, label=f"ghost-{i}")
        runs.append(info)
        await asyncio.sleep(0)  # yield to the event loop between ghosts
    return {"study": slug, "n": len(runs), "runs": runs}
