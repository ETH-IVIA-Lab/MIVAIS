# Reference implementations, side by side

Four existing apps demonstrate the spectrum from "tutorial minimal" to "production
hosted." Read the one closest to what you're building before writing your own
`main.py` from scratch.

## Contents
- [Comparison table](#comparison-table)
- [Multi-room pattern (PODIUM_V2 / Voyager2_VA / ProactiveVA)](#multi-room-pattern-podium_v2--voyager2_va--proactiveva)
- [Single-instance pattern (Starter_VA)](#single-instance-pattern-starter_va)
- [Dockerfile pattern](#dockerfile-pattern)
- [CI matrix caveat](#ci-matrix-caveat)

## Comparison table

| | Starter_VA | PODIUM_V2 | Voyager2_VA | ProactiveVA |
|---|---|---|---|---|
| Deploy mode | spawned (subprocess) | external (hosted) | external (hosted) | external (hosted, but not CI-wired — see below) |
| Rooms | single global instance | multi-room, lazy-created, idle-reaped | multi-room | multi-room |
| Frontend | one `index.html`, vanilla JS + SVG, no build step | React (dashboard + topology + replay pages) | React | React |
| Agents | one (`InsightAgent`) | `SVMRankingAgent`, `NLCommandAgent` | app-specific | `OnboardingDetector`, `ExplorationDetector`, `VerificationDetector`, `Planner`, `ActingAgent` |
| Custom `Gateway._handle_action` | no | yes — `set_nudges`, `compute_weights`, `drop_order`, `rank_all` | app-specific | app-specific (LLM-driven agent orchestration) |
| Dockerfile | none (dev-only, run with `python main.py`) | yes | yes | yes (but see CI caveat) |
| Purpose | the running example for the `/setup` tutorial served by Studio | production rank-aggregation VA | production VA, second reference system | LLM-agent-driven proactive-suggestion VA |

## Multi-room pattern (PODIUM_V2 / Voyager2_VA / ProactiveVA)

All three hosted apps use the same shape: one process serves many concurrent study
sessions by isolating them into "rooms," discovered lazily from the WebSocket URL's
`?room=<id>` query parameter (`PODIUM_V2/backend/main.py:6-24`).

Per-room startup sequence:
1. Construct infrastructure — `AuditLog`, `AgentRegistry`, `PermissionGuard`,
   `WorldState`, `MessageBus`, `Gateway`, `SessionRecorder`
   (`PODIUM_V2/backend/main.py:94-172`, `ProactiveVA/backend/main.py:36-42`):
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
2. Load the dataset into `WorldState` via `system_write` (e.g. PODIUM's
   `dataset`/`numeric_cols`, ProactiveVA's `hexgrid`/`streets`/`entities`/`knowledge`).
3. Parse `agents_config.yaml`, register each agent's `AgentCapabilities`.
4. Instantiate each enabled agent class and start its `run()` loop as an asyncio
   background task.
5. Rooms are reaped after an idle timeout (PODIUM_V2 defaults to 300s) so a
   long-running process doesn't accumulate dead rooms from finished study sessions.

Config loading (`PODIUM_V2/backend/main.py:79-90`, `ProactiveVA/backend/main.py:57-69`):
```python
_config = json.loads((Path(__file__).parent / "agents_config.yaml").read_text())
_user_configs = {u["role"]: u for u in _config.get("users", [])}
_mivais_config = MivaisConfig.load(Path(__file__).parent / "mivais_config.yaml")
```

WorldState shapes are entirely app-specific — no schema is imposed:
- **PODIUM_V2**: `dataset`, `numeric_cols`, `session_nudges`, `user_preference_ranking`,
  `ranked_items`, `display_order`, `weights`, `svm_status`. Compute Weights / Rank All are
  sent to `SVMRankingAgent` via the MessageBus (`weights.compute_request` / `rank_all.request`).
- **ProactiveVA**: `dataset`, `hexgrid`, `streets`, `entities`, `knowledge`,
  `data_fields`, `selected_hex`, `time_range`, `selected_entity`, `keyword_filter`,
  `focused_view`, `notes`, `staged_evidence`, `highlighted_message_ids`,
  `pending_suggestions`, `agent_trace`, `agent_status`, plus feature-flag-style keys
  (`onboarding_enabled`, `exploration_enabled`, `verification_enabled`) and
  `interaction_log`.

## Single-instance pattern (Starter_VA)

No multi-room logic, no idle timeout — one global `WorldState` for the process's
lifetime, because Studio spawns a fresh subprocess per session instead. Reads its port
and recording directory from env vars Studio sets when it spawns the process:

```python
PORT = int(os.environ.get("STUDIO_VA_PORT", os.environ.get("PORT", "7300")))
RECORDINGS_DIR = Path(os.environ.get("STUDIO_VA_RECORDING_DIR", HERE / "recordings"))
```

No Docker, no reverse proxy — Studio just embeds `http://127.0.0.1:<port>`. This is the
right template to copy for a quick prototype or a study that only ever runs
single-machine/local.

## Dockerfile pattern

`PODIUM_V2/Dockerfile`, `Voyager2_VA/Dockerfile`, `ProactiveVA/Dockerfile` all share a
two-stage shape, built from the **repository root** (not the app's own directory) so
`MIVAIS/` and `packages/mivais-va-client` are visible as siblings:

```dockerfile
# Stage 1 — frontend build
FROM node:20-slim AS frontend-build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /app/
COPY packages/mivais-va-client /app/packages/mivais-va-client
COPY <app>/frontend /app/<app>/frontend
RUN pnpm install --frozen-lockfile \
 && pnpm --filter mivais-va-client build \
 && pnpm --filter <app>-frontend build

# Stage 2 — Python backend
FROM python:3.11-slim
WORKDIR /app
COPY MIVAIS /app/MIVAIS
RUN pip install -e /app/MIVAIS
COPY <app>/backend/requirements.txt /app/<app>/backend/requirements.txt
WORKDIR /app/<app>/backend
RUN pip install -r requirements.txt
COPY <app>/backend /app/<app>/backend
COPY <app>/frontend /app/<app>/frontend
COPY --from=frontend-build /app/<app>/frontend/dist /app/<app>/frontend/dist
EXPOSE <port>
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "<port>"]
```

This is a reasonable starting point for a new hosted VA's Dockerfile — copy one of the
three and rename the `<app>`/`<port>` placeholders.

## CI matrix caveat

`.gitlab-ci.yml`'s `build:image` stage matrix (lines 86-100, as of this writing) only
has an entry for `studio`. PODIUM_V2, Voyager2_VA, and ProactiveVA have working
Dockerfiles but are **not** built by the pipeline — they must be built and deployed
manually, or you extend the matrix yourself (mirroring `studio`'s entry: set
`APP_LAYER`, `CONTEXT` to the repo root, `DOCKERFILE_REL` to the app's Dockerfile path).
Verify this hasn't changed before assuming otherwise — check the current matrix
directly rather than trusting this note indefinitely.
