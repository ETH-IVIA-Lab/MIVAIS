"""
WorldState - Central shared blackboard for MIVAIS.

"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .audit_log import AuditLog
from .permission_guard import PermissionGuard

# Async callback type: receives (key, new_value)
WatchCallback = Callable[[str, Any], Awaitable[None]]


class WorldState:
    """
    Central blackboard.

    Usage:
      world_state.system_write("dataset", records)       # at startup
      world_state.watch("user_ranking", my_callback)     # agent sets up observation
      world_state.write("my_agent", "result", {...})     # agent writes result
      world_state.snapshot()                             # gateway reads full state
    """

    def __init__(
        self,
        audit_log: AuditLog,
        permission_guard: PermissionGuard,
    ) -> None:
        self._state: dict[str, Any] = {}
        self._watchers: dict[str, list[WatchCallback]] = {}  # key → callbacks
        self._global_watchers: list[WatchCallback] = []       # fired on any write
        self._audit = audit_log
        self._guard = permission_guard

    # ── Reads ──────────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Read any key (unchecked). Used by infrastructure (Gateway, system)."""
        return self._state.get(key, default)

    def read(self, agent_id: str, key: str, default: Any = None) -> Any:
        """
        Permission-checked read for agents.

        """
        readable = self._guard.readable_keys(agent_id, [key])
        if key not in readable:
            return default
        return self._state.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        """Full copy of current state. Used by the Gateway for WebSocket push."""
        return dict(self._state)

    def snapshot_for(self, agent_id: str) -> dict[str, Any]:
        """Permission-filtered snapshot - only keys declared in agent's can_read."""
        readable = self._guard.readable_keys(agent_id, list(self._state.keys()))
        return {k: self._state[k] for k in readable}

    # ── Writes ─────────────────────────────────────────────────────────────────

    def write(self, agent_id: str, key: str, value: Any, event_type: str = "write") -> bool:
        """
        Write a value on behalf of agent_id.

        Steps:
          1. PermissionGuard.can_write() - reject if not authorised
          2. AuditLog.record() with accepted=True/False
          3. Apply write to internal dict
          4. Schedule watcher notifications (non-blocking asyncio task)

        Returns True if the write was accepted, False if denied.
        The optional event_type overrides the audit log label (e.g. "user_input").
        """
        allowed = self._guard.can_write(agent_id, key)
        self._audit.record(
            actor=agent_id,
            key=key,
            value=value if allowed else "[DENIED]",
            accepted=allowed,
            event_type=event_type if allowed else "denied",
        )
        if not allowed:
            return False
        self._state[key] = value
        self._schedule_notify(key, value)
        return True

    def system_write(self, key: str, value: Any, actor: str = "system") -> None:
        """
        Infrastructure-level write that bypasses permission checks.
        Used at startup (initial data loading) and by the Gateway for system state.
        Logged with actor='system' by default; pass ``actor`` to attribute the
        write to a specific agent, so it shows up correctly in the audit log and per-agent 
        replay lanes.
        """
        self._audit.record(
            actor=actor,
            key=key,
            value=value,
            accepted=True,
            event_type="write",
        )
        self._state[key] = value
        self._schedule_notify(key, value)

    # ── Watching ───────────────────────────────────────────────────────────────

    def watch(self, key: str, callback: WatchCallback) -> None:
        """
        Register an async callback to be called whenever `key` is written.

        Agents call this in their run() setup phase.
        The callback receives (key, new_value).
        Multiple agents may watch the same key — all callbacks are called.
        """
        self._watchers.setdefault(key, []).append(callback)

    def watch_any(self, callback: WatchCallback) -> None:
        """
        Register an async callback that fires on every write of any key.
        Used by the Gateway to push state updates to WebSocket clients.
        """
        self._global_watchers.append(callback)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _schedule_notify(self, key: str, value: Any) -> None:
        """Schedule watcher notifications as a non-blocking asyncio task."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify(key, value))
        except RuntimeError:
            pass  # no running loop (e.g., during tests)

    async def _notify(self, key: str, value: Any) -> None:
        """Fire all registered watchers for `key` and all global watchers."""
        for cb in list(self._watchers.get(key, [])):
            try:
                await cb(key, value)
            except Exception as exc:
                print(f"[world_state] watcher error (key={key!r}): {exc}")
        for cb in list(self._global_watchers):
            try:
                await cb(key, value)
            except Exception as exc:
                print(f"[world_state] global watcher error (key={key!r}): {exc}")
