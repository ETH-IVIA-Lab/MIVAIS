# Build context: the parent MAIN/ directory.
# docker build -f PODIUM_V2/Dockerfile .

# ── Frontend build stage ────────────────────────────────────────────────────
FROM node:20-slim AS frontend-build
RUN corepack enable
WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /app/
COPY packages/mivais-va-client /app/packages/mivais-va-client
COPY PODIUM_V2/frontend /app/PODIUM_V2/frontend
RUN pnpm install --frozen-lockfile
RUN pnpm --filter mivais-va-client build && pnpm --filter podium-v2-frontend build

# ── Backend image ────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY MIVAIS /app/MIVAIS
RUN pip install -e /app/MIVAIS

# pip resolves `-e file:../../MIVAIS` in requirements.txt relative to its CWD,
# so cd into the backend before running it.
COPY PODIUM_V2/backend/requirements.txt /app/PODIUM_V2/backend/requirements.txt
WORKDIR /app/PODIUM_V2/backend
RUN pip install -r requirements.txt

COPY PODIUM_V2/backend  /app/PODIUM_V2/backend
COPY PODIUM_V2/frontend /app/PODIUM_V2/frontend
COPY --from=frontend-build /app/PODIUM_V2/frontend/dist /app/PODIUM_V2/frontend/dist
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
