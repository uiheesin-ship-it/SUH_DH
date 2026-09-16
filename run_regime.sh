#!/usr/bin/env bash
# Launch the Market Regime Lab (Streamlit).
#   ./run_regime.sh           -> live data (Yahoo Finance)
#   ./run_regime.sh --demo    -> offline synthetic data (no network needed)
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "--demo" ]]; then
  export SUH_DH_DEMO=1
  shift
  echo "Running in DEMO mode (synthetic series, no network)."
fi

PORT="${SUH_DH_REGIME_PORT:-8501}"
echo "Open http://127.0.0.1:${PORT}"
exec python3 -m streamlit run app/regime/streamlit_app.py --server.port "$PORT" "$@"
