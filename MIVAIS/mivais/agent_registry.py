"""
AgentRegistry — Single source of truth for registered agents and their capabilities.

Populated from a configuration file at startup, or programmatically at runtime.
No agent holds a reference to another agent — they only know agent_ids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCapabilities:
    """
    Everything the infrastructure needs to know about an agent.

    Typically populated from a configuration file at startup.
    Agents never modify their own capabilities at runtime.

    Attributes:
        agent_id:              Unique identifier for this agent.
        role:                  Human-readable role label (e.g. "analyst", "observer").
        description:           Optional description shown in topology views.
        can_read:              WorldState keys this agent may read.
                               Empty list → agent may read all keys (permissive default).
        can_write:             WorldState keys this agent may write.
                               Empty list → agent may write nothing (restrictive default).
        bus_publish_topics:    MessageBus topics this agent may publish on.
                               Empty list → agent may publish on all topics.
        bus_subscribe_topics:  MessageBus topics this agent may subscribe to.
                               Empty list → agent may subscribe to all topics.
        trigger:               Observation strategy: "watch" (event-driven) or "poll".
        poll_interval_seconds: Polling interval when trigger="poll".
        params:                Arbitrary agent-specific parameters passed at construction.
    """
    agent_id: str
    role: str
    description: str = ""

    # World-state access permissions (enforced by PermissionGuard)
    can_read: list[str] = field(default_factory=list)   # empty = read everything
    can_write: list[str] = field(default_factory=list)  # empty = write nothing

    # MessageBus topic permissions
    bus_publish_topics: list[str] = field(default_factory=list)
    bus_subscribe_topics: list[str] = field(default_factory=list)

    # Observation strategy
    trigger: str = "watch"  # "watch" | "poll"
    poll_interval_seconds: float | None = None

    # Arbitrary agent-specific params
    params: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """
    Registers agents and their declared capabilities.

    Agents register themselves at startup by calling register().
    Users connecting via WebSocket are registered dynamically via register_dynamic().
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, AgentCapabilities] = {}
        self._instances: dict[str, Any] = {}  # agent_id → BaseAgent instance

    def register(self, capabilities: AgentCapabilities, instance: Any) -> None:
        """Register an agent with its capabilities and running instance."""
        self._capabilities[capabilities.agent_id] = capabilities
        self._instances[capabilities.agent_id] = instance

    def register_dynamic(self, capabilities: AgentCapabilities) -> None:
        """Register an agent at runtime without a running instance (e.g. a connected user)."""
        self._capabilities[capabilities.agent_id] = capabilities

    def deregister(self, agent_id: str) -> None:
        """Remove a dynamically registered agent (e.g. on user disconnect)."""
        self._capabilities.pop(agent_id, None)
        self._instances.pop(agent_id, None)

    def get(self, agent_id: str) -> AgentCapabilities | None:
        """Return capabilities for an agent_id, or None if not registered."""
        return self._capabilities.get(agent_id)

    def get_instance(self, agent_id: str) -> Any | None:
        """Return the running agent instance, or None."""
        return self._instances.get(agent_id)

    def all_ids(self) -> list[str]:
        """Return all registered agent IDs."""
        return list(self._capabilities.keys())

    def summary(self) -> list[dict]:
        """JSON-serialisable summary of all registered agents."""
        return [
            {
                "agent_id": cap.agent_id,
                "role": cap.role,
                "description": cap.description,
                "can_read": cap.can_read,
                "can_write": cap.can_write,
                "trigger": cap.trigger,
                "poll_interval_seconds": cap.poll_interval_seconds,
                "bus_publish_topics": cap.bus_publish_topics,
                "bus_subscribe_topics": cap.bus_subscribe_topics,
            }
            for cap in self._capabilities.values()
        ]
