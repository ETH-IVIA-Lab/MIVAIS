"""High-level session lifecycle: create, start, run tasks, finish.

A session is created by the participant join flow, transitioned through
states as the participant moves through tasks, and torn down on completion.
The manager owns the orchestration; routes just call into it.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId

import logging

from studio.config.schemas import StudyConfig, VAConfig
from studio.models import Event, Participant, Session, Study
from studio.models.event import SOURCE_STUDIO
from studio.models.session import VAProcessInfo
from studio.orchestrator import ws_collector, auto_check, flow
from studio.orchestrator.scoring import score_answer
from studio.orchestrator.va_client import VAClientError, push_world_state
from studio.orchestrator.va_spawner import va_spawner
from studio.settings import get_settings


log = logging.getLogger("studio.session_manager")


class _VASystemNotConfigured(RuntimeError):
    pass


def _utcnow() -> datetime:
    # Mongo stores datetimes without timezone info, so we keep our own naive
    # UTC datetimes throughout to avoid offset-naive/aware subtraction errors
    # on values that round-trip through the database.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _anon_id() -> str:
    return "p_" + secrets.token_hex(3)


class SessionManager:
    # ── creation ──────────────────────────────────────────────────────────

    async def create_singleplayer_session(self, study: Study) -> Session:
        snapshot, snap_hash = _snapshot_of(study)
        session = Session(
            study_id=study.id, mode="singleplayer", status="pending",
            study_snapshot=snapshot, study_yaml_hash=snap_hash,
        )
        await session.insert()
        await self._record_event(
            study.id, session.id, type="session_created",
            participant_id=None, task_id=None,
            meta={"mode": "singleplayer", "study_yaml_hash": snap_hash},
        )
        return session

    async def create_multiplayer_session(self, study: Study) -> Session:
        """Create a new multiplayer cohort session in `lobby` state.

        Participants attach to this session via Code.multiplayer_session_id.
        Once `participants_required` participants have clicked ready, the
        orchestrator transitions the session to running and spawns the shared VA.
        """
        snapshot, snap_hash = _snapshot_of(study)
        session = Session(
            study_id=study.id, mode="multiplayer", status="lobby",
            study_snapshot=snapshot, study_yaml_hash=snap_hash,
        )
        await session.insert()
        await self._record_event(
            study.id, session.id, type="session_created",
            participant_id=None, task_id=None,
            meta={"mode": "multiplayer", "study_yaml_hash": snap_hash},
        )
        return session

    async def register_participant(
        self,
        session: Session,
        user_agent: str | None = None,
        ip_hash: str | None = None,
        code_id: Any | None = None,
        role: str | None = None,
    ) -> Participant:
        # Multiplayer participants land in the lobby pending ready-up.
        initial_status = "lobby" if session.mode == "multiplayer" else "joined"
        participant = Participant(
            session_id=session.id,
            study_id=session.study_id,
            anon_id=_anon_id(),
            status=initial_status,
            user_agent=user_agent,
            ip_hash=ip_hash,
            code_id=code_id,
            role=role,
        )
        await participant.insert()
        # Counterbalancing: in singleplayer, each participant gets their own
        # applied_task_order; in multiplayer it's set once when the lobby
        # releases (see try_start_multiplayer).
        if session.mode != "multiplayer":
            await self._apply_counterbalance(participant, session)
        await self._record_event(
            session.study_id, session.id, type="participant_joined",
            participant_id=participant.id, task_id=None,
            meta={
                "anon_id": participant.anon_id,
                "role": role,
                "applied_task_order": list(participant.applied_task_order),
            },
        )
        return participant

    async def _apply_counterbalance(self, participant: Participant, session: Session) -> None:
        """Compute and persist this participant's applied_task_order."""
        study = await Study.get(session.study_id)
        if study is None or not study.blocks:
            return
        # participant_rank: how many participants of this study have joined before this one.
        rank = await Participant.find(
            Participant.study_id == study.id,
            Participant.id != participant.id,
        ).count()
        strategy = study.advance_policy and getattr(study, "block_order", "declared") or "declared"
        # Re-fetch the real field (above expression is defensive).
        strategy = getattr(study, "block_order", None) or "declared"
        block_orders = getattr(study, "block_orders", None) or []
        _block_ids, applied_tasks, used_seed = flow.build_block_order(
            blocks=study.blocks or [],
            strategy=strategy,
            declared_orderings=block_orders or None,
            participant_rank=rank,
            seed=None,
        )
        participant.applied_task_order = applied_tasks
        participant.shuffle_seed = used_seed
        participant.flow_pointer = 0
        await participant.save()

    async def record_consent(self, participant: Participant) -> None:
        participant.consented_at = _utcnow()
        # Multiplayer participants stay in `lobby` after consent until they ready up.
        session = await Session.get(participant.session_id)
        if session and session.mode == "multiplayer":
            participant.status = "lobby"
        else:
            participant.status = "consented"
        await participant.save()
        await self._record_event(
            participant.study_id, participant.session_id, type="user_consent_accepted",
            participant_id=participant.id, task_id=None, meta={},
        )

    async def assign_role(self, participant: Participant, role_id: str) -> None:
        previous = participant.role
        participant.role = role_id
        await participant.save()
        await self._record_event(
            participant.study_id, participant.session_id, type="role_assigned",
            participant_id=participant.id, task_id=None,
            meta={"role": role_id, "previous": previous},
        )

    async def mark_ready(self, participant: Participant) -> None:
        if participant.status not in ("lobby", "joined", "consented"):
            return
        participant.status = "ready"
        participant.ready_at = _utcnow()
        await participant.save()
        await self._record_event(
            participant.study_id, participant.session_id, type="participant_ready",
            participant_id=participant.id, task_id=None,
            meta={"anon_id": participant.anon_id},
        )
        # Attempt session-level transition (lobby → running).
        session = await Session.get(participant.session_id)
        if session is not None:
            await self.try_start_multiplayer(session)

    async def try_start_multiplayer(self, session: Session) -> bool:
        """If every required participant has clicked ready, leave the lobby.

        The VA spawn itself is deferred to the first va_interaction task
        (handled by participant.task_page via ensure_va_started), so a
        questionnaire-only multiplayer study never spawns a VA.
        """
        if session.mode != "multiplayer" or session.status != "lobby":
            return False
        study = await Study.get(session.study_id)
        required = study.participants_required if study and study.participants_required else 1
        participants = await Participant.find(
            Participant.session_id == session.id,
        ).to_list()
        ready_count = sum(1 for p in participants if p.status == "ready")
        if ready_count < required:
            return False

        # Counterbalancing for the whole cohort: pick one order at session level.
        if study is not None and not session.applied_task_order:
            cohort_rank = await Session.find(
                Session.study_id == study.id,
                Session.mode == "multiplayer",
                Session.id != session.id,
            ).count()
            strategy = getattr(study, "block_order", None) or "declared"
            block_orders = getattr(study, "block_orders", None) or []
            _block_ids, applied_tasks, used_seed = flow.build_block_order(
                blocks=study.blocks or [],
                strategy=strategy,
                declared_orderings=block_orders or None,
                participant_rank=cohort_rank,
                seed=None,
            )
            session.applied_task_order = applied_tasks
            session.shuffle_seed = used_seed

        session.status = "running"
        await session.save()
        # Move every ready participant into in_session.
        for p in participants:
            if p.status == "ready":
                p.status = "in_session"
                await p.save()
        await self._record_event(
            session.study_id, session.id, type="lobby_released",
            participant_id=None, task_id=None,
            meta={"participants": len([p for p in participants if p.status == 'in_session'])},
        )
        return True

    async def recover_interrupted_sessions(self) -> dict[str, int]:
        """At startup, look at every session that was active when Studio went down.

        For each VA recorded on the session:
          - If the OS still reports the PID alive: reattach to the spawner +
            reconnect the WebSocket collector (event ingest resumes live).
          - If the PID is gone: drop it from session.vas.

        Sessions that no longer have any live VA get their status flipped to
        ``interrupted``. ``lobby`` sessions are left as-is (no VAs to lose;
        ready-up still works after restart).

        Returns counts: {"recovered": N, "interrupted": M, "lobby_kept": K}.
        """
        from studio.process import pid_alive
        from datetime import datetime, timezone
        recovered = interrupted = lobby_kept = 0
        sessions = await Session.find(
            {"status": {"$in": ["running", "spawning", "lobby"]}}
        ).to_list()
        for session in sessions:
            if session.status == "lobby":
                lobby_kept += 1
                continue
            study = await Study.get(session.study_id)
            # Which of session.vas are still alive?
            survivors: dict[str, VAProcessInfo] = {}
            for va_system_id, info in (session.vas or {}).items():
                if pid_alive(info.pid):
                    survivors[va_system_id] = info
                else:
                    log.info(
                        "session %s: VA '%s' (pid %s) is gone after restart",
                        session.id, va_system_id, info.pid,
                    )
            if not survivors:
                session.status = "interrupted"
                session.failure_reason = "Studio restarted while session was active; VA process(es) lost"
                session.interrupted_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.vas = {}
                await session.save()
                interrupted += 1
                await self._record_event(
                    session.study_id, session.id, type="session_interrupted",
                    participant_id=None, task_id=None, meta={"reason": "studio_restart"},
                )
                continue

            # Reattach survivors to the spawner + restart their live collectors.
            for va_system_id, info in survivors.items():
                if info.recording_dir is None or info.iframe_url is None:
                    continue
                from pathlib import Path
                started_at = session.va_started_at or datetime.now(timezone.utc).replace(tzinfo=None)
                va_spawner.reattach(
                    session_id=str(session.id),
                    va_system_id=va_system_id,
                    pid=info.pid or 0,
                    port=info.port or 0,
                    recording_dir=Path(info.recording_dir),
                    iframe_url=info.iframe_url,
                    internal_url=info.internal_url or info.iframe_url,
                    variant=info.variant or "default",
                    started_at=started_at,
                )
                await ws_collector.start_collector(
                    session.id, session.study_id, va_system_id, info.internal_url or info.iframe_url,
                )
            session.vas = survivors
            await session.save()
            recovered += 1
            await self._record_event(
                session.study_id, session.id, type="session_recovered",
                participant_id=None, task_id=None,
                meta={"va_systems": sorted(survivors)},
            )
        return {"recovered": recovered, "interrupted": interrupted, "lobby_kept": lobby_kept}

    async def _advance_context(self, session: Session):
        """Shared lookup for try_advance_session / seconds_until_auto_advance:
        the current task, its resolved policy, the in-session participants,
        how many have already submitted the current task, and their submit
        (ended_at) timestamps. None when advance-policy logic doesn't apply
        (not multiplayer/running, or past the last task)."""
        if session.mode != "multiplayer" or session.status != "running":
            return None
        study = await Study.get(session.study_id)
        if study is None:
            return None
        flat_tasks = [t for b in (study.blocks or []) for t in b.get("tasks", [])]
        if session.current_task_index >= len(flat_tasks):
            return None
        task = flat_tasks[session.current_task_index]
        per_task_policy = (task.get("advance") or {}).get("policy")
        policy = per_task_policy or study.advance_policy or "all"

        participants = await Participant.find(
            Participant.session_id == session.id,
            Participant.status == "in_session",
        ).to_list()
        # Number of participants whose latest task_run has ended for the current
        # session task, and when. We use task_index to identify the current
        # task per-participant.
        submitted = 0
        submit_times: list[datetime] = []
        for p in participants:
            runs = p.task_runs
            if runs and runs[-1].task_index == session.current_task_index and runs[-1].ended_at is not None:
                submitted += 1
                submit_times.append(runs[-1].ended_at)
        return task, policy, participants, submitted, submit_times

    async def seconds_until_auto_advance(self, session: Session) -> int | None:
        """For the waiting-cohort UI: seconds left before an `advance.policy:
        admin` task with `timeout_seconds` set will auto-advance, so the
        participant sees a real countdown instead of a static "waiting"
        message that looks identical whether it's about to resolve itself in
        5 seconds or hanging forever. None when there's nothing to count down
        to (not admin-gated, no timeout configured, or the cohort isn't
        actually fully waiting yet — the timeout is a safety net for "admin
        hasn't clicked", not a way to shortcut the "all" case)."""
        ctx = await self._advance_context(session)
        if ctx is None:
            return None
        task, policy, participants, submitted, submit_times = ctx
        if policy != "admin":
            return None
        timeout_s = (task.get("advance") or {}).get("timeout_seconds")
        if not timeout_s or not participants or submitted < len(participants):
            return None
        waiting_since = max(submit_times) if submit_times else None
        if waiting_since is None:
            return None
        remaining = timeout_s - (_utcnow() - waiting_since).total_seconds()
        return max(0, round(remaining))

    async def try_advance_session(self, session: Session, force: bool = False) -> bool:
        """In multiplayer, advance session.current_task_index per advance.policy.

        Called from task_submit, the admin /sessions/<id>/advance route, and
        participant_state's poll (so an admin-policy task's timeout_seconds
        safety net gets re-checked while a fully-submitted cohort just sits
        on the "waiting" screen — see seconds_until_auto_advance's docstring).
        Singleplayer flows already advance per-participant on each /p/task
        render and do not need session-level coordination.
        """
        ctx = await self._advance_context(session)
        if ctx is None:
            return False
        task, policy, participants, submitted, submit_times = ctx

        if not force:
            if policy == "first":
                if submitted < 1:
                    return False
            elif policy == "all":
                if submitted < len(participants):
                    return False
            elif policy == "admin":
                timeout_s = (task.get("advance") or {}).get("timeout_seconds")
                if not timeout_s or not participants or submitted < len(participants):
                    return False
                # The wait clock starts once the LAST participant finishes —
                # that's the moment the cohort is actually blocked on the
                # admin/timeout, not on each other.
                waiting_since = max(submit_times) if submit_times else None
                if waiting_since is None or (_utcnow() - waiting_since).total_seconds() < timeout_s:
                    return False

        session.current_task_index += 1
        await session.save()
        await self._record_event(
            session.study_id, session.id, type="session_advanced",
            participant_id=None, task_id=None,
            meta={
                "to_task_index": session.current_task_index,
                "policy": policy,
                "forced": force,
                "submitted": submitted,
                "participants": len(participants),
            },
        )
        return True

    # ── VA lifecycle ──────────────────────────────────────────────────────

    async def ensure_va_started(
        self,
        session: Session,
        study_config: StudyConfig,
        va_system_id: str,
        task_variant: str | None,
    ) -> str:
        """Spawn the named VA for this session (if not already running) and return its iframe URL.

        Multiple VA systems may be running for one session simultaneously.
        Re-spawn only when the requested variant differs from what is running.
        """
        va = study_config.va_systems.get(va_system_id)
        if va is None:
            raise _VASystemNotConfigured(
                f"study has no va_system '{va_system_id}' "
                f"(known: {sorted(study_config.va_systems)})"
            )

        sid = str(session.id)
        running = va_spawner.get(sid, va_system_id)
        if running is not None and (task_variant is None or running.variant == task_variant):
            return running.iframe_url
        if running is not None:
            await va_spawner.stop(sid, va_system_id)
            await ws_collector.stop_collector(session.id, va_system_id)

        variant = task_variant or "default"
        recording_dir = self._recording_dir_for(va, va_system_id, session)

        # Only the *first* VA in a session flips status to spawning/running and
        # anchors va_started_at. Subsequent VAs join without disturbing the clock.
        first_va = not session.vas
        if first_va:
            session.status = "spawning"
            await session.save()
        await self._record_event(
            session.study_id, session.id, type="va_spawning",
            participant_id=None, task_id=None,
            va_system_id=va_system_id,
            meta={"variant": variant, "recording_dir": str(recording_dir)},
        )

        spawned = await va_spawner.spawn(
            session_id=sid,
            va_system_id=va_system_id,
            va=va,
            variant_name=variant,
            recording_dir=recording_dir,
        )

        if first_va:
            session.status = "running"
            session.va_started_at = spawned.started_at
        session.vas[va_system_id] = VAProcessInfo(
            pid=spawned.pid,
            port=spawned.port,
            recording_dir=str(spawned.recording_dir),
            iframe_url=spawned.iframe_url,
            internal_url=spawned.internal_url,
            variant=spawned.variant,
        )
        await session.save()

        await ws_collector.start_collector(
            session.id, session.study_id, va_system_id, spawned.internal_url,
        )
        await self._record_event(
            session.study_id, session.id, type="va_spawned",
            participant_id=None, task_id=None,
            va_system_id=va_system_id,
            meta={"variant": variant, "pid": spawned.pid, "port": spawned.port},
        )
        return spawned.iframe_url

    async def stop_session_vas(self, session: Session) -> None:
        """Tear down every VA and collector running for this session."""
        await ws_collector.stop_session(session.id)
        await va_spawner.stop_session(str(session.id))
        await self._record_event(
            session.study_id, session.id, type="va_terminated",
            participant_id=None, task_id=None, meta={},
        )

    # ── task transitions ──────────────────────────────────────────────────

    async def start_task(
        self,
        participant: Participant,
        session: Session,
        task: dict[str, Any],
        task_index: int,
        block_id: str,
        study_config: StudyConfig | None = None,
    ) -> None:
        from studio.models.participant import TaskRun

        # End any previous in-progress run (defensive)
        if participant.task_runs and participant.task_runs[-1].ended_at is None:
            participant.task_runs[-1].ended_at = _utcnow()

        participant.task_runs.append(TaskRun(
            task_id=task["id"],
            task_index=task_index,
            started_at=_utcnow(),
        ))
        participant.status = "in_session"
        await participant.save()

        logging_id = (task.get("mivais_config") or {}).get("logging_id")
        ws_collector.set_active_task(str(session.id), task["id"], logging_id)

        # Register auto-check triggers for this task's task_steps (if any).
        auto_check.register_task(str(session.id), task["id"], task.get("task_steps") or [])

        await self._record_event(
            session.study_id, session.id, type="task_start",
            participant_id=participant.id, task_id=task["id"], block_id=block_id,
            logging_id=logging_id,
            meta={"task_type": task["type"], "task_index": task_index},
        )

        # Apply per-task WorldState (continue with optional delta, or full replace).
        if study_config is not None:
            await self._apply_world_state(session, study_config, task, participant=participant)

    async def _apply_world_state(
        self,
        session: Session,
        study_config: StudyConfig,
        task: dict[str, Any],
        participant: "Participant | None" = None,
    ) -> None:
        """Push the task's ``world_state:`` payload to the VA over the Gateway WS.

        - mode=continue: write only the delta in ``set:`` (skip the call if empty).
        - mode=replace: write every key in ``initial:``.
        - Per-role override: if the task's ``world_state.by_role`` declares a
          block for the participant's role, that block is used instead.
        Failures are logged but never fail the task; the participant flow stays alive.
        """
        ws_cfg = task.get("world_state")
        if not ws_cfg:
            return
        # Per-role swap.
        if participant is not None and participant.role:
            by_role = ws_cfg.get("by_role") if isinstance(ws_cfg, dict) else None
            if by_role and participant.role in by_role:
                ws_cfg = by_role[participant.role]
        mode = ws_cfg.get("mode", "continue") if isinstance(ws_cfg, dict) else "continue"
        if mode == "replace":
            payload = dict(ws_cfg.get("initial") or {}) if isinstance(ws_cfg, dict) else {}
        else:
            payload = dict(ws_cfg.get("set") or {}) if isinstance(ws_cfg, dict) else {}
        # MIVAIS config forwarding: when the task declares overrides for the
        # VA's MivaisConfig (chat/cursors/audit/broadcast/etc.), inject them
        # under a dedicated `mivais_config_override` key. A MIVAIS-side
        # subscription can pick this up and apply the override. Non-MIVAIS-
        # aware VAs simply ignore the key.
        mivais_cfg = task.get("mivais_config") or {}
        # Drop logging_id — that lives in the JSONL tail, not in WorldState.
        cfg_override = {k: v for k, v in mivais_cfg.items() if k != "logging_id"}
        if cfg_override:
            payload = {**payload, "mivais_config_override": cfg_override}

        if not payload:
            return

        va_system_id = task.get("va_system") or study_config.primary_va_system
        if not va_system_id:
            return
        spawned = va_spawner.get(str(session.id), va_system_id)
        if spawned is None:
            log.warning(
                "world_state write skipped: VA '%s' not running for session %s",
                va_system_id, session.id,
            )
            return

        try:
            await push_world_state(spawned.iframe_url, payload)
        except VAClientError as exc:
            log.warning("world_state push failed for task %s: %s", task.get("id"), exc)
            await self._record_event(
                session.study_id, session.id, type="world_state_push_failed",
                participant_id=None, task_id=task.get("id"),
                va_system_id=va_system_id,
                meta={"mode": mode, "error": str(exc)},
            )
            return

        await self._record_event(
            session.study_id, session.id, type="world_state_push",
            participant_id=None, task_id=task.get("id"),
            va_system_id=va_system_id,
            meta={"mode": mode, "keys": sorted(payload.keys())},
        )

    async def record_step_checked(
        self,
        participant: Participant,
        session: Session,
        task: dict[str, Any],
        step_id: str,
        source: str = "manual",  # "manual" | "auto"
    ) -> bool:
        """Mark a task_step as checked, persist on the active TaskRun, emit an event.

        Returns True if this is the first time we record this step for the run,
        False if it was already checked (idempotent).
        """
        if not participant.task_runs or participant.task_runs[-1].task_id != task.get("id"):
            return False
        run = participant.task_runs[-1]
        if step_id in run.checked_steps:
            return False
        run.checked_steps.append(step_id)
        await participant.save()
        logging_id = (task.get("mivais_config") or {}).get("logging_id")
        await self._record_event(
            session.study_id, session.id, type="task_step_checked",
            participant_id=participant.id, task_id=task.get("id"),
            block_id=None, logging_id=logging_id,
            meta={"step_id": step_id, "source": source},
        )
        return True

    async def end_task(
        self,
        participant: Participant,
        session: Session,
        task: dict[str, Any],
        answer: Any,
        block_id: str,
        timed_out: bool = False,
        skipped: bool = False,
    ) -> None:
        # Stop watching for auto-check triggers on this task.
        auto_check.clear_task(str(session.id), task["id"])
        # Update the last task run on the participant
        run = participant.task_runs[-1] if participant.task_runs else None
        if run is not None:
            run.ended_at = _utcnow()
            run.answer = answer
            run.timed_out = timed_out
            run.skipped = skipped
            if run.started_at:
                # Strip tzinfo on both sides; Beanie may add UTC on round-trip,
                # while _utcnow() is naive.
                started = run.started_at.replace(tzinfo=None) if run.started_at.tzinfo else run.started_at
                ended = run.ended_at.replace(tzinfo=None) if run.ended_at.tzinfo else run.ended_at
                run.duration_ms = int((ended - started).total_seconds() * 1000)

            gt = task.get("ground_truth")
            run.score, run.correct, run.score_details = score_answer(answer, gt)
        await participant.save()

        logging_id = (task.get("mivais_config") or {}).get("logging_id")
        await self._record_event(
            session.study_id, session.id, type="task_end",
            participant_id=participant.id, task_id=task["id"], block_id=block_id,
            logging_id=logging_id,
            meta={
                "task_type": task["type"],
                "timed_out": timed_out,
                "skipped": skipped,
                "answer": answer,
                "score": run.score if run else None,
                "correct": run.correct if run else None,
            },
        )

    async def finish_participant(self, participant: Participant, session: Session) -> None:
        participant.status = "finished"
        participant.finished_at = _utcnow()
        await participant.save()
        await self._record_event(
            session.study_id, session.id, type="participant_finished",
            participant_id=participant.id, task_id=None,
            meta={"anon_id": participant.anon_id},
        )

        # Fire participant_finished webhook (best-effort, never blocks).
        try:
            study = await Study.get(session.study_id)
            if study is not None:
                from studio import webhooks
                await webhooks.fire("participant_finished", study, session, {
                    "participant_anon": participant.anon_id,
                    "role": participant.role,
                    "task_runs": len(participant.task_runs),
                })
        except Exception:
            log.exception("webhook fire (participant_finished) failed")

        # For singleplayer: when the only participant finishes, end the session.
        if session.mode == "singleplayer":
            session.status = "completed"
            session.ended_at = _utcnow()
            await session.save()
            await self._record_event(
                session.study_id, session.id, type="session_completed",
                participant_id=None, task_id=None, meta={},
            )
            await self.stop_session_vas(session)
            try:
                study = await Study.get(session.study_id)
                if study is not None:
                    from studio import webhooks
                    await webhooks.fire("session_completed", study, session, {})
            except Exception:
                log.exception("webhook fire (session_completed) failed")

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _recording_dir_for(va: VAConfig, va_system_id: str, session: Session) -> Path:
        """Return the directory this VA writes (and Studio tails) for this session.

        If the VA hardcodes its recording directory, the YAML can set
        `va.recording_dir_override` to that path; otherwise Studio creates a
        per-(session, va_system) directory under settings.data_dir so multiple
        VAs in one session never collide.
        """
        if va.recording_dir_override:
            override = Path(va.recording_dir_override).expanduser().resolve()
            override.mkdir(parents=True, exist_ok=True)
            return override
        settings = get_settings()
        base = (
            settings.data_dir / "recordings"
            / str(session.study_id) / str(session.id) / va_system_id
        )
        base.mkdir(parents=True, exist_ok=True)
        return base

    @staticmethod
    async def _record_event(
        study_id: PydanticObjectId,
        session_id: PydanticObjectId,
        *,
        type: str,
        participant_id: PydanticObjectId | None,
        task_id: str | None,
        block_id: str | None = None,
        logging_id: str | None = None,
        va_system_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        # t_ms relative to va_started_at; if not set yet, compute against session creation.
        session = await Session.get(session_id)
        t_ms = session.t_ms_now() if session else 0
        event = Event(
            study_id=study_id,
            session_id=session_id,
            participant_id=participant_id,
            task_id=task_id,
            block_id=block_id,
            logging_id=logging_id,
            va_system_id=va_system_id,
            t_ms=t_ms,
            source=SOURCE_STUDIO,
            type=type,
            meta=meta or {},
        )
        await event.insert()


def _snapshot_of(study: Study) -> tuple[dict, str]:
    """Capture the resolved study at this moment as a plain dict + the hash
    it was loaded under. Stored on the Session so the session's record is
    self-contained even if the study YAML changes later."""
    snap = {
        "slug": study.slug,
        "name": study.name,
        "version": study.version,
        "mode": study.mode,
        "participants_required": study.participants_required,
        "consent_text_md": study.consent_text_md,
        "va_systems": dict(study.va_systems or {}),
        "primary_va_system": study.primary_va_system,
        "roles": list(study.roles or []),
        "advance_policy": study.advance_policy,
        "block_order": getattr(study, "block_order", "declared"),
        "block_orders": list(getattr(study, "block_orders", None) or []),
        "parameters": dict(getattr(study, "parameters", None) or {}),
        "recording": dict(study.recording or {}),
        "ui": dict(study.ui or {}),
        "blocks": list(study.blocks or []),
    }
    return snap, study.yaml_hash or ""


session_manager = SessionManager()


async def _auto_check_callback(session_id: str, task_id: str, step_id: str, source: str) -> None:
    """Bridge auto_check engine → session_manager.record_step_checked.

    Loads the (single, for v0.5 singleplayer) active participant in the
    session, finds the task dict by id, and records the check.
    """
    from beanie import PydanticObjectId
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        return
    session = await Session.get(sid)
    if session is None:
        return
    # Singleplayer assumption (Phase 3): one active participant per session.
    participant = await Participant.find_one(
        Participant.session_id == sid,
        Participant.status == "in_session",
    )
    if participant is None:
        return
    study = await Study.get(session.study_id)
    if study is None:
        return
    task = _find_task(study, task_id)
    if task is None:
        return
    await session_manager.record_step_checked(participant, session, task, step_id, source=source)


def _find_task(study: Study, task_id: str) -> dict[str, Any] | None:
    for block in study.blocks:
        for t in block.get("tasks", []):
            if t.get("id") == task_id:
                return t
    return None


# Wire the in-process auto-check engine to the bridge above.
auto_check.set_callback(_auto_check_callback)
