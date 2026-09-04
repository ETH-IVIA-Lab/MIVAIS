# Build context: the parent MAIN/ directory (so MIVAIS/ is sibling-visible).
# docker build -f Voyager2_VA/Dockerfile .

# ── Frontend build stage ────────────────────────────────────────────────────
FROM node:20-slim AS frontend-build
RUN corepack enable
WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /app/
COPY packages/mivais-va-client /app/packages/mivais-va-client
COPY Voyager2_VA/frontend /app/Voyager2_VA/frontend
RUN pnpm install --frozen-lockfile
RUN pnpm --filter mivais-va-client build && pnpm --filter voyager2-va-frontend build

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
COPY Voyager2_VA/backend/requirements.txt /app/Voyager2_VA/backend/requirements.txt
WORKDIR /app/Voyager2_VA/backend
RUN pip install -r requirements.txt

COPY Voyager2_VA/backend  /app/Voyager2_VA/backend
COPY Voyager2_VA/frontend /app/Voyager2_VA/frontend
COPY --from=frontend-build /app/Voyager2_VA/frontend/dist /app/Voyager2_VA/frontend/dist
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
