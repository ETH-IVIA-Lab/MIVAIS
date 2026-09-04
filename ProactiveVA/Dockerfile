# Build context: the parent MAIN/ directory
# docker build -f ProactiveVA/Dockerfile .

# ── Frontend build stage ────────────────────────────────────────────────────
FROM node:20-slim AS frontend-build
RUN corepack enable
WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /app/
COPY packages/mivais-va-client /app/packages/mivais-va-client
COPY ProactiveVA/frontend /app/ProactiveVA/frontend
RUN pnpm install --frozen-lockfile
RUN pnpm --filter mivais-va-client build && pnpm --filter proactiveva-frontend build

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
COPY ProactiveVA/backend/requirements.txt /app/ProactiveVA/backend/requirements.txt
WORKDIR /app/ProactiveVA/backend
RUN pip install -r requirements.txt

COPY ProactiveVA/backend  /app/ProactiveVA/backend
COPY ProactiveVA/frontend /app/ProactiveVA/frontend
COPY --from=frontend-build /app/ProactiveVA/frontend/dist /app/ProactiveVA/frontend/dist
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
