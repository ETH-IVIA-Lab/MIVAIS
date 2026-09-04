####################################################################
# MIVAIS Studio — production image.
#
# Single FastAPI process (studio.main:app) talking to an external
# MongoDB. 
#
####################################################################

# ── Frontend build stage ────────────────────────────────────────────────────
FROM node:20-slim AS frontend-build
RUN corepack enable
WORKDIR /app/frontend
COPY frontend /app/frontend
RUN pnpm install
RUN pnpm build

# ── Backend image ────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS base

# Runtime libs: libsndfile1 is needed at import time by `soundfile`
# (pulled in transitively even when the Whisper worker is disabled).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Editable install (not a wheel build): Studio loads its static assets and
# locale JSON via __file__, so the package must stay in place on disk rather
# than be copied into site-packages. This mirrors the documented local setup
# (`pip install -e .`).
COPY pyproject.toml README.md ./
COPY studio ./studio
# Baked at a path OTHER than STUDIO_STUDIES_DIR on purpose: in the cluster,
# studies_dir is a PVC mounted over /app/studies, which hides whatever was
# baked there — this git-tracked copy has to live somewhere the mount
# doesn't cover so lifespan() can still read it as the seed/update source on
# every boot (see studio.config.sync_studies). Local/dev runs never set
# STUDIO_STUDIES_SEED_DIR, so this copy is simply unused there.
COPY studies ./studies-src
RUN pip install --no-cache-dir -e .

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Defaults; overridden at deploy time via the Helm chart's extraEnv.
ENV STUDIO_DATA_DIR=/app/data \
    STUDIO_STUDIES_DIR=/app/studies \
    STUDIO_STUDIES_SEED_DIR=/app/studies-src \
    STUDIO_MONGO_URL=mongodb://localhost:27017 \
    STUDIO_WHISPER_WORKER_ENABLED=false

EXPOSE 8000

# Single worker on purpose: the WebSocket collector, VA spawner and (optional)
# Whisper worker all keep in-process state. See deploy/README.md.
CMD ["python", "-m", "uvicorn", "studio.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
