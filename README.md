# MIVAIS: A Study Environment for Multi-Agent Mixed-Initiative Visual Analytics Applications

[![arXiv:2609.04983](https://img.shields.io/badge/arXiv-2609.04983-red)](https://arxiv.org/abs/2609.04983)

![Overview of the MIVAIS framework. The MIVAIS Infrastructure (left) supports the implementation of modular, mixed-initiative Visual Analytics (VA) systems where software and human agents collaborate. The MIVAIS Study Environment (right) enables researchers to easily configure experiments, collect multi-modal data during participant sessions, and perform comprehensive post-analysis.](MIVAIS/docs/mivais_teaser.svg)

MIVAIS (A Study Environment for Multi-Agent Mixed-Initiative Visual Analytics Applications) is a framework that allows researchers to build mixed-initiative Visual Analytics applications and evaluate their approaches with low-effort study setup and post-analysis. The MIVAIS Infrastructure supports the implementation of modular, mixed-initiative Visual Analytics (VA) systems where software and human agents collaborate. The MIVAIS Study Environment enables researchers to easily configure experiments, collect multi-modal data during participant sessions, and perform comprehensive post-analysis.     

Learn more about MIVAIS by reading the [MIVAIS research paper](https://arxiv.org/abs/2609.04983).

If you reference MIVAIS, use the following citation:

```bibTeX
@misc{staehle2026mivais,
  title = {{MIVAIS}: { A Study Environment for Multi-Agent Mixed-Initiative Visual Analytics Applications}},
  author = {{St{\"a}hle}, Tobias and {Schneider}, Simon and {Sevastjanova}, Rita and {El-Assady}, Mennatallah},
  year = {2026},
  eprint = {2609.04983},
  archivePrefix = {arXiv},
  doi = {10.48550/arXiv.2609.04983}
}
```


##This repository contains:

- `MIVAIS/` — the core Python framework (WorldState, MessageBus, Gateway,
  AgentRegistry, PermissionGuard, AuditLog).
- `PODIUM_V2/`, `Voyager2_VA/`, `ProactiveVA/` — three mixed-initiative VA
  applications built on MIVAIS, reimplementing prior work for evaluation.
- `Starter_VA/` — a minimal template VA for the `/setup` tutorial.
- `studio/` — MIVAIS Studio, the web-based study environment (admin +
  participant-facing apps).
- `packages/mivais-va-client/` — shared TypeScript client used by all VA
  frontends to talk to a MIVAIS Gateway over WebSocket.
- `skills/` — skill files for AI coding agents to help with retrofiting exisiting
  and building new applications with the MIVAIS Infrastructure.

Everything runs locally via Docker — no external hosting is required — but can also be hosted.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose v2
  (`docker compose version`).

## Quick start

From the repository root (this directory):

```bash
docker compose up -d --build
```

This builds and starts five containers:

| Service | Container | Default URL | Purpose |
|---|---|---|---|
| `mongo` | `studio-mongo` | `mongodb://localhost:27017` | Studio's database |
| `podium` | `studio-podium` | http://localhost:7100 | PODIUM VA |
| `voyager2` | `studio-voyager2` | http://localhost:7101 | Voyager 2 VA |
| `proactiveva` | `studio-proactiveva` | http://localhost:7102 | ProactiveVA VA |
| `studio` | `studio` | http://localhost:8000 | MIVAIS Studio (admin + participant apps) |

The first build takes a few minutes (installs Python/Node dependencies for
four apps). Subsequent `docker compose up` runs are fast — only rebuild with
`--build` after changing source or dependencies.

Check everything is up:

```bash
docker compose ps
```

All five services should show `Up`, with `studio-mongo` additionally
`(healthy)`.

## Running a study

1. Open http://localhost:8000/admin/login and sign in with the default dev
   credentials: username `admin`, password `change-me` (override via
   `STUDIO_ADMIN_USERNAME` / `STUDIO_ADMIN_PASSWORD`, see below).
2. Go to **Register a study**. A handful of demo/smoke studies are provided under
   `studio/studies/` (e.g. `demo-singleplayer`, `demo-two-vas`,
   `demo-proactiveva`) and are auto-listed there — click **Register**.
3. On the study page, click **+ New code** to mint a participant access
   code, then open `http://localhost:8000/s/<CODE>` (in a new/incognito
   browser context — each browser can only join a given study once).
4. Work through consent → any optional recording/biometric steps → the task
   flow. Tasks that embed a VA (`type: va_interaction`) load PODIUM /
   Voyager 2 / ProactiveVA directly, isolated per session via the room
   query param.
5. Back in the admin, the study page shows live session/event counts;
   **Live view** lets you watch an active session, and **Session Replay**
   lets you step through a completed one.

To try a VA standalone without going through Studio, just open its port
directly, e.g. http://localhost:7100 for PODIUM (it seeds a default `default`
room with the bundled cars dataset).

## Configuration

All configuration is via environment variables, with sensible dev defaults
in `docker-compose.yml`. Override any of them by exporting the
variable before `docker compose up`, or by adding a `.env` file next to
`docker-compose.yml` (see `studio/.env.example` for the full list of Studio
settings).

| Variable | Default | Purpose |
|---|---|---|
| `STUDIO_HOST_PORT` | `8000` | Host port Studio is published on. Change this if `8000` is already taken locally, e.g. `STUDIO_HOST_PORT=8090 docker compose up -d`. |
| `PODIUM_HOST_PORT` | `7100` | Host port for PODIUM. |
| `VOYAGER2_HOST_PORT` | `7101` | Host port for Voyager 2. |
| `PROACTIVEVA_HOST_PORT` | `7102` | Host port for ProactiveVA. |
| `STUDIO_ADMIN_USERNAME` / `STUDIO_ADMIN_PASSWORD` | `admin` / `change-me` | Studio admin login. Change these for anything beyond local dev. |
| `STUDIO_JWT_SECRET` | `dev-only-change-me` | Signs Studio's admin session tokens. |
| `STUDIO_MONGO_DB` | `mivais_studio` | Mongo database name. |
| `LITELLM_BASE_URL` / `LITELLM_API_KEY` | unset | ProactiveVA's LLM backend (LiteLLM proxy). Without these, ProactiveVA's assistant agents run without LLM inference — everything else (map, notes, detectors) still works. |

Studio and the three VAs communicate with each other over the Docker
network (e.g. `http://podium:8000`).

## Stopping / resetting

```bash
docker compose down          # stop containers, keep data (Mongo volume, Studio data volume)
docker compose down -v       # stop containers AND delete all data
```
