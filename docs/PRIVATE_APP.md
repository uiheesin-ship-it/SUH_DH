# 비공개 컨콜 리서치 앱 (로그인 4탭)

컨콜 **전문·검색·다운로드·투자포인트**를 다루는 앱입니다. 원문이 들어가므로 **공개 Pages가 아니라
로그인으로 본인만 접근**합니다. (공개 대시보드는 원문 없는 분석 카드로 별도 유지)

- 탭 ① 기업별 컨콜: 왼쪽 섹터·기업 / 가운데 연·분기 선택 + 전문(영/한 토글) / 오른쪽 최근 1년 변화 요약
- 탭 ② 투자포인트: 최초 언급 시점순 목록 + 상세(누적 이력 포함)
- 탭 ③ 검색: 영어/한국어로 전체 컨콜 전문 검색
- 탭 ④ 컨콜 다운로드: 기업·기간 선택 → **하나의 txt/Word 파일**

## 로컬에서 바로 실행 (가장 간단, docker 없이)

```bash
# 1) 백엔드 (SQLite, 비밀번호 지정)
pip install -r requirements-eai.txt
EAI_APP_PASSWORD='내비밀번호' EAI_LLM_PROVIDER=mock uvicorn app.eai_asgi:app --port 8000

# 2) 데이터 채우기 (택1)
#   (a) 데모: 6개 기업 합성 컨콜로 화면 먼저 보기
curl -X POST "http://localhost:8000/api/eai/jobs/run-batch?wait=true"
#   (b) 실제 수집: AV 키로 원문 수집 후 분석
EAI_ALPHAVANTAGE_API_KEY=... EAI_HARVEST_PROVIDER=alphavantage \
  EAI_TRANSCRIPT_API_DELAY=15 python -m app.eai.harvest
EAI_TRANSCRIPT_PROVIDER=directory EAI_LLM_PROVIDER=mock python -m app.eai.export --out data/eai

# 3) 프론트엔드
cd frontend && npm install
NEXT_PUBLIC_EAI_API_BASE=http://localhost:8000 npm run dev
#   → http://localhost:3000 접속 → 비밀번호 로그인 → 4탭
```

## docker-compose (Postgres 포함)

```bash
echo "EAI_APP_PASSWORD=내비밀번호"        >  .env
echo "EAI_LLM_PROVIDER=mock"              >> .env
echo "EAI_ALPHAVANTAGE_API_KEY=..."       >> .env   # 실제 수집 시
docker compose up --build
# 데이터: docker compose exec backend curl -X POST "localhost:8000/api/eai/jobs/run-batch?wait=true"
# 앱: http://localhost:3000
```

## 데이터 영속 & 크레딧 소진 대비 (요구 #4)
- 원문·분석은 **DB에 저장**됩니다(SQLite 파일 또는 Postgres 볼륨). LLM/크레딧이 없어도 **기존 데이터는 사라지지 않고**, 신규분만 분석이 보류됩니다. 나중에 LLM 켜면 캐시로 한 번에 분석.

## 실제 Claude 분석으로 전환
`EAI_LLM_PROVIDER=anthropic` + `EAI_ANTHROPIC_API_KEY` + `EAI_FAST_MODEL/EAI_BALANCED_MODEL/EAI_DEEP_MODEL`.
전문·번역·톤 분석·투자포인트가 실제 분석으로 채워집니다(캐시로 재분석 저렴).

## 배포 — 무료 티어, 설치 없이 (권장)
서비스 **1개**(FastAPI가 화면+API 함께 서빙)로 배포합니다. 블루프린트: `render.private.yaml`.

1. https://dashboard.render.com → **New → Blueprint** → 이 저장소 연결 → `render.private.yaml` 선택 → **Apply**
2. 프롬프트에서 **`EAI_APP_PASSWORD`**(로그인 비밀번호) 입력
3. 빌드 후 `https://suh-dh-private.onrender.com` 같은 URL 생성 → 열고 로그인 → 4탭(6개 기업 데모 자동 채움)

무료 플랜: 유휴 15분 후 잠들어 첫 요청이 ~30~60초. SQLite는 재배포 시 초기화(EAI_DEMO_SEED=1이 데모 재생성).
**영속 실데이터**가 필요하면 `EAI_DATABASE_URL`을 무료 관리형 Postgres(예: Neon)로 지정하고 `EAI_DEMO_SEED=0` 후 harvester 실행.
