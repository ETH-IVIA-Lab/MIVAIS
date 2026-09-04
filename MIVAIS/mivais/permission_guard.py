"""
PermissionGuard — Runtime enforcement of agent read/write boundaries.

Every WorldState.write() call passes through can_write().
The Gateway uses readable_keys() to filter per-agent snapshots.

Permission model:
  can_read  = []  →  agent may read all keys  (permissive read default)
  can_write = []  →  agent may write nothing  (restrictive write default)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_registry import AgentRegistry


class PermissionGuard:
    """
    Single source of truth for what each agent is permitted to read and write.
    Backed by AgentRegistry, which is populated from configuration at startup.
    """

    def __init__(self, registry: "AgentRegistry") -> None:
        self._registry = registry

    def can_write(self, agent_id: str, key: str) -> bool:
        """
        Return True if agent_id has declared `key` in its can_write list.
        Unknown agents are denied by default.
        """
        cap = self._registry.get(agent_id)
        if cap is None:
            return False
        return key in cap.can_write

    def readable_keys(self, agent_id: str, all_keys: list[str]) -> list[str]:
        """
        Filter `all_keys` to the subset the agent is permitted to read.
        If can_read is empty, all keys are returned (permissive default).
        """
        cap = self._registry.get(agent_id)
        if cap is None:
            return []
        if not cap.can_read:
            return list(all_keys)
        return [k for k in all_keys if k in cap.can_read]

    def can_publish(self, agent_id: str, topic: str) -> bool:
        """
        Return True iff agent_id may publish on `topic` via the MessageBus.
        Empty bus_publish_topics - agent may publish on all topics.
        """
        cap = self._registry.get(agent_id)
        if cap is None:
            return False
        return not cap.bus_publish_topics or topic in cap.bus_publish_topics

    def can_subscribe(self, agent_id: str, topic: str) -> bool:
        """
        Return True iff agent_id may subscribe to `topic` on the MessageBus.
        Empty bus_subscribe_topics - agent may subscribe to all topics.
        """
        cap = self._registry.get(agent_id)
        if cap is None:
            return False
        return not cap.bus_subscribe_topics or topic in cap.bus_subscribe_topics
