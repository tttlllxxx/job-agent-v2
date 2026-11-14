FROM node:22-bookworm-slim AS web
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS agent
WORKDIR /build/agent-runtime
COPY agent-runtime/package*.json ./
RUN npm ci --no-audit --no-fund
COPY agent-runtime/ ./
RUN npm run build && npm prune --omit=dev

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir . && python -m playwright install --with-deps chromium
COPY --from=web /build/frontend/dist ./frontend/dist
COPY --from=agent /usr/local/bin/node /usr/local/bin/node
COPY --from=agent /build/agent-runtime/dist ./agent-runtime/dist
COPY --from=agent /build/agent-runtime/node_modules ./agent-runtime/node_modules
COPY --from=agent /build/agent-runtime/package.json ./agent-runtime/package.json
RUN mkdir -p /data/uploads /data/generated /data/backups
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
