# API Overview

MIVAIS exposes seven infrastructure components and one abstract base class. All public symbols are importable directly from the `mivais` package:

```python
from mivais import (
    AuditLog,
    AuditEntry,
    AgentRegistry,
    AgentCapabilities,
    PermissionGuard,
    WorldState,
    MessageBus,
    BusMessage,
    Gateway,
    SessionRecorder,
    BaseAgent,
)
```

## Component Summary

| Class | Module | Description |
|---|---|---|
| [`WorldState`](/api/world-state) | `mivais.world_state` | Central shared blackboard |
| [`MessageBus`](/api/message-bus) | `mivais.message_bus` | Typed async pub/sub |
| [`AgentRegistry`](/api/agent-registry) | `mivais.agent_registry` | Capabilities registry |
| [`AgentCapabilities`](/api/agent-registry#agentcapabilities) | `mivais.agent_registry` | Dataclass for agent metadata |
| [`PermissionGuard`](/api/permission-guard) | `mivais.permission_guard` | Runtime access control |
| [`AuditLog`](/api/audit-log) | `mivais.audit_log` | Immutable provenance record |
| [`AuditEntry`](/api/audit-log#auditentry) | `mivais.audit_log` | Single audit record |
| [`Gateway`](/api/gateway) | `mivais.gateway` | WebSocket bridge |
| [`SessionRecorder`](/api/session-recorder) | `mivais.session_recorder` | JSONL session recording |
| [`BaseAgent`](/api/base-agent) | `mivais.base_agent` | Abstract agent base class |

## Construction Order

The six infrastructure singletons have dependencies. Construct them in this order:

```python
from mivais import (
    AuditLog, AgentRegistry, PermissionGuard,
    WorldState, MessageBus, Gateway, SessionRecorder,
)

audit    = AuditLog()
registry = AgentRegistry()
guard    = PermissionGuard(registry)       # needs registry
state    = WorldState(audit, guard)        # needs audit + guard
bus      = MessageBus(audit)              # needs audit
recorder = SessionRecorder(Path("recordings/"))
gateway  = Gateway(state, audit, registry, bus, user_configs, recorder)
```

`AgentRegistry` and `AuditLog` have no dependencies and can be constructed in any order.

## WebSocket Message Protocol

The Gateway communicates with frontend clients via JSON messages over WebSocket.

### Incoming (client → server)

| `action` | Built-in | Description |
|---|---|---|
| `cursor_move` | Yes | Update cursor position: `{row_name, x, y}` |
| `drag_update` | Yes | Update drag state: `{dragging, drag_over}` |
| `chat_message` | Yes | Publish a chat message: `{text, to}` |
| `publish_bus` | Yes | Publish on the bus: `{topic, payload}` |
| `*` | No | Any other action is forwarded to `_handle_action()` |

### Outgoing (server → client)

| `type` | Description |
|---|---|
| `initial_state` | Full snapshot on connect, includes `my_permissions`, `chat_history`, `online_agents` |
| `state_update` | Incremental snapshot after any WorldState write |
| `cursor_update` | Lightweight cursor/presence update (no WorldState) |
| `bus_message` | A bus message delivered to this client's subscribed topics |

### State Update Envelope

```json
{
  "type": "state_update",
  "world_state": { ... },
  "audit_log": [ ... ],
  "cursors": { "user:abc": { "x": 0.4, "y": 0.6, "row_name": "Item A" } },
  "connected_users": [ { "session_id": "abc", "role": "analyst" } ],
  "online_agents": [ { "agent_id": "ranker", "role": "processor" } ]
}
```

### Initial State Envelope

Same as state_update, plus:

```json
{
  "my_permissions": {
    "role": "analyst",
    "can_write": ["user_input"],
    "bus_publish_topics": ["chat.message"]
  },
  "chat_history": [ ... ],
  "online_agents": [ ... ]
}
```
