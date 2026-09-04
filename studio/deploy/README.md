# Deploying MIVAIS Studio

Studio is a single FastAPI process talking to one MongoDB. Everything else
(Whisper transcription, VA spawn, audit log) runs in-process. For a real
deployment, put it behind:

  1. **TLS** (Caddy or any reverse proxy that does automatic certificates).
     Browsers refuse `getUserMedia` on non-secure origins outside localhost,
     so audio capture *breaks* without TLS.
  2. **A real Mongo** — the dev `docker-compose.yml` runs one, but in
     production you'll want a managed cluster or a snapshotted volume.
  3. **A Prometheus scrape** of `/metrics` (or just a cron pinging `/health`).

## Quick recipe

```bash
# 1. Set your host + admin credentials
cp .env.example .env
# Edit STUDIO_ADMIN_PASSWORD, STUDIO_JWT_SECRET (>=32 random bytes)

# 2. Bring up Mongo + Studio
docker compose up -d mongo
uv pip install -e .  # or: pip install -e .
python -m uvicorn studio.main:app --host 127.0.0.1 --port 8000 \
    --workers 1 --log-level info

# 3. Run Caddy in front (see deploy/Caddyfile)
caddy run --config deploy/Caddyfile
```

## Why a single uvicorn worker

The Whisper worker, WebSocket collector, and VA spawner all keep in-process state
(asyncio queues, subprocess.Popen handles, in-memory PID maps). Running with
`--workers > 1` would multiply those into uncoordinated copies. If you outgrow
a single process, move Whisper transcription to a separate service (it's the
hot CPU consumer) before sharding the main app.

## Backups

Studio's durable state is two places:

  - **MongoDB** — studies, sessions, participants, events, transcripts.
    Standard `mongodump` works; the database name is `STUDIO_MONGO_DB` from
    your `.env` (defaults to `mivais_studio`).
  - **`data/audio/`** — the raw audio chunks. Plain WebM/Opus files in a
    nested directory per `<study>/<session>/<participant>/`.

A nightly tarball of both is enough for thesis-grade durability:

```bash
mongodump --uri="$STUDIO_MONGO_URL" --db="$STUDIO_MONGO_DB" --out=./bak/mongo
tar czf studio-$(date +%F).tar.gz data/audio bak/mongo
```

## Observability

  - `GET /health` — mongo connectivity + Whisper worker enabled flag.
  - `GET /metrics` — Prometheus exposition (studies, sessions, participants,
    events, audio chunks pending/transcribed, audit log size).
  - `GET /admin/audit` — every state-changing admin action with actor + meta.

## Rate limiting

Out-of-the-box Studio has no rate limit on `/ingest/audio-chunk`. A
misbehaving client could fill `data/audio/` quickly. The included Caddyfile
shows the recommended stanza using the `caddy-ratelimit` plugin.
