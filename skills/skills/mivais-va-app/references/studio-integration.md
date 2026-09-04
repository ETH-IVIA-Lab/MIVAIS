# How MIVAIS Studio talks to a VA app

Studio never imports your code — the entire integration surface is HTTP/WebSocket
calls plus a study-YAML config block. This doc covers what Studio expects from you and
what you can expect from it.

## Contents
- [Studio → VA push contract](#studio--va-push-contract-va_clientpy)
- [Session manager: external-VA flow](#session-manager-external-va-flow-session_managerpy)
- [VAConfig YAML schema](#vaconfig-yaml-schema-configschemaspy)
- [`va_interaction` task YAML](#va_interaction-task-yaml-configschemaspy)

## Studio → VA push contract (`va_client.py`)

Studio pushes state and Wizard-of-Oz actions into your app the same way any client
would — by opening a short-lived WebSocket connection under a special role,
`studio_replayer`, sending one action, and closing. There is no persistent
Studio↔VA connection to maintain or worry about.

**`push_world_state`** (`va_client.py:51-83`): connects with `role=studio_replayer` and
whatever `room` your iframe URL implies, sends
```json
{"action": "replay.push_state", "state": {"key": "value", ...}}
```
Each key lands via `WorldState.system_write()` on your side (bypasses your
`PermissionGuard` — this is expected, since it's infrastructure, not a participant).
This is how task-start world-state seeding (`world_state.set`/`world_state.initial` in
a task YAML) and the replay viewer's scrubber actually work — **make sure your
`Gateway`'s built-in `replay.push_state` handler is not overridden or skipped**; if you
subclassed `Gateway` and overrode `_handle_action`, remember the base class handles
this action before falling through to your override, not instead of it.

URL derivation (`va_client.py:29-48`): `_ws_url_from_iframe(iframe_url, channel)` turns
your `iframe_url` into `{wsProto}://{host}:{port}/ws/{channel}?role=studio_replayer&room={room}`
— so your WebSocket route path and port must match what you declared in
`iframe_url`/`health_check_url`.

**`send_wizard_action`** (`va_client.py:86-114`): same connection pattern, sends
`{"action": "wizard.act"|"wizard.say", ...}` so a human wizard (via Studio's admin UI)
can manipulate WorldState or chat *as* a chosen agent — useful for Wizard-of-Oz study
designs where a researcher manually plays the role of an AI agent.

## Session manager: external-VA flow (`session_manager.py`)

`ensure_va_started` (`session_manager.py:373-448`) checks whether your VA is already
running for this session and spawns it if not (spawned mode only — for `external: true`
it just proceeds straight to embedding, since there's nothing to spawn). Line 438:
external VAs explicitly skip the local JSONL tailer, since "external VAs aren't
co-located, so there's no local JSONL file to tail."

`_apply_world_state` (`session_manager.py:501-548`) runs at task start: pushes the
task's `world_state:` payload via `push_world_state()`, in either `"continue"` mode
(apply `world_state.set` as a delta) or `"replace"` mode (write `world_state.initial`
wholesale), with optional per-role overrides via `world_state.by_role`.

## `VAConfig` YAML schema (`config/schemas.py`)

Fields on a `va_systems.<id>` entry (`config/schemas.py:61-107`):

| field | meaning |
|---|---|
| `system: str` | your app's identifier |
| `external: bool = False` | `true` → Studio embeds an already-running service; `false` → Studio spawns `spawn_cmd` as a subprocess |
| `iframe_url: str` | URL embedded in the participant's task iframe (may use `{port}` for spawned mode) |
| `health_check_url: str` | polled before Studio embeds you — must return 200 once you're ready |
| `room_per_session: bool = True` | append `?room=<session_id>` to `iframe_url` and forward that room to server-side state pushes |
| `room_param: str = "room"` | override the query-param name if your app doesn't use `room` |
| `token_env: str | None` | env var holding an access token to append to the URL |
| `token_param: str = "token"` | query-param name for the token |
| `cwd`, `spawn_cmd` | spawned mode only — working directory + command template (supports `{port}`) |
| `compose: {file, service, project?}` | spawned mode, docker-compose flavor instead of a bare subprocess |
| `recording_dir_override` | spawned mode — where your app writes `session_*.jsonl`, if not co-locatable with Studio's default assumption |

Example external entry:
```yaml
va_systems:
  podium:
    system: podium
    external: true
    iframe_url: "https://podium.example_va.com/"
    health_check_url: "https://podium.example_va.com/state"
```

Example spawned entry:
```yaml
va_systems:
  my_va:
    system: my_va
    cwd: /path/to/my-va/backend
    spawn_cmd: python -m uvicorn main:app --port {port} --log-level warning
    iframe_url: http://127.0.0.1:{port}/
    health_check_url: http://127.0.0.1:{port}/state
```

## `va_interaction` task YAML (`config/schemas.py`)

Fields (`config/schemas.py:411-416`):

| field | meaning |
|---|---|
| `type: "va_interaction"` | discriminator |
| `id: str` | task id |
| `variant: str = "default"` | which variant of the VA system to use |
| `parameters: dict` | task-specific parameters passed to your VA at startup |
| `mivais_config: dict` | per-task overrides of your `MivaisConfig` (e.g. `{"chat": {"enabled": false}}`) |
| `answer: VAInteractionAnswer` | how to score the task |

`answer.type` is one of `"capture_state"` (record a specific WorldState key —
`world_state_key: str`), `"text"`, `"choice"`, `"none"`.

World-state seeding block (`config/schemas.py:217-234`), sibling to the task fields
above:

```yaml
world_state:
  mode: replace          # or "continue"
  initial:               # used when mode: replace
    session_nudges: {}
    ranked_items: []
  # set:                 # used when mode: continue — delta merged into existing state
  # by_role:              # per-role overrides, keyed by role name
```

Full example (adapted from `studio/studies/demo-multiplayer/tasks/joint-ranking.yaml`):

```yaml
type: va_interaction
prompt_md: "Build ONE ranking together..."
timer_seconds: 420
world_state:
  mode: replace
  initial:
    session_nudges: {}
    weights: {}
    user_preference_ranking: {}
    ranked_items: []
    display_order: []
answer:
  type: capture_state
  world_state_key: display_order
```

Task steps can also declare `auto_check_on` (`config/schemas.py:183-214`) to
auto-advance when a matching MIVAIS event arrives — e.g.
`{ event_type: "user_action", meta: { action: "chat_message" } }` fires on the first
chat message, useful for "discuss with your partner, then continue" steps.
