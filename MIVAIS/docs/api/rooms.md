# Rooms

Generic multi-room hosting for MIVAIS applications (`mivais.rooms`). One process hosts many isolated worlds ("rooms"), one per `?room=<id>` query param on the WebSocket / page URL. Each room owns its own [WorldState](/api/world-state), [AuditLog](/api/audit-log), [MessageBus](/api/message-bus), [AgentRegistry](/api/agent-registry), agent tasks and [SessionRecorder](/api/session-recorder), so two participants on the same host never share state unless they share a room id.

MIVAIS Studio sets the room to the participant's session id — a private world per participant in singleplayer, one shared world per cohort in multiplayer. Rooms are created lazily on the first WebSocket connect and disposed after an idle timeout with no connections, so a participant who refreshes mid-task rejoins the same world.

A complete backend is **one call**:

```python
from pathlib import Path
from mivais.rooms import Room, create_room_app

def seed(room: Room, params: dict) -> None:
    room.world_state.system_write("dataset", DATASET)

va = create_room_app(
    title="My VA (MIVAIS)",
    base_dir=Path(__file__).parent,   # agents_config.yaml (+ mivais_config.yaml) live here
    gateway_cls=MyGateway,            # your Gateway subclass (_handle_action)
    agent_classes=AGENT_CLASSES,      # class-name or agent_id → class
    seed=seed,
    env_prefix="MYVA",                # MYVA_DEFAULT_ROOM, MYVA_ROOM_IDLE_TIMEOUT
)
app, rooms = va.app, va.rooms         # extra REST routes go on `app`
```

The application keeps only what is genuinely its own: the Gateway subclass, the agent classes, the initial WorldState seed, and any extra REST routes. The lower-level pieces (`Room`, `RoomManager`, `attach_room_routes`, `load_agents_config`) stay public for custom wiring.

## `create_room_app(...)`

Builds the whole app: loads `<base_dir>/agents_config.yaml` (both dialects) and `mivais_config.yaml` (if present), reads `{env_prefix}_DEFAULT_ROOM` / `{env_prefix}_ROOM_IDLE_TIMEOUT` from the environment, derives the recordings dir from the config, wires the `RoomManager` + lifespan, and attaches every standard route. Returns a `RoomApp` with `.app`, `.rooms`, `.user_configs`, `.agent_configs`, `.mivais_config`, `.recordings_dir`, `.default_room`.

| Parameter | Description |
|---|---|
| `title`, `version` | FastAPI metadata |
| `base_dir` | The backend directory — configs and recordings live here |
| `gateway_cls`, `agent_classes`, `seed`, `room_cls` | Your app's pieces (see `Room` below) |
| `env_prefix` | Env-var prefix, e.g. `"VOYAGER"` |
| `frontend_dir` | Defaults to `<base_dir>/../frontend` |
| `bus_record_exclude_topics` | Bus topics kept out of the session recording |
| `cors` | Add a permissive CORS middleware |
| `watch_config` | Hot-reload `agents_config.yaml` into live rooms (needs `watchfiles`) |
| `on_config_reload` | Called with the raw reloaded JSON — for app-specific sections (e.g. PODIUM's `infrastructure` block) |

## Functions

### `load_agents_config(path)`

Parse `agents_config.yaml` into `(user_configs, agent_configs)`.

```python
user_configs, agent_configs = load_agents_config(HERE / "agents_config.yaml")
```

Accepts both user-section dialects found in MIVAIS applications:

- `"users": [ {"role": "analyst", ...}, ... ]` — list of role objects
- `"roles": { "analyst": {...}, ... }` — map keyed by role name

Either reduces to the `role → capability dict` mapping the [Gateway](/api/gateway) expects. `agent_configs` is the raw `"agents"` list.

---

### `capabilities_from_config(cfg)`

Build an [`AgentCapabilities`](/api/agent-registry) from one agent config entry. Accepts both the flat layout (`can_read` at the top level) and the nested one (`observation.can_read` / `actions.can_write` / `bus.publish_topics`). See the [configuration grammars](/reference/grammars) for both dialects.

---

### `safe_room_dir(room_id)`

Filesystem-safe folder name for a room's recordings (alphanumerics, `-`, `_`; max 64 chars; falls back to `"room"`).

---

### `attach_room_routes(app, manager, *, default_room="default", default_role="analyst", frontend_dir=None)`

Attach the routes every hosted MIVAIS VA serves:

| Route | Description |
|---|---|
| `WS /ws/{session_id}?room=&role=&…` | Real-time channel. **All** query params are forwarded to the room factory, so an app can consume extra ones (e.g. Voyager's `?dataset=`) without new endpoint code. |
| `GET /` | The built frontend (`<frontend_dir>/dist/index.html`), plus `/assets` static mount. |
| `GET /audit?room=&limit=` | Recent audit entries. Never creates a room. |
| `GET /agents?room=` | Registered agents with capabilities (registry summary). |
| `GET /users` | Role definitions — read live from `user_configs`, so hot-reload shows up. |
| `GET /recordings`, `GET /recordings/{file}` | List / download session JSONL recordings (if `recordings_dir` given). |
| `GET /log?room=` | Zero-dependency HTML audit-log viewer (disable with `audit_viewer=False`). |

## Room

One fully-isolated MIVAIS world: its own infrastructure septet, agents and recorder.

### Constructor

```python
Room(
    room_id: str,
    *,
    gateway_cls: type[Gateway] = Gateway,
    agent_classes: dict[str, type] | None = None,
    user_configs: dict[str, dict] | None = None,
    agent_configs: list[dict] | None = None,
    mivais_config: MivaisConfig | None = None,
    recordings_dir: str | Path | None = None,
    seed: Callable[[Room, dict], None] | None = None,
    params: dict | None = None,
    gateway_kwargs: dict | None = None,
    bus_record_exclude_topics: Iterable[str] = (),
)
```

| Parameter | Description |
|---|---|
| `gateway_cls` | Your [Gateway](/api/gateway) subclass; receives the standard constructor kwargs |
| `agent_classes` | Agent lookup map — keyed by config `class` name (PODIUM dialect) or by `agent_id` (flat dialect) |
| `agent_configs` | The `"agents"` list from `load_agents_config` |
| `mivais_config` | Optional [MivaisConfig](/guide/configuration); recording is skipped when `audit.enabled` is false |
| `recordings_dir` | Recordings root; each room records into `<dir>/<safe_room_dir(room_id)>/` |
| `seed` | Called as `seed(room, params)` before agents start — write the initial WorldState here |
| `params` | The query params of the WebSocket connect that created the room |

Agent constructors are called with `agent_id`, `world_state`, `message_bus`, and — only if the class accepts it — `params`.

### Attributes

`room_id`, `params`, `audit_log`, `registry`, `guard`, `world_state`, `bus`, `recorder`, `gateway`, and `connection_count` (live WebSocket count from the gateway).

### Methods

- **`await start()`** — seed the WorldState, register and start every enabled agent, publish the agent roster to clients. Idempotent.
- **`await stop()`** — cancel agent tasks and close the recorder.
- **`reload_config(new_user_cfgs, new_agent_cfgs)`** — apply a hot-reloaded config to the live room: user roles are swapped wholesale, each known agent's capabilities are patched in place, and agents that define `on_config_reload(params)` get their new params. Driven by `watch_agents_config`.

Bus messages published inside a room are written to its session recording as `bus_message` events (so agent-to-agent traffic shows up in the Studio replay timeline); `bus_record_exclude_topics` keeps high-volume telemetry topics out.

## RoomManager

Owns the live rooms and reaps idle ones.

### Constructor

```python
RoomManager(factory: Callable[[str, dict], Room], *, idle_timeout_s: float = 300.0)
```

`factory(room_id, params)` builds a room; `params` are the query params of the WebSocket connect that **created** the room. Later joiners share the existing world regardless of their own params — first-come semantics, matching the room id itself.

### Methods

- **`await get_or_create(room_id, params=None)`** — return the live room, creating and starting it if needed; cancels any pending disposal.
- **`peek(room_id)`** — the live room or `None`; never creates one (use for health checks and REST reads).
- **`all()`** — list of all live rooms (used e.g. by PODIUM's hot-reload to patch every room).
- **`schedule_dispose_if_idle(room_id)`** — call after a disconnect; the room is stopped after `idle_timeout_s` seconds with zero connections.
- **`await stop_all()`** — tear down every room (shutdown).
- **`lifespan(recordings_dir=None, extra=None, background=())`** — returns a FastAPI lifespan handler that ensures the recordings dir exists, awaits an optional `extra()` startup hook, starts each `background` coroutine as a task (cancelled on shutdown), and calls `stop_all()` on shutdown.

## Config hot-reload

### `watch_agents_config(cfg_path, manager, user_configs, agent_configs, on_reload=None)`

Async task (usually started via `create_room_app(watch_config=True)`) that watches `agents_config.yaml` and, on every save, updates the passed `user_configs` / `agent_configs` containers **in place** (so new rooms pick the change up) and calls `Room.reload_config` on every live room. `on_reload(raw_json)` handles app-specific config sections. Requires `watchfiles`; without it, hot-reload is silently disabled.

## Who uses it

`PODIUM_V2`, `Voyager2_VA` and `ProactiveVA` all build their backends on this module. `Starter_VA` deliberately wires the infrastructure by hand — it is the pedagogical example in the [Building a System](/guide/building) guide.
