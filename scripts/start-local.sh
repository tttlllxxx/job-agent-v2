#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv
  .venv/bin/pip install -e '.[dev]'
fi
if [[ ! -d frontend/node_modules ]]; then npm --prefix frontend ci; fi
if [[ ! -d agent-runtime/node_modules ]]; then npm --prefix agent-runtime ci; fi
npm --prefix frontend run build
npm --prefix agent-runtime run build
export PYTHONPATH=backend
if [[ -f data/app.db && ! -f data/workspace.db ]]; then
  .venv/bin/python -m app.migrate --source data/app.db --target sqlite:///data/workspace.db
fi
.venv/bin/python -m alembic upgrade head
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${APP_PORT:-8000}" --workers 1
