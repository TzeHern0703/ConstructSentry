#!/usr/bin/env bash
# Start the backend (FastAPI) and frontend (Vite) for a Codespace, in the
# background, so the dashboard is reachable as soon as the codespace opens.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Avoid duplicate servers on restart.
pkill -f "uvicorn api:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

cd "$ROOT"
nohup python -m uvicorn api:app --port 8000 >/tmp/constructsentry-api.log 2>&1 &

cd "$ROOT/dashboard"
nohup npm run dev -- --host >/tmp/constructsentry-web.log 2>&1 &

echo "ConstructSentry starting — dashboard on port 5173, API on 8000."
