#!/usr/bin/env bash
# Serve the dashboard locally AND expose it on your ngrok domain — one command.
#
#   ./run_ngrok.sh           -> live data + tunnel on https://japan.ngrok-free.app
#   ./run_ngrok.sh --demo    -> offline sample data + tunnel
#
# Requirements (one-time):
#   1) Install ngrok:            https://ngrok.com/download
#   2) Log in with your token:   ngrok config add-authtoken <YOUR_TOKEN>
# The reserved domain is bound to YOUR ngrok account, so this must run on your
# machine (the GitHub Pages site is the always-on alternative — no PC needed).
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--demo" ]]; then
  export SUH_DH_DEMO=1
  echo "Running in DEMO mode (sample data, no network)."
fi

DOMAIN="${SUH_DH_NGROK_DOMAIN:-japan.ngrok-free.app}"
PORT="${SUH_DH_PORT:-8000}"

command -v ngrok >/dev/null 2>&1 || {
  echo "ngrok가 설치되어 있지 않습니다 → https://ngrok.com/download"
  exit 1
}

# Start the dashboard in the background; stop it when this script exits.
python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null || true' EXIT

# Wait for the server to answer before opening the tunnel.
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done

echo "▶ 로컬: http://127.0.0.1:${PORT}    공개: https://${DOMAIN}/earnings/"
exec ngrok http "$PORT" --url="https://${DOMAIN}"
