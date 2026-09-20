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

# 이미 다른 창에서 서버가 돌고 있나.
#
# 이게 제일 헷갈리는 함정이다. 창을 두 개 띄워 놓고 한쪽만 Ctrl+C 로 끄면,
# 브라우저는 계속 **옛 코드가 도는 쪽**을 본다. "다시 띄웠는데 왜 그대로지" 가
# 여기서 나온다. 포트가 이미 물려 있으면 uvicorn 이 죽긴 하지만 에러 문구가
# 영어 한 줄이라 그냥 지나치기 쉽다 — 먼저 확인하고 할 일을 알려 준다.
if curl -fsS -m 2 "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1; then
  echo
  echo "⚠  이미 http://${HOST}:${PORT} 에서 서버가 돌고 있습니다."
  echo "   지금 도는 코드:"
  curl -fsS -m 2 "http://${HOST}:${PORT}/api/health" \
    | python3 -c "import sys,json;b=(json.load(sys.stdin).get('backend') or {});print('     리비전', b.get('rev') or '(모름 — 옛 코드입니다)', '· 시작', b.get('started_at') or '?')" \
    2>/dev/null || echo "     (버전 정보를 안 보냅니다 — 옛 코드입니다)"
  echo
  echo "   그 서버가 도는 창을 찾아 Ctrl+C 로 끄고 다시 실행하세요."
  echo "   창을 못 찾겠으면 다른 포트로 띄우면 됩니다:"
  echo "     SUH_DH_PORT=8001 ./run.sh   →   http://${HOST}:8001/quarterly/"
  echo
  exit 1
fi

echo "Open http://${HOST}:${PORT}"
exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT"
