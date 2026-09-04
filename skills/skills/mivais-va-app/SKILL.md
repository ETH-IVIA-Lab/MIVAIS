---
name: mivais-va-app
description: Guide for building a new MIVAIS-based visual-analytics (VA) application from scratch, or retrofitting an existing visualization/dashboard app to integrate with the MIVAIS infrastructure — the shared Gateway/WorldState/agent runtime used by PODIUM_V2, Voyager2_VA, ProactiveVA, and Starter_VA. Use this whenever the user wants to build, scaffold, wire up, or retrofit a VA app for MIVAIS; mentions the MIVAIS Gateway, WorldState, mivais-va-client, or agents_config.yaml; wants to add mixed-initiative / background-agent behavior to a visualization so it reacts to what the analyst does; or wants to hook a new or existing app into MIVAIS Studio for a user study (`external: true` va_systems, `va_interaction` tasks, embedding in an iframe). Trigger even when the user doesn't say "MIVAIS" explicitly — e.g. "I want an agent that watches what the user selects and writes an insight", "how do I get my dashboard to show up in Studio", "add real-time multi-user sync to my visualization tool".
---

# Building or retrofitting a MIVAIS visual-analytics (VA) app

## The three layers — don't confuse them

1. **`MIVAIS/`** — the shared Python runtime library (`Gateway`, `WorldState`, agents,
   permissions, recording). Every VA app depends on it via `pip install -e <path-to-MIVAIS>`.
   You don't modify this library to build a new app; you *compose* it.
2. **Your VA app** — a FastAPI (or similar) backend + a frontend (React or plain JS/SVG)
   that wires up the library and adds the domain-specific visualization, dataset, and
   agents. This is what you're building or retrofitting. `PODIUM_V2`, `Voyager2_VA`,
   `ProactiveVA` are production-shaped examples; `Starter_VA` is the deliberately tiny
   one (see `references/reference-apps.md` for a side-by-side).
3. **`studio/`** — MIVAIS Studio, the separate study-runner platform that spawns or
   embeds your VA app for participants, drives task flow, and records everything. You
   don't need to touch Studio's code to build a VA app — you only need to satisfy its
   integration contract at the end (a study-YAML `va_systems` entry) so it can find and
   embed you.

Keep these separate in your head: a bug in "my agent doesn't react" is almost always in
layer 2 (your `agents_config.yaml` / your agent's `run()`), never in layer 1 or 3.

## Decide two things before writing code

**New app or retrofit?** Retrofitting means adding the Gateway/WorldState/WebSocket
layer *beside* an existing visualization's rendering code, not replacing it — your
existing charts/maps/tables keep doing their own rendering; they just read from
`worldState` instead of local component state, and write through `sendAction`/`_write`
instead of local `setState`/mutation.

**Deployed mode: external vs. spawned?** This determines how much scaffolding you need.
- **External** (long-running hosted service, like PODIUM_V2/Voyager2_VA in production):
  Studio embeds you via iframe and pushes state over a short-lived WebSocket call; you
  need multi-room support (one process serves many concurrent study sessions), a
  Dockerfile, and — if you want it CI-built — a `.gitlab-ci.yml` matrix entry.
- **Spawned** (Studio launches your process per session as a subprocess, like
  `Starter_VA` / local dev): single global `WorldState`, no multi-room logic, no
  Dockerfile needed. Read `STUDIO_VA_PORT`/`STUDIO_VA_RECORDING_DIR` env vars for your
  port and recording directory.

If genuinely unsure which the user wants, ask — it changes the shape of `main.py`
significantly (see `references/reference-apps.md` for both patterns side by side).

## Build steps

### 1. Backend: wire the Gateway

Install MIVAIS editable (`pip install -e /path/to/MIVAIS`), then construct the six
infrastructure pieces and hand them to `Gateway`:

```python
audit_log = AuditLog()
registry = AgentRegistry()
guard = PermissionGuard(registry)
world_state = WorldState(audit_log=audit_log, permission_guard=guard)
bus = MessageBus(audit_log=audit_log)
recorder = SessionRecorder(recordings_dir)
gateway = Gateway(world_state, audit_log, registry, bus, user_configs,
                   recorder=recorder, mivais_config=mivais_config)
```

For external/multi-room apps, this whole block lives inside a per-room factory keyed by
a `?room=<id>` query parameter, created lazily on first WebSocket connect and reaped
after an idle timeout — see `references/reference-apps.md` for the exact pattern all
three hosted apps share. For spawned apps it's one global set of objects at import time.

Register a WebSocket route that forwards `connect`/`disconnect`/action-handling to the
gateway, and seed the dataset/initial state via `world_state.system_write(key, value)`
(bypasses permission checks — use it for infra-level setup, not participant actions).

If your app needs actions beyond the built-ins (`cursor_move`, `drag_update`,
`chat_message`, `publish_bus`, plus Studio's `replay.push_state`/`wizard.act`/
`wizard.say`), subclass `Gateway` and override `_handle_action(agent_id, session_id,
data)` — this is how PODIUM_V2 adds `set_nudges`, `compute_weights`, `drop_order`,
`rank_all`.

Full constructor signatures, method list, and the WorldState/PermissionGuard/
SessionRecorder API → **`references/gateway-api.md`**.

### 2. Declare roles and agents

Write `agents_config.yaml` — one vocabulary for both human roles (`users`) and software
agents (`agents`), each declaring `can_read`/`can_write` WorldState keys and
`bus_publish_topics`/`bus_subscribe_topics`. An empty list for `can_read` or
`bus_subscribe_topics` means "no restriction" (permissive default); an empty
`can_write`/`bus_publish_topics` means "nothing" (restrictive default) — this asymmetry
trips people up, so state each role's permissions explicitly rather than relying on the
default. Optionally write `mivais_config.yaml` to toggle chat/cursors/audit and to list
`broadcast.exclude_keys` (large keys like a full dataset that should ship once in
`initial_state` but not on every `state_update`).

Schema + examples → **`references/gateway-api.md`**.

### 3. Write agents (only if you want mixed-initiative behavior)

An agent is optional — plenty of valid VA apps have `agents: []` and are pure
multi-user-sync tools. If you want the "agent observes → agent acts" loop (like
Starter_VA's `InsightAgent`, or ProactiveVA's detector/planner agents), subclass
`BaseAgent`, implement `async def run()`, and inside it call `self.watch(key,
callback)` (or `world_state.watch_any(...)`) to react to writes, using
`self._read`/`self._write`/`self._publish` for permission-checked I/O. Agents declared
with `"trigger": "poll"` in `agents_config.yaml` run on a timer instead of purely
event-driven — use this for periodic checks that aren't triggered by a specific key
write.

API details → **`references/gateway-api.md`**.

### 4. Frontend: use `mivais-va-client`

Add the workspace package as a dependency (`packages/mivais-va-client`), then wrap your
app in the React context provider (`createMivaisContext`) or use `MivaisSocket`
directly if you're not on React (Starter_VA is vanilla JS). This gives you
`worldState`, `sendAction`, `sendCursor`, `sendChat`, `canWrite`/`canPublish` gating, and
— critically for Studio embedding — the **harness bridge**: the provider automatically
relays state updates and user/agent actions to the parent window via `postMessage`,
which is what lets Studio's participant page and replay viewer observe your app
without you writing any Studio-specific code.

Full API (message types, hooks, harness contract) → **`references/frontend-client.md`**.

### 5. Recording comes free

`SessionRecorder` writes `session_{YYYYMMDD_HHMMSS}.jsonl` to your recordings directory
automatically on every state/cursor/bus/connect event — you don't call it directly
except via the Gateway. This filename pattern matters only for **spawned** apps: Studio's
JSONL tailer expects it and tails the newest file in the directory it configured via
`STUDIO_VA_RECORDING_DIR`. External apps skip the tailer entirely (Studio isn't
co-located with you, so there's no local file for it to read) — your recording still
happens locally for your own debugging, but Studio's event log comes from the state
pushes it makes to you, not from tailing your file.

### 6. Wire into Studio

Add a `va_systems` entry to a study YAML. For a spawned VA:

```yaml
va_systems:
  my_va:
    system: my_va
    cwd: /path/to/my-va/backend
    spawn_cmd: python -m uvicorn main:app --port {port} --log-level warning
    iframe_url: http://127.0.0.1:{port}/
    health_check_url: http://127.0.0.1:{port}/state
```

For an external/hosted VA:

```yaml
va_systems:
  my_va:
    system: my_va
    external: true
    iframe_url: "https://my-va.example.com/"
    health_check_url: "https://my-va.example.com/state"
    room_per_session: true   # appends ?room=<session_id> and forwards it to state pushes
```

Then reference it from a `va_interaction` task in the study's task list, with a
`world_state.mode: replace|continue` block to seed/reset state at task start and an
`answer.type: capture_state` to record which WorldState key is the scored answer.

Full `VAConfig`/`va_interaction` schema and Studio's push contract (what URLs/payloads
it calls on you) → **`references/studio-integration.md`**.

### 7. Package for deployment (external/hosted route only)

Follow the multi-stage Dockerfile pattern (Node frontend-build stage → Python backend
stage) shared by `PODIUM_V2`, `Voyager2_VA`, `ProactiveVA`. **Check
`.gitlab-ci.yml` before assuming CI builds your image** — as of this writing only
`studio` is wired into the `build:image` matrix; the three reference VA apps have
Dockerfiles but must be built/deployed manually (or you extend the CI matrix yourself)
unless that's changed since.

Dockerfile pattern + CI caveat → **`references/reference-apps.md`**.

## Verification checklist

Before calling a new/retrofitted VA app done, confirm:

- [ ] Two browser tabs connecting with the same `session_id` (and `room`, if
      multi-room) see each other's writes as `state_update` messages in real time.
- [ ] A role without a key in `can_write` gets that write rejected (check
      `myPermissions`/`canWrite` client-side, and that the server actually denies it —
      client-side gating alone isn't enforcement).
- [ ] If you wrote an agent: it visibly reacts (writes state / posts chat) within its
      `watch()`ed key shortly after a manual test write to that key.
- [ ] A `session_*.jsonl` file appears in the recordings directory with one line per
      event (spawned mode only — see step 5).
- [ ] Health endpoint (whatever `health_check_url` points at, e.g. `/state`) returns 200
      before you ask Studio to embed the app.
- [ ] Spawned mode: your app actually reads `STUDIO_VA_PORT`/`STUDIO_VA_RECORDING_DIR`
      (or whatever env vars your `spawn_cmd` implies) rather than hardcoding a port.

## Reference files

- **`references/gateway-api.md`** — full Python library API: `Gateway`, `WorldState`,
  `BaseAgent`/`AgentRegistry`, `PermissionGuard`, `SessionRecorder`, `MivaisConfig`,
  `AuditLog`/`MessageBus`, with `agents_config.yaml`/`mivais_config.yaml` examples and
  file:line citations into `MIVAIS/mivais/*.py`.
- **`references/frontend-client.md`** — `mivais-va-client` TS API: `MivaisSocket`, the
  wire protocol (`initial_state`/`state_update`/`cursor_update`/`bus_message`), the
  harness postMessage bridge, REST helpers, and the React context/hook.
- **`references/studio-integration.md`** — how Studio talks to a VA (the
  `push_world_state`/`send_wizard_action` contract), the full `VAConfig` YAML schema
  (spawn vs. external fields), and the `va_interaction` task YAML shape.
- **`references/reference-apps.md`** — side-by-side comparison of `PODIUM_V2` /
  `Voyager2_VA` / `ProactiveVA` / `Starter_VA` (multi-room vs. single-instance, what's
  custom per app), plus the shared Dockerfile pattern and the current CI matrix caveat.
