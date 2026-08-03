# Phase 2 보고서 — 6개 기업 MVP

> 대상: NVDA · MSFT · JPM · WMT · CAT · XOM (각 최근 2개 분기) · 브랜치 `claude/us-earnings-investment-themes-695ie0`
> 목적(spec §23): 투자 테마의 유효성 확정이 아니라 **기술 파이프라인 검증**. 결과에는 **Prototype / Insufficient Breadth**를 표시하고 High Conviction 테마를 생성하지 않음.

## 1. 실제 실행 여부

이 환경에서 **엔드투엔드로 실제 실행·검증**했습니다(외부 네트워크·LLM 키 없이 오프라인).

- **DB**: 설정으로 Postgres/SQLite 전환. MVP는 SQLite(aiosqlite)로 실제 구동. Postgres는 `docker-compose.yml` + Alembic로 준비(초기 마이그레이션 자동생성 확인).
- **LLM**: `MockLLMProvider`로 파이프라인 전 구간 실행. 실제 `AnthropicProvider`는 코드 경로 구현(모델 ID는 env 등급 지정, 키 없으면 명확히 `LLM analysis unavailable`).
- **파이프라인**: seed → ingest(중복/버전 검사) → 파싱(paragraph_id·Prepared/Q&A·Q&A 링크·Chunk) → Stage1 추출 → **Evidence exact 검증** → Stage2 요약 → **코드 Score 계산** → Stage3 QoQ → Stage4 Cross-company(코드 Theme Score) → Stage5 Investment Theme(코드 conviction) 까지 6개 기업 12개 콜 전부 처리.

## 2. 테스트 결과

```
python -m pytest tests/eai/ -q   →  30 passed
```

| 파일 | 커버 |
|---|---|
| `test_preprocess.py` | paragraph_id 포맷, Prepared/Q&A 분리, Speaker 식별, 질문-답변 링크, Chunk 경계, 해시/정규화 |
| `test_evidence.py` | exact substring 통과·offset, 숫자 토큰 검증, 존재하지 않는 paragraph_id 차단, **Fuzzy는 수동검토(자동통과 불가)**, 정규화, 버킷 카운트 |
| `test_scoring.py` | Narrative/Fundamental 분리, 검증 KPI 부족 시 강제생성 금지, 분류 매트릭스, Theme breadth 게이트, 결측 미정규화, 빈도만으론 만점 불가, Incremental 중복 페널티 |
| `test_pipeline_e2e.py` | 6×2 콜 전체 배치, Evidence↔Verification 정합, 모든 verified 근거가 실제 substring, Score Experimental, MVP conviction=low·Prototype 라벨 |
| `test_api.py` | health/ontology, seed→run-batch→대시보드/기업/테마/보드/usage/coverage, **업로드 checksum 중복 방지** |

프론트엔드: `npm run build` 성공(8개 라우트 컴파일, `tsc --noEmit` 0 오류).

## 3. 비용

MVP는 MockLLM이라 **실제 API 비용 $0**. 모든 호출은 `model_usage`에 토큰·estimated_cost·processing_time·retry_count·cache_hit·status로 기록되며 `/api/eai/usage`와 “작업·비용” 화면에서 집계됩니다. 실제 Anthropic 전환 시 `AnthropicProvider`가 usage로 실비용을 채웁니다(공개 단가 기준 근사, 설정 가능).

## 4. 구현 범위 (spec §11-16 매핑)

- LLM/코드 역할 분리: LLM은 의미·요약·번역·톤/상충만, **Score·집계·검증·시점관리는 코드**(§1-4).
- Narrative Momentum ↔ Fundamental Confirmation **분리 계산**, 5단계 분류(§13).
- Theme Score(Breadth25/Momentum20/Intensity15/Persistence10/ValueChain15/Numeric15, 설정 교체), breadth 게이트·결측 방지(§14).
- Evidence: normalized exact substring 자동통과, Fuzzy 자동통과 금지→needs_manual_review, 숫자·단위 검증, insufficient_evidence(§16).
- 시점 관리: `analysis_as_of` Look-ahead 차단(§5), fiscal/calendar quarter 분리 저장.
- Provider 교체(Transcript/Financial/LLM/Storage), 모델 등급 env, Prompt/Ontology/Score 버전(§8·§20).
- Job 8상태 + 서버 재시작 복구(`recover_incomplete`) + 부분 실패 지속(§2·§23).
- UI(한국어): 마켓 테마 / 기업 / 투자 아이디어 / 유니버스 커버리지 / 작업·비용, Evidence 토글, Experimental·Prototype 표기.

## 5. 알려진 제한사항

1. **트랜스크립트/재무 데이터가 합성 픽스처**입니다. 실제 API/IR 어댑터(`TranscriptProvider`·SEC 등)는 슬롯만 있고 미구현(라이선스 확인 후 후속 Phase). 무단 스크래핑·전체 원문 재배포는 기본 미제공.
2. **MockLLM은 테스트 더블**로, 규칙 기반이라 실제 의미 분석 품질을 대변하지 않습니다. 운영 품질은 Anthropic 연결 후 재평가 필요. (Mock 결과는 provider=mock으로 명시 기록.)
3. **Celery는 코드·compose로 준비**되어 있으나 MVP 실행 경로는 asyncio 인라인/백그라운드입니다(50개+에서 Celery 정식 도입, Phase 4).
4. **Prompt Caching**은 Capability로 설계·게이팅했으나 Mock에서는 미작동(Anthropic에서 prefix 캐시 활성).
5. **초기 Alembic 마이그레이션은 SQLite 기준 autogenerate** 결과입니다. Postgres 정식 배포 전 재생성/검토 권장(타입은 이식 가능하게 선택).
6. 6개 기업이라 **Theme Score/Investment Theme는 Prototype**이며 High Conviction·정량 백테스트는 범위 밖(§14).
7. 이 샌드박스에는 기존 앱의 pandas/numpy 등이 미설치라 **기존 가격 스크리너 테스트는 여기서 미실행**(eai는 완전 격리되어 영향 없음, `app/main.py`는 eai를 try/except로 mount).

## 6. 로컬 실행

```bash
# 백엔드 (SQLite, LLM=mock 기본)
pip install -r requirements-eai.txt
uvicorn app.main:app --port 8000          # /api/eai/* 제공
#   → POST /api/eai/seed, POST /api/eai/jobs/run-batch?wait=true

# 프론트엔드
cd frontend && npm install && npm run dev  # http://localhost:3000

# 전체 스택(Postgres·Redis·worker 포함)
docker compose up --build

# 실제 LLM 연결
export EAI_LLM_PROVIDER=anthropic EAI_ANTHROPIC_API_KEY=... \
       EAI_FAST_MODEL=... EAI_BALANCED_MODEL=... EAI_DEEP_MODEL=...
```

## 7. 다음 단계 (Phase 3, 20개 기업)

섹터별 복수 기업 확보 → Value-chain/Contradiction 신호 → Universe Coverage 고도화 → Human Review 저장 → Incremental Information Score 검증 → 최소 Breadth 기준 상향. (실제 트랜스크립트 소스 어댑터 확보가 선행 과제.)
