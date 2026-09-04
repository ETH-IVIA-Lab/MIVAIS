# MIVAIS Studio

A Revisit-style study platform for evaluating MIVAIS-based visual analytics
systems. Researchers describe a study in YAML, hand a code to participants,
and end up with a full record of every action they took, every state change
the VA produced, and every answer they gave.


---

## Quick start

### 1. Start MongoDB

```bash
docker compose up -d mongo
```

### 2. Install Python dependencies

The project uses [uv](https://docs.astral.sh/uv/) by preference, but plain
`pip` also works.

```bash
# With uv (fast)
uv venv && uv pip install -e .

# Or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set STUDIO_ADMIN_PASSWORD and STUDIO_JWT_SECRET
```

### 4. Run

```bash
uvicorn studio.main:app --reload
```

Open [http://localhost:8000/admin/login](http://localhost:8000/admin/login),
sign in with the credentials from `.env`, upload a study YAML (see
`studies/podium-smoke.yaml`), and Studio gives you a code. Hand the code
to a participant (or visit `http://localhost:8000/s/<CODE>` yourself).

---

## Smoke-testing against PODIUM_V2

The bundled study `studies/podium-smoke.yaml` spawns PODIUM_V2 as a
subprocess on a free port from the configured range. Before uploading:

1. Make sure PODIUM_V2 can run on its own (`cd PODIUM_V2/backend && uvicorn main:app`).
2. Edit the absolute paths in `studies/podium-smoke.yaml`:
   - `va.spawn_cmd` — the directory before `&& uvicorn …`
   - `va.recording_dir_override` — PODIUM hardcodes its recordings dir, so
     Studio tails it directly.
3. Make sure no other process is listening on the configured VA port range
   (default 7100–7199).
4. Upload via `/admin/studies/new`, copy the generated code, and visit
   `/s/<CODE>` in a second tab.

When the participant reaches the `rank-cars` task, Studio spawns PODIUM,
waits for its `/state` endpoint to return 200, then mounts it in the iframe.
PODIUM writes its `session_*.jsonl` recording to the configured directory;
Studio tails the newest file and stores every event in the `events`
collection. Open `/admin/sessions/<id>` to see the live event stream.

---

## Project layout

```
mivais-studio/
├── README.md                    # this file
├── pyproject.toml
├── docker-compose.yml           # Mongo only; Studio runs on host
├── .env.example
├── studies/                     # study YAMLs (versioned in git)
│   └── podium-smoke.yaml
└── studio/                      # Python package
    ├── main.py                  # FastAPI entry point
    ├── settings.py              # env-driven configuration
    ├── db.py                    # Mongo connection + Beanie init
    ├── auth/                    # JWT + argon2 password hashing
    ├── config/                  # YAML schemas + loader
    ├── models/                  # Beanie ODM documents
    ├── orchestrator/            # VA spawner, WebSocket collector, session manager, scoring
    ├── api/                     # FastAPI routers (admin, participant)
    ├── templates/               # Jinja2 templates
    └── static/css/              # one CSS file, no build step
```

---

## What's in v0 / what's deferred

**In:**
- FastAPI backend, MongoDB via Beanie, Pydantic schemas
- Admin auth (single user via env), study upload, study list, session detail
- Participant flow: code entry → consent → tasks → finish
- Task primitives: `info_screen`, `single_choice`, `multi_choice`, `likert`, `free_text`, `va_interaction`
- VA spawner: subprocess with port allocation + health check + termination
- WebSocket collector that ingests MIVAIS events into Mongo, tagged with `task_id` and `logging_id`
- Ground-truth scoring (`exact`, `set_match`, `ordered_match`, `regex`)
- Blocks / variants / `parameters` / `mivais_config` / `task_steps` / `response_format` accepted in YAML
- One CSS file, server-rendered templates — no Node toolchain

**Deferred to next phases:**
- Audio recording (browser MediaRecorder) + faster-whisper transcription
- Multiplayer lobby + ready-check + group session
- Live session view (read-only admin spectator)
- Replay viewer with timeline scrubber + WorldState reconstruction
- Per-study analytics dashboard + per-task drill-down + cross-system comparison
- Exports (CSV, Parquet, JSONL bundle)
- Caddy reverse proxy + production deploy
- Hot-reload of in-flight study YAMLs

---

## Notes on PODIUM compatibility

The contract asks each VA to accept a `--port` and a `--recording-dir`
argument and to write JSONL there. PODIUM_V2 currently only accepts a port
(via uvicorn) and writes to a hardcoded relative path. Studio works around
this by reading `va.recording_dir_override` from the study YAML and tailing
that path directly. When PODIUM gains a `--recording-dir` flag (or an env
var), the override can come out and the contract is fully met.

## Spawning VAs: process vs. docker-compose

Each `va_systems.<id>` in a study YAML chooses one of two modes.

**Local subprocess (default)** — Studio runs `va.spawn_cmd` as a child
process. Good for laptops, single-machine pilots, and anything the researcher
already runs from a terminal:

```yaml
va_systems:
  podium:
    system: podium
    cwd: /path/to/PODIUM_V2/backend
    spawn_cmd: python -m uvicorn main:app --port {port} --log-level warning
    iframe_url: http://127.0.0.1:{port}/
    health_check_url: http://127.0.0.1:{port}/state
```

**Docker-compose** — Studio calls `docker compose up -d <service>` against a
compose file you control. Containers survive a Studio crash *if* docker
remains up, and you can put real bind-mounts / networks in the compose file.
Use this when hosting Studio somewhere shared:

```yaml
va_systems:
  podium:
    system: podium
    iframe_url: http://127.0.0.1:{port}/
    health_check_url: http://127.0.0.1:{port}/state
    compose:
      file: ./docker-compose.podium.yml      # path is resolved relative to `cwd`
      service: podium                         # service name in the compose file
      # project: pilot-may                    # optional `-p <project>` override
    recording_dir_override: /var/lib/podium/recordings   # the host path the container writes to
```

The compose file is **not generated by Studio** — you write it, with a port
mapping that matches `{port}` resolution (we set `STUDIO_VA_PORT` in the env).
Studio runs `up -d --no-recreate`, resolves the container PID via
`docker inspect`, and tracks liveness through the same PID-based path as
local subprocesses. Stop is `docker compose stop <service>` (graceful), so
container state survives for later inspection.

## Session resume across restarts

When Studio is killed mid-session, the in-flight VA processes go down with
their parent. On the next boot Studio:

1. Walks every session in `running` / `spawning` status.
2. For each `Session.vas` entry, checks whether the recorded PID is alive
   (cross-platform, see [`studio/process.py`](studio/process.py)).
3. Re-attaches survivors to the spawner and reconnects each WebSocket collector
   (event ingest resumes mid-file).
4. Sessions where every VA is gone get marked `interrupted` with a clear
   `failure_reason`; the participant sees a friendly "this session was
   interrupted" screen and the admin sees the status pill change.
5. Audio chunks where `transcribed: false` are re-queued into the Whisper
   worker, so transcription resumes where it left off.

Lobby sessions (no VA spawned yet) are left untouched and continue to accept
ready-ups after the restart.
