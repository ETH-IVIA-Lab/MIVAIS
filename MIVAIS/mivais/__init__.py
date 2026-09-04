"""
MIVAIS — Mixed-Initiative Visual Analytics Infrastructure System.

A governance layer for building collaborative, multi-agent visual analytics systems.

Core components:
  WorldState       — Central shared blackboard
  MessageBus       — Typed async pub/sub between agents
  AgentRegistry    — Capabilities registry and instance store
  PermissionGuard  — Runtime access-control enforcement
  AuditLog         — Immutable provenance record
  Gateway          — WebSocket bridge (extend to add domain actions)
  SessionRecorder  — JSONL session recording for replay
  BaseAgent        — Abstract base class for all agents
  Rooms            — Multi-room hosting (Room, RoomManager, attach_room_routes)

Typical startup sequence:

    from mivais import (
        AuditLog, AgentRegistry, PermissionGuard,
        WorldState, MessageBus, Gateway, SessionRecorder,
    )

    audit   = AuditLog()
    registry = AgentRegistry()
    guard   = PermissionGuard(registry)
    state   = WorldState(audit, guard)
    bus     = MessageBus(audit)
    gateway = Gateway(state, audit, registry, bus, user_configs={...})
"""

from .audit_log import AuditLog, AuditEntry
from .agent_registry import AgentRegistry, AgentCapabilities
from .permission_guard import PermissionGuard
from .world_state import WorldState
from .message_bus import MessageBus, BusMessage
from .gateway import Gateway
from .session_recorder import SessionRecorder
from .base_agent import BaseAgent
from .config import MivaisConfig
from .rooms import (
    Room,
    RoomApp,
    RoomManager,
    attach_room_routes,
    create_room_app,
    load_agents_config,
    watch_agents_config,
)

__all__ = [
    "AuditLog",
    "AuditEntry",
    "AgentRegistry",
    "AgentCapabilities",
    "PermissionGuard",
    "WorldState",
    "MessageBus",
    "BusMessage",
    "Gateway",
    "SessionRecorder",
    "BaseAgent",
    "MivaisConfig",
    "Room",
    "RoomApp",
    "RoomManager",
    "attach_room_routes",
    "create_room_app",
    "load_agents_config",
    "watch_agents_config",
]

__version__ = "1.0.0"
