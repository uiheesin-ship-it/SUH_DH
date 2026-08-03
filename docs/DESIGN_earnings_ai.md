# 미국 실적 컨퍼런스콜 기반 투자 테마 발굴 시스템 — 설계안 (Phase 1)

> 상태: **설계 제안 (승인 대기)** · 작성일 2026-08-03 · 브랜치 `claude/us-earnings-investment-themes-695ie0`
> 이 문서는 구현 전 설계안입니다. 아직 대규모 구현 코드는 작성하지 않았습니다.

---

## 0. 코드베이스 분석 결과 (1·2번 항목)

### 0.1 기존 스택 (확인된 사실)

| 영역 | 현재 상태 |
|---|---|
| Backend | **FastAPI (Python 3.11)** + uvicorn, 단일 `app/main.py`에 라우터 집약 |
| 영속화 | **DB 없음.** `data/*.json` 파일 + `app/cache.py`의 인메모리 TTL 캐시 |
| Frontend | **바닐라 JS/HTML/CSS** (`app/static/<page>/`), TypeScript·프레임워크·번들러 없음 |
| 데이터 소스 | Finviz, yfinance, FinanceDataReader, OpenDART, RSS(feedparser) |
| "번역/의미" | `deep-translator`(무료 Google) — **LLM 아님** |
| 큐/비동기 | **없음.** 동기 함수 + TTL 캐시. `async def` 백엔드 코드 0건 |
| 배포 | GitHub Pages(정적 `build.py`→`site/`) + Render(FastAPI) + GH Actions cron |
| 알림 | Telegram (`notify_telegram.py`, `app/telegram.py`) |
| 설정 | **YAML 설정 주도** (`config.yaml`, `flat_config.yaml`) → `app/*/config.py`가 로드 |
| 테스트 | pytest 오프라인 단위테스트 (`tests/`) |

기존 앱의 **도메인은 "가격 액션 스크리너"**(52주 신고가, 평평 베이스, 수주잔고, 실적 드리프트)로, 이번 요구사항인 **"컨퍼런스콜 의미 분석 + 투자 테마 발굴"과 도메인이 완전히 다릅니다.** 재사용은 인프라·패턴 수준에서 이루어집니다.

### 0.2 재사용 가능한 자산

- **FastAPI 앱 구조 + Render/GH Actions 배포 파이프라인** — 그대로 확장.
- **설정 주도 철학** (`config.yaml` → `config.py` 로더) — Topic Ontology·Score 가중치·유니버스를 동일 패턴으로.
- **`app/cache.py` TTL 캐시 패턴** — Redis 캐시로 승격하되 인터페이스 개념 유지.
- **`app/earnings.py` + `data/guidance.json`** — 이미 "가이던스 vs 컨센서스"를 큐레이션 JSON으로 관리. → `FinancialDataProvider`의 **Guidance 레이어 씨앗**으로 직접 재활용.
- **`app/dartdoc.py`** — 공시 문서(zip/XML) 다운로드·표 파싱 + "모든 수치에 원본 문자열·단위·뷰어 링크 보존" 원칙. → **Evidence·출처 추적 철학의 선례**로 계승(단, 대상은 미국 SEC/IR).
- **`app/demo_data.py` + `SUH_DH_DEMO` 모드** — 네트워크 없이 UI/테스트. → `MockTranscriptProvider`·`MockLLMProvider`의 선례.
- **`app/translate.py`** — 폴백 안전 패턴(실패 시 원문 유지). LLM 번역으로 대체하되 폴백 원칙 계승.

### 0.3 유지·격리 원칙

기존 가격 스크리너(`app/screener.py`, `app/flat/`, `app/base*`, `app/krhighs*`, `app/backlog.py`, `app/news.py` 등)는 **재작성하지 않고 그대로 운영**합니다. 신규 시스템은 **같은 저장소·같은 FastAPI 프로세스** 안에 **독립된 바운디드 컨텍스트 패키지 `app/eai/`**(Earnings-AI)로 추가합니다. 라우트는 `/api/eai/*`로 네임스페이스를 분리해 기존 `/api/*`와 충돌하지 않습니다.

---

## 1. 기술 스택 선택 및 근거 (2·3번 항목)

### 결정: **Python / FastAPI 백엔드로 확장** (기본안 채택, NestJS 대안 기각)

| 판단 기준 | 근거 |
|---|---|
| 기존 백엔드 언어 | **100% Python/FastAPI.** Node/TS 백엔드 0줄. |
| 기존 프론트 | 바닐라 JS — **TypeScript조차 아님.** "TS 중심이라 Node 유지가 명확히 유리"한 조건에 해당하지 않음. |
| 요구 기본안 | FastAPI·Pydantic·SQLAlchemy·Alembic·PostgreSQL·Redis·Celery — 기존 Python 자산과 **정렬**. |
| LLM 생태계 | Anthropic/OpenAI Python SDK, 구조화 출력, 토큰 계산 라이브러리가 Python에서 성숙. |
| 데이터 처리 | 트랜스크립트 파싱·정규화·수치 검증에 pandas 등 기존 Python 도구 활용. |

→ **요구사항의 "TypeScript 중심일 때만 NestJS" 예외에 해당하지 않으므로, 두 스택을 혼합하지 않고 FastAPI 단일 백엔드로 확정합니다.**

### 확정 스택

| 레이어 | 선택 |
|---|---|
| Frontend | **Next.js(App Router) + TypeScript + Tailwind + TanStack Query + Zod** — 신규 `frontend/` 디렉터리 (대시보드·Evidence 팝업·리뷰 워크플로에 바닐라 JS는 부적합) |
| Backend | **FastAPI + Pydantic v2** (기존 `app/` 확장, 신규 `app/eai/`) |
| ORM/마이그레이션 | **SQLAlchemy 2.0 (async) + Alembic** |
| DB | **PostgreSQL 16** (JSONB·전문검색·`pgvector`(선택, Fuzzy 후보 탐색용)) |
| 캐시 | **Redis** (LLM 응답 캐시·레이트리밋·Celery 브로커 결과) |
| 큐 | **Celery** (Redis broker) — 50개 이상 정식 배치. MVP는 동기/asyncio 허용 |
| 파일 저장 | MVP **로컬** → 프로덕션 **S3 호환**(추상 `ObjectStore` 인터페이스) |
| 테스트 | Pytest(백엔드), Vitest(프론트 단위), Playwright(E2E) |
| 컨테이너 | Docker Compose (postgres·redis·backend·worker·beat·frontend) |

> 기존 가격 스크리너는 DB 없이 계속 동작하며, 신규 시스템만 Postgres/Redis/Celery를 사용합니다(**가산적 확장**, 기존 동작 무손상).

---

## 2. 전체 시스템 아키텍처 (3번 항목)

```
┌────────────────────────────────────────────────────────────────────┐
│ Frontend  (Next.js App Router, TS, Tailwind, TanStack Query, Zod)   │
│  Market Theme / Company / Cross-company Theme / Investment Board /   │
│  Universe Mgmt / Job&Cost  ── 한국어 UI, Zod로 API 응답 검증        │
└───────────────┬────────────────────────────────────────────────────┘
                │ REST (/api/eai/*)  JSON, Zod ↔ Pydantic 스키마 공유
┌───────────────▼────────────────────────────────────────────────────┐
│ FastAPI (app/eai)                                                    │
│  Routers → Services (도메인 로직) → Repositories (SQLAlchemy)        │
│  · Providers: Transcript / Financial / LLM / ObjectStore            │
│  · Scoring(코드 계산) · Evidence Verifier · Job Orchestrator        │
└──────┬───────────────────────┬───────────────────────┬──────────────┘
       │                       │                       │
┌──────▼──────┐        ┌───────▼────────┐      ┌───────▼──────────┐
│ PostgreSQL  │        │ Redis          │      │ Celery Workers   │
│ (원문·구조화│        │ (캐시·브로커·   │      │ (Stage1~5 태스크,│
│  ·점수·감사)│        │  레이트리밋)    │      │  재시도·복구)    │
└─────────────┘        └────────────────┘      └──────┬───────────┘
                                                       │
                       ┌───────────────────────────────▼─────────────┐
                       │ 외부: LLM API(Anthropic/…) · Transcript/IR   │
                       │       · SEC/재무 API · S3(prod)             │
                       └──────────────────────────────────────────────┘
```

**레이어링 규칙**
- Router는 얇게(검증·직렬화만), 도메인 로직은 Service, DB 접근은 Repository.
- LLM은 **의미 해석만**, 최종 Score/Incremental Score는 **코드가 계산**(요구 §1-5, §14).
- 모든 결론 → Evidence(회사·분기·발언자·paragraph_id·영어 원문)로 연결(요구 §16).

---

## 3. 데이터 흐름 (5번 항목)

```
[수집] TranscriptProvider ─▶ source_documents ─▶ transcript_documents(+version, checksum)
[수집] FinancialProvider  ─▶ source_documents ─▶ financial_metrics / guidance_metrics (verified)
   │
[전처리] 파싱 ─▶ speakers / transcript_paragraphs(paragraph_id, hash, section, offset)
   │                    └─ Prepared/Q&A 분리, 질문-답변 연결, 의미단위 Chunk
   │
[LLM Stage1] chunk_analysis / topic_mentions (+evidence_links, insufficient_evidence)
   │
[검증] Evidence Verifier(정규화 exact substring, offset, hash, 숫자·단위) 
   │        └─ 실패→needs_manual_review, Fuzzy는 후보탐색 보조만
   │
[LLM Stage2] call_summaries (executive_summary_ko, prepared_vs_qa_gap, narrative_vs_numbers_gap …)
   │
[코드] Narrative Momentum / Fundamental Confirmation (검증 KPI만) ─▶ score_versions
   │
[LLM Stage3] quarterly_comparisons (신규·가속·지속·약화·소멸, 분기 가중치는 코드)
   │
[LLM Stage4] cross_company_themes / theme_components  ── analysis_as_of 이전 자료만(Look-ahead 차단)
[코드] Theme Score = Breadth·Momentum·Intensity·Persistence·ValueChain·Numeric (가중치=설정)
   │
[LLM Stage5] investment_themes (conviction, narrative_confirmation_status)
   │
[코드] Incremental Information Score / Universe Coverage / Dynamic 후보
   │
[UI] 대시보드 · 다운로드 · 알림
```

핵심: **LLM 출력은 항상 구조화 스키마 + Evidence를 반환**하고, **집계·점수·필터·시점 관리는 코드**가 담당합니다.

---

## 4. LLM 호출 흐름 (6·8·11번 항목)

### 4.1 모델 등급 (하드코딩 금지)

| 논리 등급 | 용도 | 실제 모델 ID |
|---|---|---|
| `FAST_EXTRACTION_MODEL` | 문단 분류·번역·기초 Topic 추출 (Stage1) | 설정/환경변수 |
| `BALANCED_ANALYSIS_MODEL` | Call 요약·QoQ 비교 (Stage2·3) | 설정/환경변수 |
| `DEEP_REASONING_MODEL` | Cross-company·Investment Theme (Stage4·5) | 설정/환경변수 |

`.env` 예: `EAI_FAST_MODEL=…`, `EAI_BALANCED_MODEL=…`, `EAI_DEEP_MODEL=…`. 코드에는 등급명만.

### 4.2 호출 파이프라인 (요청당 원자적, 거대 단일요청 금지)

```
build_prompt(고정 Prefix + 가변 Body)
  · Prefix(캐시 대상): System·Ontology·JSON Schema·Evidence Rules·Few-shot
  · Body(가변): Company meta·Transcript chunk·직전분기 분석·검증 KPI
        │
call(model_tier, capabilities)
  · supports_structured_output? → native structured / strict tool schema 우선
  · supports_prompt_caching?    → prefix 캐시 헤더, 아니면 일반 호출
  · 미지원 파라미터는 전달 안 함(temperature/thinking 등 capability 게이팅)
        │
validate: Pydantic → Enum/range → Evidence exact-match
  · 실패 필드만 담은 Repair Request로 재요청(최대 N회)
  · 초과 시 status=failed | needs_manual_review
        │
persist: chunk_analysis + model_usage(토큰·비용·cache_hit·retry_count·prompt_version·ontology_version)
```

- **LLM 불가 시** "LLM analysis unavailable" 명시(키워드 결과를 LLM 분석처럼 표시 금지, 요구 §8).
- **DB 캐시 재사용 키**: (원문 hash, prompt_version, model_id, ontology_version) 동일 시 재계산 생략(요구 §9).

---

## 5. Provider 구조 (7·8번 항목)

### 5.1 TranscriptDataProvider (요구 §6.1)

```python
class TranscriptDataProvider(Protocol):
    def list_available(self, ticker, since=None) -> list[TranscriptRef]: ...
    def fetch(self, ref) -> RawTranscript:   # exact_text 보존, checksum, license_note
        ...

# 우선순위 체인: 정식API → 기업 IR → 웹캐스트/텍스트 → 사용자 업로드 → 기타 허용 소스
TranscriptProvider              # 정식 Transcript API 어댑터 (구현 슬롯)
CompanyIRTranscriptProvider     # 기업 공식 IR
ManualUploadTranscriptProvider  # .txt/.json/.pdf 업로드  ← MVP 우선
MockTranscriptProvider          # 오프라인/테스트         ← MVP 우선
```

- 저장 필드: company, ticker, fiscal_year/quarter, calendar_quarter, call_date, source, source_identifier, source_url, language, retrieval_date, transcript_version, is_complete, checksum, license_note.
- **중복 방지**(checksum) · 원문 변경 시 **새 버전 저장 + 변경분만 재분석**.
- **라이선스 미확인 무단 스크래핑 기본 금지**, 전체 영어 원문 공개 재배포 기능 미제공(요구 §6.1). Seeking Alpha/StockEasy는 UX 참고용만.

### 5.2 FinancialDataProvider (요구 §6.2)

```python
class FinancialDataProvider(Protocol):
    def fetch_kpis(self, ticker, fiscal_period) -> list[VerifiedKPI]: ...
    def fetch_guidance(self, ticker, fiscal_period) -> list[GuidanceMetric]: ...

EarningsReleaseProvider   # 실적발표문 / 10-Q / 10-K
IRPresentationProvider    # IR 자료·공식 Guidance Table
StructuredFinancialAPIProvider  # 허가된 재무 API
ManualUploadFinancialProvider   # 사용자 업로드
GuidanceJSONProvider      # ← 기존 data/guidance.json 재활용(씨앗)
```

- KPI 필드: company, ticker, fiscal_period, metric_id/name, value, unit, currency, gaap_or_non_gaap, actual_or_guidance, period_start/end, comparison_basis, source_document_id, source_page, source_paragraph_id, published_at, confidence, verification_status.
- **트랜스크립트 추출 KPI vs 공식자료 충돌 시 공식자료 우선 + 차이 별도 표시.**
- **Fundamental Confirmation Score는 verified KPI만 사용**(요구 §6.2, §13).

### 5.3 LLMProvider (요구 §8)

```python
class LLMProvider(Protocol):
    capabilities: Capabilities   # supports_structured_output/tool_schema/prompt_caching/
                                 # batch/temperature/thinking, maximum_context_length
    def complete(self, tier, prompt, schema=None, **opts) -> LLMResult: ...

AnthropicProvider      # 1차 구현
AlternativeProvider    # 교체 가능 슬롯
MockLLMProvider        # 오프라인/테스트(고정 구조화 응답)
```

- API Key는 **환경변수/Secret**에서만. 코드 하드코딩 금지.
- 미지원 파라미터 공통 전달 금지 → capability 게이팅.

### 5.4 ObjectStore

```python
class ObjectStore(Protocol):
    def put(self, key, data, content_type) -> str: ...
    def get(self, key) -> bytes: ...

LocalObjectStore   # MVP
S3ObjectStore      # 프로덕션(S3 호환)
```

모든 Provider는 **설정(`eai_config.yaml` / env)으로 교체**(요구 §1-12).

---

## 6. DB 스키마 초안 (10·20번 항목)

PostgreSQL. 요구 §20의 테이블 전부 포함. 핵심 관계만 요약(전체 컬럼은 Alembic 마이그레이션에서 확정).

### 6.1 유니버스·회사
- **companies**(id, ticker, name, cik, country, sector, industry, is_active)
- **company_universe_types**(company_id, type: core|specialist|dynamic, tracked_quarters, added_at)
- **company_signal_roles**(company_id, role: capex/demand/pricing/credit/inventory/labor/tech_adoption/commodity/supply_chain/consumer_health) — **다대다**(중복 등록 대신 복수 역할)
- **company_value_chain_positions**(company_id, position, description)
- **universe_change_history**(company_id, action: add|remove|promote|demote, reason, proposed_by: system, approved_by, approved_at)
- **incremental_information_scores**(company_id, components JSONB, score, score_version, computed_at) — Experimental

### 6.2 문서·원문
- **source_documents**(id, company_id, doc_type, source, source_url, checksum, published_at, retrieved_at, storage_key, license_note)
- **transcript_documents**(id, company_id, fiscal_year, fiscal_quarter, calendar_quarter, call_date, event_date, language, is_complete, current_version_id, +시점필드 전부)
- **transcript_versions**(id, transcript_id, version_no, checksum, raw_storage_key, created_at)
- **speakers**(id, transcript_version_id, name, role: operator/ceo/cfo/other_mgmt/analyst, company)
- **transcript_paragraphs**(id, transcript_version_id, **paragraph_id**(예 `NVDA_2026Q2_QA_CFO_015`), section_type, speaker_id, sequence_number, exact_text_en, normalized_text_en, preceding_question_id, answer_to_question_id, paragraph_hash)

### 6.3 재무
- **financial_metrics** / **guidance_metrics** (§5.2 필드, verification_status 포함)

### 6.4 작업
- **analysis_jobs**(id, kind, scope JSONB, **status**: pending|queued|running|partially_completed|completed|failed|cancelled|needs_manual_review, priority, progress JSONB, created_at, updated_at, resumable) — **서버 재시작 후 복구**(§2·§23)
- **chunk_analysis**(id, job_id, transcript_version_id, chunk_ref, status, raw_llm_output JSONB, model_id, prompt_version, ontology_version)

### 6.5 분석 산출물
- **topic_mentions**(§11 Stage1 필드 전부: direction/intensity/confidence/management_initiated/… + topic_id FK)
- **call_summaries**(§11 Stage2)
- **quarterly_comparisons**(§11 Stage3, 비교분기·paragraph_id 연결)
- **cross_company_themes** / **theme_components**(§11 Stage4, breadth·momentum·persistence 등)
- **investment_themes**(§11 Stage5, conviction, narrative_confirmation_status)

### 6.6 Evidence·검증
- **evidence_links**(id, claim_ref(polymorphic: topic_mention/theme/…), paragraph_id, exact_quote_en, translation_ko, quote_start_offset, quote_end_offset, paragraph_hash, evidence_reason)
- **evidence_verifications**(evidence_id, verification_method, verification_status, numeric_check JSONB, verified_at)

### 6.7 버전·감사·비용
- **prompt_versions** / **ontology_versions** / **score_versions**(가중치·임계값 스냅샷)
- **user_corrections**(§17: original_value, corrected_value, corrected_by, corrected_at, correction_reason, prompt_version, ontology_version, model_id) — **원본 LLM 결과 미덮어쓰기**
- **model_usage**(§9 필드 전부: input/output_tokens, estimated_cost, processing_time, cache_hit, status …)
- **provider_errors**(provider, error_type, payload, occurred_at)
- **topics**(ontology_version_id, topic_id, name_en, name_ko, category, parent_id, status: active|new_topic_candidate)
- **watchlists**(user, filters JSONB, name)

**재현성**: 원문·구조화결과·번역·prompt_version·model_id·ontology_version·score_version을 분리 저장 → 과거 결과 재현 가능(요구 §20).

---

## 7. 폴더 구조 초안 (11번 항목)

기존 자산 유지 + 신규 격리:

```
SUH_DH/
├── app/                      # (기존) 가격 스크리너 — 유지
│   ├── main.py               #  → app.eai.router 를 include만 추가
│   ├── screener.py, flat/, base*, krhighs*, backlog.py, news.py …
│   └── eai/                  # ★ 신규 바운디드 컨텍스트 (Earnings-AI)
│       ├── __init__.py
│       ├── router.py         # /api/eai/* 라우트 집약
│       ├── config.py         # eai_config.yaml 로더(기존 패턴 계승)
│       ├── db.py             # async engine/session
│       ├── models/           # SQLAlchemy 모델(§6 테이블)
│       ├── schemas/          # Pydantic v2 스키마(LLM I/O·API)
│       ├── repositories/     # DB 접근
│       ├── services/         # 도메인 로직
│       │   ├── ingest.py preprocess.py evidence.py scoring.py
│       │   ├── pipeline.py   # Stage1~5 오케스트레이션
│       │   ├── universe.py incremental.py coverage.py
│       ├── providers/
│       │   ├── transcript/  financial/  llm/  storage/
│       ├── tasks/            # Celery 태스크(Stage별) + celery_app.py
│       └── prompts/          # 버전화된 프롬프트·few-shot
├── frontend/                 # ★ 신규 Next.js(App Router, TS)
│   ├── app/                  # 6개 페이지(§18)
│   ├── lib/                  # api client, zod 스키마
│   └── ...
├── eai_config.yaml           # ★ 유니버스·Ontology·Score 가중치·Provider 설정
├── alembic/                  # ★ 마이그레이션
├── docker-compose.yml        # ★ postgres·redis·backend·worker·beat·frontend
├── tests/                    # 기존 + eai 백엔드 테스트
├── frontend/tests, e2e/      # Vitest, Playwright
├── config.yaml, flat_config.yaml, build.py, render.yaml …  # (기존) 유지
└── docs/DESIGN_earnings_ai.md
```

---

## 8. Topic Ontology 초안 (12번 항목)

**문자열 키워드가 아닌 의미 단위 Topic** + 버전 관리. `eai_config.yaml`/관리화면에서 편집. 신규 발견 시 `new_topic_candidate` → 사용자 승인 후 정식 등록.

- **공통 Topic**(요구 §10 전부): Demand Growth/Weakness, Pricing Power, Discounting, Inventory Build/Destocking, Supply Constraint/Normalization, Capex, Hiring/Layoffs, Wage Pressure, Productivity, Consumer Weakness, Credit Deterioration, Delinquency, Interest Rates, FX, Tariffs, Regulation, AI Adoption, Automation, Data Center Investment, Power Demand, Cloud Optimization, Cybersecurity Spending, Geographic Demand.
- **산업 하위 Topic**: 반도체(HBM, Advanced Packaging, Foundry Utilization, Lead Time, Wafer Demand, AI Accelerator Demand, Networking Bottleneck), 은행(NIM, Deposit Beta, Charge-off, Delinquency, Loan Growth, Credit Provision), 소비(Traffic, Ticket Size, Promotional Activity, Trade-down, Discretionary Spending), 산업재(Order Growth, Backlog, Book-to-bill, Lead Time, Pricing vs Cost, Dealer Inventory).

`ontology_versions`로 스냅샷 → 과거 분석 재현.

---

## 9. Evidence Verification 설계 (13번 항목, 요구 §15·§16)

**자동 통과 기준 = normalized exact substring match.**

```
정규화(제한적): 공백 · 줄바꿈 · 따옴표문자 · Unicode 정규화 (그 이상 변형 금지)
검증 순서:
 1. Provider structured output      2. Pydantic/Zod 스키마
 3. Enum/range 검증(direction·intensity 0~5·confidence 0~1)
 4. Evidence: paragraph_id 존재? exact_quote_en ⊂ normalized_paragraph? offset·hash 일치?
 5. 숫자 포함 시 → 숫자·통화·비율·기간·단위 별도 검증
 6. 실패 필드만 Repair Request → 재시도 초과 시 failed|needs_manual_review
```

- **Fuzzy Match는 자동 통과 불가** — 근접 후보 문단 탐색 보조만. Fuzzy-only Evidence는 `needs_manual_review`로 표시하고 **확정 Evidence 수·Numeric Confirmation·Fundamental Confirmation·High Conviction에서 제외**(요구 §16).
- 자동 검출 오류: JSON 파싱실패, 필수필드 누락, 잘못된 Enum, 없는 paragraph_id, Evidence 없는 주장, 범위 오류, Prepared/Q&A 혼동, Analyst Question을 Management Initiated로 오분류, 원문과 다른 수치, Speaker 불일치(요구 §15).
- 근거 부족 → 사실 생성 금지, **`insufficient_evidence` 표시**(요구 §1-8).

---

## 10. Score 계산·버전 관리 설계 (14번 항목, 요구 §4·§13·§14)

**모든 Score는 코드가 계산.** LLM은 원자료(direction·intensity·구체성 등)만 제공. 모든 Score는 **Experimental**로 표기, 수익률 예측모델로 표현 금지.

### 10.1 Narrative vs Fundamental (요구 §13) — 별도 계산
- **Narrative Momentum**: direction·intensity·자발적강조·CEO/CFO직접·Prepared포함·반복빈도·QoQ강조증가·미래전망·전략중요성.
- **Fundamental Confirmation**: 매출성장·가이던스변화·주문·백로그·RPO/cRPO·Billings/CCB·신규/확장고객·가격·물량·마진·재고·CAPEX·산업KPI — **verified KPI만**, 최소기준 미달 시 강제 생성 금지.
- 분류: 강+강=Confirmed Acceleration / 강+약=Narrative Ahead of Numbers / 약+강=Conservative or Underpromising / 혼재=Mixed Signals / 약+약=Confirmed Deterioration.

### 10.2 Theme Score (요구 §14) — 기본 가중치(설정 교체 가능)
Breadth 25 · Momentum 20 · Intensity 15 · Persistence 10 · Value-chain Confirmation 15 · Numeric Confirmation 15 (합 100). **빈도만으론 고득점 불가**(서로 다른 기업·밸류체인 독립 확인 가중). 구성요소 부족 시 정규화 과대표시 금지 → `Data Insufficient`.

### 10.3 Incremental Information Score (요구 §4) — Experimental
New Topic Contribution · New Value-chain Position · Independent Confirmation · Contradictory Signal · Numeric Specificity · Transcript Information Density · Existing Universe Redundancy · Data Availability Reliability. 가중치=설정.

### 10.4 버전 관리
`score_versions`에 score_version·classification_rule_version·narrative_threshold·fundamental_threshold·minimum_verified_kpi_count·minimum_company_breadth·missing_component_count 저장. UI에 가중치·원시구성요소·결측치·산출일·Score Version·검증 KPI 수 명시(요구 §13).

### 10.5 분기 가중치 (요구 §5)
최신 40 / 직전 30 / 2분기전 20 / 3분기전 10 (설정 교체). **fiscal vs calendar quarter 구분 저장**. **`analysis_as_of` 이전 자료만** 사용 → Look-ahead 차단.

---

## 11. Queue · Cache · 비용 관리 설계 (15번 항목, 요구 §2·§9)

- **큐**: MVP는 asyncio/동기 백그라운드 허용. **50~150개 정식 배치는 Celery(Redis broker)**. asyncio로 운영 큐 대체 금지.
- **작업 상태**를 DB(`analysis_jobs`)에 저장 → 8가지 상태 관리, **서버 재시작 시 미완료 작업 복구**, **일부 Chunk 실패해도 전체 배치 지속**(partially_completed).
- 지원: Batch, 실패 Chunk만 재처리, 특정 기업 재분석, 신규 Transcript 증분, 큐 중단/재개, 우선순위, 기업별·분기별 진행률.
- **Cache**: (원문hash, prompt_version, model_id, ontology_version) 동일 시 DB 캐시 재사용. Redis는 레이트리밋·단기 응답 캐시. Prompt Caching은 **Optional Capability**(미지원 Provider도 일반 호출로 정상 동작).
- **비용**: `model_usage`에 토큰·estimated_cost·processing_time·retry_count·cache_hit·status 기록 → Job&Cost 페이지(§18.6).

---

## 12. Phase 2 — 6개 기업 MVP 실행 계획 (16번 항목, 요구 §23·§24)

**대상**: NVDA · MSFT · JPM · WMT · CAT · XOM, **최근 2개 분기**.
**목적**: 투자 테마 유효성 확정이 아니라 **기술 파이프라인 검증**(수집→파싱→LLM구조화→Evidence검증→KPI연결→QoQ→Score→UI→비용). 결과에 **Prototype / Insufficient Breadth** 표시. **High Conviction 테마 생성 안 함**.

**구현 순서**
1. Docker Compose(postgres·redis) + Alembic 초기 마이그레이션 + `eai_config.yaml`.
2. `ManualUploadTranscriptProvider` + `MockTranscriptProvider`, `.txt/.json/.pdf` 업로드.
3. Transcript 파싱: paragraph_id 생성, Prepared/Q&A 분리, Speaker 식별, 질문-답변 연결, 의미단위 Chunk.
4. `MockLLMProvider` + `AnthropicProvider`(구조화 출력), 모델 등급 라우팅.
5. Stage1 Chunk Extraction + Evidence exact 검증 + Repair/재시도.
6. Stage2 Call Synthesis.
7. 공식 KPI 입력/업로드(`GuidanceJSONProvider` 재활용) + 검증.
8. Stage3 QoQ Comparison(분기 가중치·시점 관리).
9. Narrative / Fundamental Score(코드) + 분류.
10. Prototype Cross-company Theme(Insufficient Breadth 표기).
11. Next.js: Market Theme Dashboard + Company Page(Evidence 토글, Original AI/Human-reviewed 구분).
12. Job & Cost 모니터링.
13. E2E(Playwright) 6개 기업 파이프라인.

**Phase 완료 보고**: 실제 실행 여부·테스트 결과·비용·알려진 제한사항. 오류는 다음 Phase 전 수정(요구 §24).

---

## 13. 주요 리스크와 대안 (17번 항목)

| 리스크 | 영향 | 대안 |
|---|---|---|
| **트랜스크립트 라이선스/스크래핑 제약** | 원문 확보 불가 | 업로드+MockProvider 우선, 정식 API 어댑터는 슬롯으로. 전체 원문 재배포 미제공 |
| **샌드박스 네트워크 차단**(현 환경 opendart/finviz 차단 관측) | CI에서 외부 호출 실패 | Mock Provider·오프라인 픽스처로 테스트, 실호출은 Actions/서버에서 |
| **LLM Evidence 환각** | 잘못된 근거 | exact-substring 강제, Fuzzy 자동통과 금지, insufficient_evidence, Repair 루프 |
| **비용 폭증**(150개×4분기×Chunk) | 운영비 | Prompt Caching·DB 캐시·증분분석·모델 등급 라우팅·Batch, `model_usage` 예산 모니터 |
| **Narrative≠Numbers 오판** | 신뢰도 하락 | 두 Score 완전 분리, verified KPI만, 임계값 버전화 |
| **Look-ahead 누출** | 백테스트 무효 | `analysis_as_of` 필터 + 테스트로 강제 |
| **작은 유니버스 과대결론** | 오도 | 6개=Prototype, High Conviction은 최소 20개+복수 밸류체인 확보 후 |
| **스키마 진화** | 마이그레이션 부담 | Alembic + JSONB raw_llm_output 병행, 버전 테이블로 재현성 확보 |
| **모놀리식 프로세스 부하** | 기존 스크리너 영향 | Celery 워커 분리, 신규 라우트 네임스페이스 격리, 필요 시 별 서비스로 분리 |

---

## 14. 구현 순서 · 변경/신규 파일 목록 (18번 항목)

### 변경(기존)
- `app/main.py` — `from .eai.router import router as eai_router; app.include_router(eai_router)` **한 줄 추가**(기존 라우트 무손상).
- `requirements.txt` — sqlalchemy[asyncio], alembic, psycopg[binary], redis, celery, pydantic-settings, anthropic, boto3, pypdf, tiktoken 등 추가.
- `render.yaml` — worker/beat 서비스·env 추가(후속 Phase).
- `.gitignore` — `.env`, `frontend/node_modules`, `frontend/.next`, `uploads/` 등.

### 신규(Phase 2 범위)
- `docker-compose.yml`, `alembic.ini`, `alembic/`(env.py + 초기 마이그레이션)
- `eai_config.yaml`
- `app/eai/`: `router.py config.py db.py`, `models/*`, `schemas/*`, `repositories/*`, `services/{ingest,preprocess,evidence,scoring,pipeline,universe,incremental,coverage}.py`, `providers/{transcript,financial,llm,storage}/*`, `tasks/*`, `prompts/*`
- `frontend/`: Next.js 스캐폴드 + `app/(dashboard|company|themes|ideas|universe|jobs)/`, `lib/{api,zod-schemas}`
- 테스트: `tests/eai/`(수집·파싱·LLM·Evidence·분석·운영), `frontend/tests/`(Vitest), `e2e/`(Playwright 6개 기업)

### 이후 Phase (요구 §24)
Phase3(20개: Value-chain/Contradiction, Coverage Dashboard, Human Review, Incremental 검증) → Phase4(≈50개: Core 확대, Celery 배치, Prompt Caching) → Phase5(≈80개 정상운영: Core50+Spec20+Dyn10, 자동업데이트·다운로드·알림·Watchlist, 150개 확장검증).

---

## 15. 승인 요청

아래를 확정해 주시면 **Phase 2(6개 기업 MVP)부터 단계별 구현**을 시작하겠습니다.

1. **백엔드 = FastAPI(Python) 확장** (NestJS 기각) — 동의?
2. **프론트 = 신규 Next.js `frontend/`**, 기존 바닐라 JS 스크리너는 유지 — 동의?
3. **신규 시스템은 `app/eai/` 격리 + `/api/eai/*`**, 기존 앱 무손상 — 동의?
4. LLM Provider **1차 = Anthropic**(모델 ID는 env로 교체) — 동의?
5. MVP는 **로컬 스토리지 + Docker Compose(postgres·redis)**, Celery는 Phase 4부터 정식 도입 — 동의?
6. 트랜스크립트는 **업로드 + Mock 우선**(정식 API는 어댑터 슬롯) — 동의?

수정·추가 요청을 반영해 설계를 확정한 뒤 구현에 착수하겠습니다.
