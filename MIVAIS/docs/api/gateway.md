# Gateway

WebSocket bridge between the MIVAIS infrastructure and frontend browser clients. The Gateway is the only component in MIVAIS that touches the network. Infrastructure components never send data to clients directly.

Extend this class with a subclass to add domain-specific WebSocket action handling.

## Constructor

```python
Gateway(
    world_state: WorldState,
    audit_log: AuditLog,
    registry: AgentRegistry,
    bus: MessageBus,
    user_configs: dict[str, dict],
    recorder: SessionRecorder | None = None,
)
```

| Parameter | Type | Description |
|---|---|---|
| `world_state` | `WorldState` | The shared blackboard |
| `audit_log` | `AuditLog` | Provenance log for this session |
| `registry` | `AgentRegistry` | Used to register users as agents on connect |
| `bus` | `MessageBus` | Inter-agent message bus |
| `user_configs` | `dict[str, dict]` | Role definitions keyed by role name |
| `recorder` | `SessionRecorder \| None` | Optional session recorder; `None` disables recording |

### `user_configs` format

```python
{
    "analyst": {
        "description": "Full access",
        "can_read": [],
        "can_write": ["user_input"],
        "bus_publish_topics": ["chat.message"],
        "bus_subscribe_topics": ["chat.message", "advisor.insight"],
    },
    "observer": { ... }
}
```

## Class Attributes

### `_broadcast_exclude_keys`

Keys excluded from `state_update` broadcasts. These keys are still included in the `initial_state` message sent on first connect.

```python
class MyGateway(Gateway):
    _broadcast_exclude_keys = frozenset({"dataset", "raw_corpus"})
```

Use this to prevent large, rarely-changing values (e.g. a full dataset) from being re-transmitted on every state change.

**Type:** `frozenset[str]`  
**Default:** `frozenset()` (nothing excluded)

## Connection Lifecycle

### `connect(session_id, websocket, role="analyst")` *(async)*

Accept a new WebSocket connection.

```python
# FastAPI endpoint
@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str, role: str = "analyst"):
    await gateway.connect(session_id, websocket, role=role)
    try:
        while True:
            raw = await websocket.receive_text()
            await gateway.receive_and_apply(session_id, raw)
    except WebSocketDisconnect:
        await gateway.disconnect(session_id)
```

**What happens:**
1. WebSocket accepted.
2. Role resolved from `user_configs` (falls back to first defined role if unknown).
3. User registered in `AgentRegistry` as `user:<session_id>` with role permissions.
4. User subscribed to their permitted bus topics.
5. Full `initial_state` snapshot sent to the newcomer.
6. All other clients receive a `state_update` with updated presence list.

| Parameter | Type | Description |
|---|---|---|
| `session_id` | `str` | Unique identifier for this connection |
| `websocket` | `WebSocket` | FastAPI WebSocket object |
| `role` | `str` | Role name to look up in `user_configs` |

---

### `disconnect(session_id)` *(async)*

Deregister a user and notify remaining clients.

```python
await gateway.disconnect(session_id)
```

**What happens:**
1. Session recorded as disconnected.
2. User unsubscribed from all bus topics.
3. User deregistered from `AgentRegistry`.
4. Cursor and role state cleaned up.
5. All remaining clients receive a `state_update` with updated presence list.

---

### `receive_and_apply(session_id, raw)` *(async)*

Parse a JSON message from the frontend and dispatch it.

```python
raw = await websocket.receive_text()
await gateway.receive_and_apply(session_id, raw)
```

| Parameter | Type | Description |
|---|---|---|
| `session_id` | `str` | The session that sent the message |
| `raw` | `str` | Raw JSON string from the WebSocket |

**Built-in actions:**

| `action` | Payload fields | Description |
|---|---|---|
| `cursor_move` | `row_name`, `x`, `y` | Update cursor position |
| `drag_update` | `dragging`, `drag_over` | Update drag state |
| `chat_message` | `text`, `to` | Publish on `chat.message` bus topic |
| `publish_bus` | `topic`, `payload` | Publish an arbitrary bus message |

Any other `action` value is forwarded to `_handle_action()`.

## Extending the Gateway

### `_handle_action(agent_id, session_id, data)` *(async)*

Override in subclasses to handle domain-specific actions.

```python
from mivais import Gateway

class AppGateway(Gateway):
    _broadcast_exclude_keys = frozenset({"dataset"})

    async def _handle_action(self, agent_id: str, session_id: str, data: dict) -> None:
        action = data.get("action")

        if action == "submit_ranking":
            ranking = data.get("ranking", [])
            if len(ranking) >= 2:
                self._ws.write(
                    agent_id,
                    "user_preference_ranking",
                    {"ranking": [int(i) for i in ranking]},
                    event_type="user_input",
                )

        elif action == "apply_nudges":
            nudges = {k: int(v) for k, v in data.get("nudges", {}).items()}
            self._ws.write(agent_id, "session_nudges", nudges, event_type="user_input")

        elif action == "trigger_rerank":
            current = self._ws.get("rerank_trigger", 0)
            self._ws.write(agent_id, "rerank_trigger", current + 1, event_type="user_input")
```

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The registered agent ID, e.g. `"user:abc123"` |
| `session_id` | `str` | The raw session identifier |
| `data` | `dict` | Parsed JSON payload from the client |

The default implementation is a no-op.

## Configuration Methods

### `reload_user_configs(user_configs)`

Hot-reload user role definitions.

```python
gateway.reload_user_configs(config["users"])
```

Updates the role map used by the next `connect()` call. Does not affect existing connections.

---

### `set_online_agents(agents)`

Register the list of currently running non-user agents.

```python
gateway.set_online_agents([
    {"agent_id": "ranker", "role": "processor", "description": "Computes rankings"},
])
```

This list is included in `initial_state` and `state_update` messages so frontends can display which agents are active.

| Parameter | Type | Description |
|---|---|---|
| `agents` | `list[dict]` | Each dict should have `agent_id`, `role`, `description` |

## Internal State

The Gateway maintains the following in-memory state (not in WorldState):

| Attribute | Description |
|---|---|
| `_connections` | `session_id → WebSocket` |
| `_roles` | `session_id → role` |
| `_cursors` | `"user:<sid>" → {x, y, row_name, dragging, drag_over}` |
| `_chat_history` | Last 100 chat messages (for replay on reconnect) |
| `_online_agents` | List of running non-user agents |

Cursor state is intentionally kept out of WorldState to avoid polluting the audit log with every mouse movement.
