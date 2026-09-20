#!/usr/bin/env bash
# 국장(🇰🇷)에 필요한 DART 키를 .env 에 적어 준다. 메모장을 안 거친다.
#
#   ./set-dart-key.sh
#
# 메모장으로 .env 를 만들다 걸리는 함정이 셋이다. 셋 다 여기서 사라진다.
#   1. `notepad .env` 는 **메모장을 닫을 때까지 터미널을 붙잡는다.** 그동안
#      친 명령이 전부 메모장 안으로 들어간다.
#   2. 파일 형식이 "텍스트 문서" 가 기본이라 .env.txt 가 된다.
#   3. 줄끝에 \r 이 붙어 키 끝에 보이지 않는 글자가 생긴다.
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "DART 무료 API 키를 넣습니다. (없으면 https://opendart.fss.or.kr → 인증키 신청)"
echo "붙여넣기는 마우스 오른쪽 클릭 또는 Shift+Insert."
echo
printf "키를 붙여 넣고 Enter: "
IFS= read -r key || true

# 앞뒤 공백·따옴표·윈도우 줄끝을 떼어 낸다. 붙여 넣다 보면 꼭 하나씩 묻어온다.
key="${key%$'\r'}"
key="$(printf '%s' "$key" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
key="${key%\"}"; key="${key#\"}"; key="${key%\'}"; key="${key#\'}"

if [[ -z "$key" ]]; then
  echo "아무것도 안 넣으셨습니다. 그만둡니다."
  exit 1
fi
if [[ ! "$key" =~ ^[A-Za-z0-9]+$ ]]; then
  echo "키에 글자·숫자가 아닌 것이 섞여 있습니다. 다시 복사해 보세요."
  exit 1
fi
if [[ ${#key} -ne 40 ]]; then
  echo "⚠  DART 키는 보통 40자인데 ${#key}자입니다. 일부만 복사됐을 수 있습니다."
  printf "   그래도 넣을까요? [y/N] "
  IFS= read -r yn || true
  [[ "${yn%$'\r'}" =~ ^[Yy]$ ]] || { echo "그만둡니다."; exit 1; }
fi

# 이미 있는 .env 의 다른 줄은 지키고 DART_API_KEY 줄만 갈아 끼운다.
tmp="$(mktemp)"
if [[ -f .env ]]; then
  grep -v '^[[:space:]]*\(export[[:space:]]\+\)\?DART_API_KEY[[:space:]]*=' .env \
    | sed -e 's/\r$//' > "$tmp" || true
fi
printf 'DART_API_KEY=%s\n' "$key" >> "$tmp"
mv "$tmp" .env

echo
echo "✓ .env 에 저장했습니다(${#key}자). 키 값은 화면에 찍지 않습니다."
echo "  이제 ./run.sh 로 띄우면 국장 조회가 됩니다."
