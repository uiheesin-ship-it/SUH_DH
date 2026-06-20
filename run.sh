#!/usr/bin/env bash
# Launch the 52-week-high dashboard.
#   ./run.sh           -> live data (Finviz + Yahoo Finance)
#   ./run.sh --demo    -> offline sample data (no network needed)
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--demo" ]]; then
  export SUH_DH_DEMO=1
  echo "Running in DEMO mode (sample data, no network)."
fi

HOST="${SUH_DH_HOST:-127.0.0.1}"
PORT="${SUH_DH_PORT:-8000}"
echo "Open http://${HOST}:${PORT}"
exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT"
