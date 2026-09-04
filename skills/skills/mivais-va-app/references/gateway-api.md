# MIVAIS Python library API (`MIVAIS/mivais/*.py`)

This is the shared runtime every VA app composes. You do not subclass most of these —
you construct instances and wire them together; `Gateway` and `BaseAgent` are the two
you do subclass/implement.

## Contents
- [Gateway](#gateway-gatewaypy)
- [WorldState](#worldstate-world_statepy)
- [BaseAgent + AgentRegistry](#baseagent--agentregistry-base_agentpy--agent_registrypy)
- [PermissionGuard](#permissionguard-permission_guardpy)
- [SessionRecorder](#sessionrecorder-session_recorderpy)
- [MivaisConfig](#mivaisconfig-configpy)
- [AuditLog + MessageBus](#auditlog--messagebus)
- [agents_config.yaml example](#agents_configjson-example)

## Gateway (`gateway.py`)

Constructor (`gateway.py:74-96`):

```python
def __init__(
    self,
    world_state: "WorldState",
    audit_log: "AuditLog",
    registry: "AgentRegistry",
    bus: "MessageBus",
    user_configs: dict[str, dict],
    recorder: SessionRecorder | None = None,
    mivais_config: MivaisConfig | None = None,
) -> None: ...
```

`user_configs` is a dict keyed by role name, each entry containing `can_read`,
`can_write`, `bus_subscribe_topics`, `bus_publish_topics`, `description` — this is the
"users" half of `agents_config.yaml`, loaded and passed in by your `main.py`.

**Connection lifecycle** (`gateway.py:139-223`):
- `connect(session_id, websocket, role)` — registers the caller as a dynamic agent in
  `AgentRegistry` with permissions from `user_configs[role]`, sends a full
  `initial_state` message to just this connection, then broadcasts to everyone else.
- `disconnect(session_id)` — deregisters and cleans up.

**Wire message types it sends** (matches the TS client's `types.ts`, see
`frontend-client.md`):
- `initial_state` — full snapshot + audit tail + permissions + chat history + online
  agents (sent once, on connect).
- `state_update` — partial delta + audit tail, broadcast on every `WorldState` write.
- `cursor_update` — cursor-only frame, broadcast on cursor/drag moves.
- `bus_message` — inter-agent/user typed message on a topic.

**Built-in actions handled without any app code** (`gateway.py:237-376`):
| action | what it does |
|---|---|
| `cursor_move` | tracks per-row cursor position (`gateway.py:264-292`), broadcasts `cursor_update` |
| `drag_update` | tracks drag state (`gateway.py:294-305`) |
| `chat_message` | routes to MessageBus topic `chat.message` (`gateway.py:307-324`) |
| `publish_bus` | user publishes on a permitted topic (`gateway.py:326-332`) |
| `replay.push_state` | **Studio-only** — role-gated to `studio_replayer`, used for state injection during replay/task setup (`gateway.py:334-346`) |
| `wizard.act` | **Studio-only** — Wizard-of-Oz state write as a chosen agent, role-gated (`gateway.py:348-359`) |
| `wizard.say` | **Studio-only** — Wizard-of-Oz chat as a chosen agent (`gateway.py:361-375`) |

**Custom actions**: override `async def _handle_action(self, agent_id, session_id,
data)` in a `Gateway` subclass (`gateway.py:380-404`) to add domain-specific WebSocket
actions. Example — PODIUM_V2 adds `set_nudges`, `compute_weights`, `drop_order`,
`rank_all` this way (`PODIUM_V2/backend/main.py:131-145`).

**Broadcast exclusion**: `_broadcast_exclude_keys` (`gateway.py:70-72`) is a frozenset of
large keys (e.g. `dataset`) present in `initial_state` but stripped from every
subsequent `state_update` — configure via `MivaisConfig.broadcast.exclude_keys` so you
don't re-ship a multi-MB dataset on every write.

## WorldState (`world_state.py`)

Free-form dict-backed state — there's no schema class to subclass. You declare your
app's shape implicitly by calling `system_write` at startup.

- `self._state: dict[str, Any]` (`world_state.py:38-47`).
- `get(key, default)` — unchecked read, infrastructure use only.
- `read(agent_id, key, default)` — permission-checked read via `PermissionGuard`
  (`world_state.py:51-76`).
- `snapshot()` / `snapshot_for(agent_id)` — full copy vs. permission-filtered copy.
- `write(agent_id, key, value, event_type)` — permission-checked write; logs to
  `AuditLog`; fires watcher callbacks; returns `True`/`False` (`world_state.py:79-122`).
- `system_write(key, value, actor)` — bypasses `PermissionGuard` entirely. Use this for
  startup seeding and for Studio's replay/wizard actions — never for participant-facing
  writes, since it skips the permission check that makes roles meaningful.
- `watch(key, callback)` — register an async callback fired on every write to that key;
  this is what an agent's `run()` typically does at startup.
- `watch_any(callback)` — fired on every write to any key; this is what `Gateway` uses
  internally to push `state_update` messages.
- Watcher signature: `async def callback(key: str, value: Any) -> None`
  (`world_state.py:126-141`).

## BaseAgent + AgentRegistry (`base_agent.py` / `agent_registry.py`)

**`BaseAgent`** (`base_agent.py:28-109`):
```python
def __init__(self, agent_id: str, world_state: WorldState,
             message_bus: MessageBus, params: dict | None): ...

async def run(self) -> None: ...          # required — set up watch() callbacks here
async def on_message(self, message: dict) -> None: ...  # optional — bus subscriptions
```
Convenience helpers (`base_agent.py:82-109`), all permission-checked through the
agent's own `agent_id`:
- `self._read(key, default)` → `world_state.read(self.agent_id, key, default)`
- `self._write(key, value)` → `world_state.write(self.agent_id, key, value)`
- `self._publish(topic, payload)` → `message_bus.publish(self.agent_id, topic, payload)`
- `self._subscribe(topic)` → routes matching bus messages into `on_message()`

**`AgentCapabilities`** dataclass (`agent_registry.py:13-54`) — the fields you declare
per agent in `agents_config.yaml`:

| field | meaning |
|---|---|
| `agent_id` | unique identifier |
| `role` | human-readable role label |
| `description` | optional |
| `can_read` | WorldState keys readable; empty list = read all |
| `can_write` | WorldState keys writable; empty list = write nothing |
| `bus_publish_topics` | empty = publish on all |
| `bus_subscribe_topics` | empty = subscribe to all |
| `trigger` | `"watch"` (event-driven) or `"poll"` (periodic) |
| `poll_interval_seconds` | interval for polling agents |
| `params` | arbitrary agent-specific config, passed to the constructor |

Note the asymmetry: `can_read`/`bus_subscribe_topics` default *permissive* (empty =
everything), `can_write`/`bus_publish_topics` default *restrictive* (empty = nothing).
Always state both explicitly for a new role rather than relying on the default.

**`AgentRegistry`** (`agent_registry.py:57-110`): `register(capabilities, instance)` for
software agents at startup; `register_dynamic(capabilities)` for human users on
WebSocket connect (no backing instance); `deregister(agent_id)`; `get(agent_id)`;
`get_instance(agent_id)`; `all_ids()`; `summary()` (JSON-serialisable list, what the
frontend's `onlineAgents` comes from).

## PermissionGuard (`permission_guard.py`)

- `can_write(agent_id, key)` (`permission_guard.py:28-36`) — `True` iff `key` in the
  agent's `can_write`; unknown agents denied by default.
- `readable_keys(agent_id, all_keys)` (`permission_guard.py:38-48`) — filters to the
  agent's `can_read` (empty = permissive, read all).
- `can_publish` / `can_subscribe` (`permission_guard.py:50-68`) — same pattern for bus
  topics.

## SessionRecorder (`session_recorder.py`)

- Constructor `__init__(recordings_dir: Path)` (`session_recorder.py:34-40`) creates
  `session_{YYYYMMDD_HHMMSS}.jsonl` inside `recordings_dir` immediately, and starts
  appending. **This filename pattern is load-bearing** — Studio's JSONL tailer (spawned
  mode only) looks for exactly this pattern.
- Event types recorded (`session_recorder.py:8-14`): `snapshot` (full state, once, on
  first connect), `state_update`, `cursor_update` (throttled ≤20fps), `connect`,
  `disconnect`, `bus_message`, `user_action`.
- You rarely call this directly — `Gateway` calls `record`/`record_cursors`/
  `record_state` (`session_recorder.py:44-84`) for you at the right moments.

## MivaisConfig (`config.py`)

Dataclass (`config.py:56-86`): `ChatConfig(enabled, history_size)`,
`CursorConfig(enabled)`, `AuditConfig(enabled, recording_dir)`,
`BroadcastConfig(exclude_keys)`. Load with `MivaisConfig.load(path)` (missing keys fall
back to defaults) or `MivaisConfig.default()`.

Example `mivais_config.yaml` (`config.py:9-24`):
```yaml
chat:
  enabled: true
  history_size: 50
cursors:
  enabled: true
audit:
  enabled: true
  recording_dir: recordings
broadcast:
  exclude_keys:
  - dataset
```

## AuditLog + MessageBus

**AuditLog** (`audit_log.py:57-105`) — append-only, immutable, no `clear()`. Records
every write attempt (accepted or denied) and every bus message. `record(actor, key,
value, accepted, event_type)`, `record_bus_message(sender, topic, payload)`,
`get_entries(limit)`.

**MessageBus** (`message_bus.py:45-118`) — typed async pub/sub, keyed by topic (not
sender). `subscribe(agent_id, topic, handler)`, `publish(sender, topic, payload)`
(auto-logs to `AuditLog` with `event_type="bus_message"`), `unsubscribe(agent_id,
topic)`. Fire-and-forget: publishers don't await subscriber responses.

## `agents_config.yaml` example

```yaml
users:
- role: analyst
  can_read: []
  can_write:
  - selected_attributes
  bus_publish_topics:
  - chat.message
  bus_subscribe_topics:
  - chat.message
agents:
- agent_id: insight_agent
  role: advisor
  class: InsightAgent
  can_read:
  - dataset
  - selected_attributes
  can_write:
  - insight
  bus_publish_topics:
  - chat.message
  bus_subscribe_topics: []
  trigger: watch
```

(`class` names an agent implementation class your `main.py` loads and instantiates;
this key isn't consumed by the library itself, just by your own loader loop —
`PODIUM_V2/backend/main.py:79-90` and `ProactiveVA/backend/main.py:57-69` both do this.)
