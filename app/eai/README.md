# Earnings-AI (`app/eai`)

미국 실적 컨퍼런스콜 원문을 수집·구조화하고, 런타임에 LLM을 호출해 의미 분석·요약·톤/상충
분석을 수행한 뒤, **코드가** 근거 검증과 점수를 계산해 산업·밸류체인 투자 테마를 발굴하는
서브시스템입니다. 기존 가격 스크리너(`app/screener.py`, `app/flat/` 등)와 완전히 격리되어
`/api/eai/*` 네임스페이스로 동작합니다.

설계 전문: [`docs/DESIGN_earnings_ai.md`](../../docs/DESIGN_earnings_ai.md) ·
Phase 2 보고: [`docs/PHASE2_REPORT.md`](../../docs/PHASE2_REPORT.md)

## 핵심 원칙
- LLM = 의미 해석/요약/번역/톤·상충. **코드 = 수집·집계·점수·근거검증·시점관리·재시도**.
- 모든 결론에 회사·분기·발언자·paragraph_id·**영어 원문** 근거 연결. 근거 부족 시 `insufficient_evidence`.
- Evidence 자동통과 = normalized exact substring. Fuzzy는 수동검토(자동통과 불가).
- Narrative Momentum ↔ Fundamental Confirmation 분리. 모든 점수는 **Experimental**.
- 모델 ID·Provider·유니버스·Ontology·Score 가중치는 설정/env로 교체.

## 레이아웃
```
config.py  db.py  ontology.py  router.py
models/            SQLAlchemy 테이블 (spec §20)
schemas/           Pydantic: enums, LLM I/O 계약
services/          textnorm evidence scoring preprocess ingest pipeline themes jobs queries universe llm_runner
providers/         transcript/ financial/ llm/ storage/   (mock+real, 팩토리)
prompts/           버전화된 stage 프롬프트
tasks/             celery_app (durable queue, 50개+)
fixtures/          6개 기업 합성 트랜스크립트·재무 (generate.py로 재생성)
```

## 실행
```bash
pip install -r ../../requirements-eai.txt
uvicorn app.main:app --port 8000
curl -X POST localhost:8000/api/eai/seed
curl -X POST "localhost:8000/api/eai/jobs/run-batch?wait=true"
curl localhost:8000/api/eai/themes
python -m pytest ../../tests/eai -q      # 30 tests
```
기본 Provider는 mock(오프라인). 실제 LLM: `EAI_LLM_PROVIDER=anthropic`,
`EAI_ANTHROPIC_API_KEY`, `EAI_FAST_MODEL/EAI_BALANCED_MODEL/EAI_DEEP_MODEL`.

## 배포 모델 — GitHub Pages 자동 갱신 (기존 프로그램과 동일)
로컬/Docker는 개발용입니다. **운영은 다른 카드(신고가·수주잔고 등)와 똑같이**
"GitHub Actions가 매일 분석해 JSON을 커밋 → Pages가 정적 서빙"입니다.

1. **매일 분석**: `.github/workflows/eai.yml`(cron 08:00 UTC)이
   `python -m app.eai.export --out data/eai` 를 실행해 스냅샷 JSON을 `data/eai/`에 커밋.
   - **비용 절감**: `EAI_LLM_CACHE_FILE=data/eai/llm_cache.json` 로 **바뀐 콜만** 과금(§9).
2. **게시**: 기존 `build.py`가 `data/eai/*.json`을 `site/data/eai/`로 복사하고,
   허브에 **📞 카드**(`app/static/eai/`)가 표시됨(바닐라 정적 페이지, `../data/eai/*.json` 읽음).
3. **실제 컨콜 원문 — 두 가지 방식**:
   - **(A) 인터넷에서 자동 수집(권장)**: 라이선스된 트랜스크립트 API에서 매일 자동으로 가져옵니다.
     각 티커에 대해 최근 `tracked_quarters` 분량을 자동 수집·분석. ⚠️ 무단 스크래핑이 아니라
     **라이선스 API**만 사용하며, 전체 원문은 재배포하지 않고 파생 분석과 검증된 짧은 인용만 저장/표시.
     - **Alpha Vantage** (무료 ~25 req/day, MVP 테스트 적합):
       Variable `EAI_TRANSCRIPT_PROVIDER=alphavantage` + Secret `EAI_ALPHAVANTAGE_API_KEY`
     - **FMP / 호환 유료 API** (커버리지·볼륨 큼):
       Variable `EAI_TRANSCRIPT_PROVIDER=fmp` + Secret `EAI_TRANSCRIPT_API_KEY`
       (`EAI_TRANSCRIPT_API_BASE`로 호환 API 지정 가능)
   - **(B) 파일 드롭**: Variable `EAI_TRANSCRIPT_PROVIDER=directory` + `data/eai/transcripts/`에
     `<TICKER>_<FY>Q<Q>.json`(또는 `.txt`) 커밋.
   실제 LLM은 Secret `EAI_ANTHROPIC_API_KEY` + Variable `EAI_LLM_PROVIDER=anthropic` + 모델 Variable.

> 참고: 라이브 Pages 사이트에 반영하려면 이 브랜치를 **배포 브랜치로 병합**해야 합니다
> (현재 Pages 배포는 `daily.yml` 기준). 병합 전까지는 `data/eai/`에 커밋된 **mock 스냅샷**이
> 프로토타입으로 표시됩니다.

정적/라이브 겸용: 페이지는 정적 모드에서 `../data/eai/*.json`, 로컬(FastAPI) 모드에서
`/api/eai/*` 를 읽습니다(`config.js`의 `SUH_DH_STATIC` 토글, 기존 페이지와 동일).
