"""
BaseAgent — Abstract base class for all agents in MIVAIS.

Architectural contract:
  - Agents observe WorldState via watch() callbacks set up in run()
  - Agents write results via world_state.write(self.agent_id, key, value)
  - Agents communicate via message_bus.publish() — never direct calls to other agents
  - Agents never hold references to other agent instances
  - run() is started as an asyncio task at startup; it runs for the lifetime of the process

Required implementation:
  run() — infinite async observation loop

Optional:
  on_message() — called when a bus message arrives on a subscribed topic
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .world_state import WorldState
    from .message_bus import MessageBus


class BaseAgent(ABC):
    """
    Abstract base for MIVAIS agents.

    Agents receive only WorldState and MessageBus at construction time.
    They do NOT receive the full infrastructure layer, other agents, or the Gateway.

    Example:
        class MyAgent(BaseAgent):
            async def run(self) -> None:
                self._ws.watch("input_key", self._on_input)
                await asyncio.Event().wait()  # wait forever

            async def _on_input(self, key: str, value: Any) -> None:
                result = compute(value)
                self._write("output_key", result)
    """

    def __init__(
        self,
        agent_id: str,
        world_state: "WorldState",
        message_bus: "MessageBus",
        params: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._ws = world_state
        self._bus = message_bus
        self.params: dict[str, Any] = params or {}

    @abstractmethod
    async def run(self) -> None:
        """
        Infinite observation loop. Must:
          1. Set up watch() callbacks on relevant WorldState keys (if trigger="watch")
          2. Wait for triggers (asyncio.Event) or sleep (if trigger="poll")
          3. Read needed state via self._read(key)
          4. Compute results
          5. Write results via self._write(key, value)
          6. Handle exceptions internally — this coroutine must never die silently
        """
        ...

    # ── Optional: bus message handler ─────────────────────────────────────────

    async def on_message(self, message: dict) -> None:
        """
        Called when a bus message arrives on a topic this agent subscribed to.
        Default: no-op. Override to react to typed bus messages.
        """
        pass

    # ── helpers ────────────────────────────────────────────────────

    def _read(self, key: str, default: Any = None) -> Any:
        """Read a key from WorldState (permission-checked via PermissionGuard)."""
        return self._ws.read(self.agent_id, key, default)

    def _write(self, key: str, value: Any) -> bool:
        """
        Write a key to WorldState on behalf of this agent.
        PermissionGuard and AuditLog are invoked inside WorldState.write().
        Returns True if accepted, False if denied.
        """
        return self._ws.write(self.agent_id, key, value)

    async def _publish(self, topic: str, payload: dict | None = None) -> None:
        """Publish a typed message on the MessageBus."""
        await self._bus.publish(self.agent_id, topic, payload or {})

    def _subscribe(self, topic: str) -> None:
        """
        Subscribe this agent to a MessageBus topic.
        Routes messages to self.on_message().
        Call this at the start of run() if the agent needs to receive bus messages.
        """
        self._bus.subscribe(self.agent_id, topic, self.on_message)

    @staticmethod
    async def _sleep(seconds: float) -> None:
        """Interruptible sleep. Raises asyncio.CancelledError on shutdown."""
        await asyncio.sleep(seconds)
