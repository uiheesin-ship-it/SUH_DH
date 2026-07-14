# SUH_DH 대시보드

투자/리서치 프로그램을 카드로 모아 둔 대시보드입니다. 현재 두 가지 프로그램이 있습니다.

1. **미국 52주 신고가** — 매일 미국 증시 마감 후(한국시간 아침) **52주 신고가**를 기록한
   미국 주식을 섹터·소섹터별로 한눈에.
2. **AI 투자 뉴스** — Reuters·CNBC·Yahoo Finance·DataCenterDynamics·The Register 등
   주요 외신에서 **AI·데이터센터 생태계 뉴스만** 선별해 하루 10~20건, 한국어 1~2줄 요약
   + 원문 링크로(무료 매체 우선).

아래 설명은 주로 52주 신고가 프로그램 기준이며, 뉴스 프로그램은
[AI 투자 뉴스 프로그램](#ai-투자-뉴스-프로그램) 절을 참고하세요.

**두 가지 방식으로 쓸 수 있습니다:**
1. **항상 켜져 있는 웹 주소(추천)** — GitHub가 매일 자동으로 갱신. PC를 켜둘 필요 없이
   링크만 즐겨찾기 해두고 들어가면 됩니다. → 아래 [매일 자동 갱신 웹사이트](#매일-자동-갱신-웹사이트-github-pages) 참고.
2. **내 PC에서 실행** — 클릭할 때마다 진짜 실시간 데이터. → 아래 [빠른 시작](#빠른-시작) 참고.

둘 다 화면은 똑같습니다.

- **데이터 소스**: 신고가 스크리닝은 [Finviz](https://finviz.com) `New High` 시그널,
  차트·뉴스·실적은 [Yahoo Finance](https://finance.yahoo.com) (모두 무료 소스).
- **정리 기준**: 섹터 → 소섹터(산업)별 그룹, 각 그룹 내 **시가총액 순** 정렬.
- **종목별 정보**: 티커, 전일대비 상승률, **사업 개요(한국어)**, 상승 이유(최신
  뉴스 헤드라인 한국어 번역 + 최근 실적발표 배지). 번역은 무료 Google 번역을
  사용하며 실패 시 영어 원문으로 표시됩니다.
- **차트**: 티커 클릭 시 **오른쪽에서 슬라이드되는 분할 패널**(가운데 경계를 끌어
  좌우 너비 조절). 전체기간 캔들 차트, **거래량**, **5/20/50/120일 이동평균선**
  (각각 다른 색). 드래그로 확대하면 가격축이 자동으로 맞춰지고, 거래일만 표시해
  주말 빈칸이 없습니다.

## 빠른 시작

```bash
pip install -r requirements.txt

# 실시간(라이브) 데이터로 실행
./run.sh
# 또는: python3 -m uvicorn app.main:app --port 8000

# 네트워크 없이 샘플 데이터로 UI 미리보기
./run.sh --demo
```

브라우저에서 <http://127.0.0.1:8000> 접속.

## 실시간 업데이트

- 상단의 **자동 새로고침**(기본 1분) 체크박스와 간격 선택으로 주기적 갱신.
- **새로고침** 버튼으로 즉시 갱신.
- 서버는 무료 소스의 레이트리밋을 피하려고 짧게 캐시합니다
  (신고가 목록 3분, 차트 10분, 뉴스 30분 — `SUH_DH_*_TTL` 환경변수로 조정).
- ⚠️ 무료 데이터(Yahoo/Finviz)는 실시간 대비 **약 15분 지연**될 수 있습니다.
  진짜 틱 단위 실시간이 필요하면 유료 API(Polygon, IEX 등) 연동이 필요합니다.

## ngrok로 외부에서 보기 (내 도메인)

PC에서 라이브로 띄운 대시보드를 **내 ngrok 주소로 외부(폰 등)에서** 보고 싶을 때:

```bash
# 1) 대시보드 실행 (로컬)
./run.sh                       # http://127.0.0.1:8000

# 2) 다른 터미널에서 ngrok 터널 (예약 도메인 사용)
ngrok http 8000 --url=https://japan.ngrok-free.app
#   (구버전 ngrok이면) ngrok http --domain=japan.ngrok-free.app 8000
```

위 두 단계를 **한 번에** 하려면:

```bash
./run_ngrok.sh                 # 앱 실행 + 터널을 한 명령으로 (도메인은 SUH_DH_NGROK_DOMAIN 로 변경)
```

이제 <https://japan.ngrok-free.app/> 로 들어가면 **대시보드 허브**가 뜨고, 카드에서
**📈 실적 발표 전후 주가 반응**(`/earnings/`)을 눌러 들어가면 됩니다. 이 모드는 로컬
FastAPI(`/api/*`)에 붙는 라이브라서 **아무 티커나** 조회됩니다. ngrok 무료 플랜은 접속 시
경고 페이지가 한 번 뜰 수 있고, 터널을 켜 둔 동안에만 접속됩니다(끄면 GitHub Pages 정적
사이트를 쓰세요).

## 아무 티커나 보기 (무료 백엔드 연결, 선택)

GitHub Pages는 정적 사이트라 **미리 빌드한 종목만** 조회됩니다. 임의 티커를 항상
조회하려면 **무료 백엔드 1개**를 연결하면 됩니다(리포에 `render.yaml` 포함).

1. <https://dashboard.render.com> → **New → Blueprint** → 이 저장소 연결 → 자동 배포.
   배포되면 `https://suh-dh-api.onrender.com` 같은 주소가 생깁니다.
2. 깃허브 저장소 **Settings → Secrets and variables → Actions → Variables → New variable** 에
   `SUH_DH_API_BASE = https://suh-dh-api.onrender.com` 등록.
3. **Actions → "Build & deploy dashboard" → Run workflow** 한 번 실행.

이제 Pages의 실적 페이지에서 **미리 빌드 안 된 티커**를 입력하면 이 백엔드에서 라이브로
가져옵니다(무료 플랜은 유휴 15분 후 잠들어 첫 요청이 ~30~60초 걸릴 수 있음). 로컬
`./run.sh` 의 `/api/*` 도 같은 백엔드라, ngrok 주소를 `SUH_DH_API_BASE` 로 써도 됩니다.

## 매일 자동 갱신 웹사이트 (GitHub Pages)

PC를 켜지 않아도 **고정 주소에 접속하면 매일 최신 데이터가 떠 있는** 방식입니다.
GitHub가 매일 미장 마감 후 자동으로 데이터를 갱신해 줍니다 (무료).

**최초 1회 설정 (마우스 클릭만, 약 3분):**

1. 깃허브 저장소 페이지에서 위쪽 **Settings**(설정) 탭 클릭.
2. 왼쪽 메뉴에서 **Pages** 클릭.
3. **Build and deployment → Source** 를 **`GitHub Actions`** 로 선택.
4. 위쪽 **Actions** 탭으로 이동 → 왼쪽에서 **"Build & deploy dashboard"** 선택 →
   오른쪽 **Run workflow** 버튼으로 한 번 수동 실행(첫 데이터 생성).
5. 1~3분 뒤 다시 **Settings → Pages** 로 가면 맨 위에 **사이트 주소**가 나옵니다
   (보통 `https://uiheesin-ship-it.github.io/SUH_DH/`). 이 주소를 **즐겨찾기**!

이후로는 **6시간마다** 자동 갱신되고(뉴스용), 여기에 더해 **미국 장중에는 매시간**
갱신됩니다 — 한국시간 밤 10시~아침 7시(미국 개장~마감). 미국 장은 한국 밤에만 열려
신고가가 그때만 바뀌므로, 밤에 자주 갱신하고 낮에는 갱신하지 않습니다.
즉시 갱신하고 싶으면 **Actions → Run workflow** 를 누르면 됩니다.

> 참고: 자동 실행 주기는 `.github/workflows/daily.yml` 의 `cron` 으로 조정합니다
> (`30 */6 * * *` = 6시간마다 + `0 13-22 * * 1-5` = 미국 장중 매시간, 13~22 UTC ≈
> 밤 10시~아침 7시 KST). 한 번에 차트를 만들 종목 수는 `SUH_DH_BUILD_LIMIT`(기본
> 150)로 조정합니다. 차트는 그날 마감 기준이며, 진짜 실시간 차트는 각 종목의
> **Yahoo ↗** 링크로 볼 수 있습니다.

## 동작 방식 / 구조

```
build.py                 정적 사이트 생성(GitHub Actions가 매일 실행) -> ./site
notify_telegram.py       선별된 AI 뉴스를 텔레그램 채널로 전송(30분마다)
.github/workflows/       매일 빌드 + GitHub Pages 배포, 텔레그램 전송
app/
  main.py        FastAPI 앱 + JSON API (/api/highs, /api/reason/{t}, /api/chart/{t}, /api/news)
  screener.py    Finviz "New High" 스크리닝 → 섹터/소섹터 그룹, 시총 정렬
  charts.py      Yahoo 과거 시세(차트) + 뉴스/실적(상승 이유)
  earnings.py    분기별 실적일 + EPS 컨센서스 판정 + 가이던스 vs 컨센 + 발표 전후 주가 드리프트
  news.py        주요 외신 RSS 수집 → AI/데이터센터 뉴스 선별/중복제거 → 한국어 요약
  telegram.py    텔레그램 메시지 포맷 + 전송 + 전송이력 상태(표준 라이브러리만)
  indicators.py  이동평균(MA5/20/50/120) 계산
  cache.py       짧은 TTL 인메모리 캐시
  translate.py   영어 → 한국어 번역(무료 Google, 실패 시 원문)
  demo_data.py   오프라인 샘플 데이터(SUH_DH_DEMO=1)
  static/
    index.html   대시보드 허브(런처) — 프로그램 카드 목록
    hub.css
    highs/       52주 신고가 프로그램(HTML/CSS/JS, 차트는 Plotly)
    news/        AI 투자 뉴스 프로그램(HTML/CSS/JS)
    earnings/    실적 발표 전후 주가 반응 프로그램(HTML/CSS/JS)
tools/
  guidance.py            가이던스 vs 컨센서스 큐레이션 도우미(add/consensus)
data/
  guidance.json          가이던스 vs 컨센서스 큐레이션 데이터(스키마 내장)
```

### 화면 구조 (허브 + 프로그램)

- `/` — **대시보드 허브**. 프로그램들을 카드로 보여주고 눌러서 들어갑니다.
- `/highs/` — 52주 신고가 프로그램.
- `/news/` — AI 투자 뉴스 프로그램.
- `/base/` — **베이스 스크리너** 프로그램 (아래 참고).

### 베이스 스크리너 프로그램 (`/base/`)

미국 상장 보통주 중 **"건전한 베이스(base)를 형성 중인 종목"** 을 Mark Minervini의
Trend Template을 기본으로, 여기에 **베이스 / VCP / 변동성 축소 / 거래량 감소(dry-up) /
RS 라인 신고가 / 섹터 ETF 강세** 를 정량화해 **100점 만점**으로 채점하고 watchlist로
보여줍니다. 종목을 누르면 SMA50/150/200과 **베이스 구간·피봇 라인**을 오버레이한
차트, 점수 분해, 상세 지표가 열립니다.

- **1차 유니버스**: Finviz 스크리너로 시총·주가·거래량·ETF제외·(옵션)SMA200/50 위를
  먼저 걸러 후보를 수백 개로 압축합니다(`app/base/universe.py`). 무료 데이터로 전체
  미국주식을 매번 받는 건 비현실적이라, "미리 거른 뒤 정밀분석"하는 구조입니다.
  후보 상한은 `config.yaml`의 `universe.max_candidates`(기본 300)로 조절합니다.
- **정밀분석**: 후보별 2년치 조정 일봉(Yahoo→Stooq 폴백)으로 이동평균·수익률·52주
  고저·ATR·베이스/VCP/거래량/피봇·RS 라인·섹터 액션을 계산합니다.
- **RS 백분위**: "스캔한 유니버스 내" 상대 백분위입니다(문자 그대로 전 종목이 아님).
  3/6/12개월 수익률을 `rs_composite` 가중치로 합성합니다.
- **점수 배점**(기본): 추세 25 · RS 20 · 베이스 25 · VCP/변동성 15 · 거래량 10 · 섹터 5.
  등급: **Prime ≥85 · High ≥75 · Watch ≥65 · Low <65**.
- **알림**(`alert_type`): `ready`(피봇 근접+조건 충족) · `breakout`(피봇 돌파+대량거래) ·
  `extended`(피봇/50일선 대비 과열) · `none`.
- **필터/정렬/저장**: 상단에서 최소점수·등급·pivot·알림·섹터·검색으로 거르고, 헤더
  클릭으로 정렬, **CSV ↓** 버튼으로 현재 결과를 내려받습니다.

**설정 (`config.yaml`)** — 모든 임계값을 여기서 조정합니다. 파일이 없으면
`app/base/config.py`의 기본값으로 동작하고, 일부만 적어도 그 값만 덮어씁니다.
예: 베이스 최대 깊이(`base.max_depth`), RS 백분위 컷(`trend_template.min_rs_percentile`),
거래량 dry-up 기준(`volume.dry_up_10d_vs_50d`), 점수 배점(`scoring.*`), 알림 기준(`alerts.*`).

**섹터 매핑 (`data/sector_mapping.csv`)** — 선택 파일. `ticker,sector_etf` 형식으로 종목별
세부 섹터 ETF(예: `NVDA,SMH`)를 지정하면 그 ETF 대비 상대강도로 섹터 점수를 매깁니다.
없으면 Finviz 섹터 기준 기본 ETF(XLK·XLV 등)를 쓰고, 매핑이 없는 종목도 제외하지 않고
섹터 점수를 중립(0.5)으로 둡니다.

**실행**

```bash
# 라이브(백엔드가 스캔): 대시보드 실행 후 /base/ 로 접속
python3 -m uvicorn app.main:app --port 8000     # → http://127.0.0.1:8000/base/
# API 직접 호출
curl http://127.0.0.1:8000/api/base

# 네트워크 없이 UI/로직 미리보기(합성 데이터)
SUH_DH_DEMO=1 python3 -m uvicorn app.main:app --port 8000
```

정적 사이트(GitHub Pages)에서는 `build.py`가 스캔 결과를 `data/base.json`으로 미리
생성합니다. 스캔은 무겁기 때문에 후보 수를 `SUH_DH_BASE_LIMIT`(빌드 시), 차트 프리빌드
수를 `SUH_DH_BASE_CHART_LIMIT`로 제한할 수 있고, 실패해도 나머지 빌드를 막지 않습니다.

**주요 출력 컬럼**: `ticker, company_name, sector, sector_etf, current_price, market_cap,
avg_dollar_volume_20d, total_score, setup_grade, trend_template_pass, rs_percentile,
rs_vs_spy_3m, rs_vs_qqq_3m, base_start_date, base_length_days, base_depth, pivot_price,
distance_to_pivot, pivot_status, atr_contraction_ratio, volume_dry_up_ratio,
high_volume_down_days_20d, sector_action_score, alert_type, notes` + 세부 점수(`trend_score,
rs_score, base_score, vcp_score, volume_score, sector_score`).

**한계점 (반드시 유의)**

- 가격/거래량 기반 스크리너는 **투자 추천이 아니며**, 정성적 차트 판독을 대체하지 않습니다.
- 무료 데이터 소스(Yahoo/Stooq/Finviz)는 **지연·누락·오류**가 있을 수 있습니다.
- 베이스/VCP 탐지는 **완벽한 차트 판독이 아니라 정량화된 근사치**입니다(구간 경계·피봇은
  휴리스틱). 최종 매수/매도는 반드시 실제 차트와 실적 이벤트를 추가로 확인하세요.
- RS 백분위는 **스캔한 유니버스 기준** 상대값이라, 유니버스 구성(Finviz 필터)에 따라 값이
  달라집니다.
- 펀더멘털(매출/EPS 성장 등)은 초기 버전에서 미반영입니다(구조상 추후 추가 가능).

### AI 투자 뉴스 프로그램

주요 외신 RSS를 모아 **AI·데이터센터 생태계와 직접 관련된 뉴스만** 선별해 한국어로
간결하게 전달합니다(긴 분석이 아니라 "적절한 선별 + 간결한 전달"이 목표).

- **AI 전용 스코프(게이트)**: 아래 AI 카테고리 중 하나 이상에 해당해야 노출됩니다
  (`app/news.py`의 `AI_QUALIFYING`). 연준 금리·환율·유가·일반 실적 같은 **순수 거시
  뉴스는 제외**되고, 거시 이슈라도 AI/반도체와 엮인 경우(예: AI 칩 수출규제)에만 포함됩니다.
  - **AI / 반도체**: AI 모델·LLM·오픈AI 등, 반도체·GPU·파운드리(NVDA·TSMC·AMD·ASML 등)
  - **AI인프라 공급망**: HBM/DRAM·DDR5·NAND, CoWoS·어드밴스드 패키징, 액침/수랭 냉각, AI 서버·랙
  - **데이터센터**: 글로벌 데이터센터·하이퍼스케일러·콜로케이션
  - **데이터센터 투자/지연**: capex·자금조달·착공/전력연결 지연·공급과잉
  - **전력·인프라**: 전력망·변압기·배전반·800VDC/HVDC·전력 부족
  - **에너지**: 태양광·풍력·ESS·SMR·원전·지열·SOFC/연료전지·가스터빈
  - **광통신**: CPO(공동패키지 광학)·실리콘 포토닉스·광 트랜시버·800G/1.6T·InfiniBand/NVLink
  - **소버린 AI · 엣지 AI · 피지컬 AI**: 국가 AI·온디바이스/AI PC·휴머노이드/로보틱스/자동화
- **무료 매체 우선**: 매체별로 유료(paywall) 여부를 표시하고, 피드 우선순위·중복 제거·
  일일 컷에서 **무료로 읽을 수 있는 매체**(Reuters·CNBC·Yahoo Finance·
  DataCenterDynamics·The Register 등)를 우대합니다. 유료 매체(Bloomberg·FT·WSJ·Nikkei)는
  커버리지를 위해 남기되 후순위로 두고 화면에 `🔒 유료` 배지를 붙입니다.
- **중복 제거**: 같은 이슈가 여러 매체에 있으면 제목 유사도로 묶어 **무료 + 신뢰도 높은
  매체 1건**만 남깁니다.
- **출력**: 하루 10~20건, 각 뉴스 한국어 1~2줄 요약 + **원문 링크** + 출처 + 보도 시각.
- 동작 파라미터는 환경변수로 조정: `SUH_DH_NEWS_MAX`(기본 18), `SUH_DH_NEWS_MAX_AGE`
  (시간, 기본 36), `SUH_DH_NEWS_MIN_SCORE`(기본 2), `SUH_DH_NEWS_FREE_BONUS`(기본 1),
  `SUH_DH_NEWS_TTL`(초, 기본 1800).

### 실적 발표 전후 주가 반응 프로그램

`/earnings/` — 티커를 입력하면 **실적 발표일 기준 주가 반응**을 표로 보여줍니다.

- **주가 반응(자동)**: 발표일 종가 대비 **직전1일·D+1·D+7·D+30·D+60 거래일 수익률**을
  무료 일별 종가(Yahoo)로 계산하고, 하단에 **D+N 평균 + 상승 횟수**를 집계합니다.
  상승은 빨강, 하락은 파랑으로 진하기까지 입혀 한눈에 보입니다(이미지의 히트맵과 동일).
- **EPS vs 컨센(자동)**: 실제 EPS가 컨센서스를 **상회/하회/부합**했는지 — yfinance의
  추정치·실제치로 서프라이즈 %를 계산해 배지로 표시.
- **가이던스 vs 컨센(큐레이션)**: 회사가 발표 때 제시한 **차분기 가이던스**가 그 시점
  컨센서스를 상회했는지(대폭상회~대폭하회 7단계). 이 두 숫자는 무료 가격/실적 API에
  없어, `data/guidance.json` 큐레이션 레이어에서 출처 링크와 함께 채웁니다.

> **`tools/guidance.py`** — 가이던스 큐레이션 도우미(네트워크가 열린 로컬/Actions에서 실행).
> - `add` : 보도자료·실적 기사에서 확인한 숫자를 기록(가이던스·컨센·출처) → 상회/하회 등급 자동 계산 후 `data/guidance.json`에 저장.
> - `consensus` : 차분기 컨센서스(매출·EPS)를 yfinance forward 추정치로 **스냅샷**(발표 직전에 돌리면 발표 당시 컨센서스를 자동 포착). `--apply`로 기존 항목에 기록.
> ```bash
> python3 tools/guidance.py add MU --report-date 2025-12-17 --period "FY26 Q2" \
>     --metric revenue --guidance 8.8 --consensus 8.5 --source https://investors.micron.com/...
> python3 tools/guidance.py consensus MU --apply 2025-12-17 --metric revenue
> ```
> 정적 사이트에서는 `data/guidance.json`에 있는 티커와 기본 워치리스트
> (`SUH_DH_DRIFT_TICKERS`, 기본 `MU`)만 미리 빌드되며, 로컬 실행 시에는 아무 티커나 조회됩니다.

### 텔레그램 채널로 자동 전송

**대시보드에 올라온 것과 똑같은** AI 뉴스를 텔레그램 채널로 보냅니다
(`.github/workflows/telegram.yml`). 텔레그램은 뉴스를 따로 긁지 않고 **대시보드 빌드가
저장소에 커밋해 둔 `data/news.json`(`TELEGRAM_NEWS_URL`)을 그대로 읽어** 전송하므로 둘이
항상 일치합니다(공개/비공개 저장소 모두 동작). 30분마다 확인해 **새 기사만** 보내고
(대시보드는 6시간마다 갱신 → 그때 `data/news.json` 이 바뀌며 새 묶음이 전송), 서버가
필요 없는 무료 방식이며, 이미 보낸 기사는 `state/telegram_sent.json` 으로 기억해 중복
전송하지 않습니다.

**최초 1회 설정 (약 5분):**

1. 텔레그램에서 **@BotFather** 와 대화 → `/newbot` 으로 봇을 만들고 **봇 토큰**을 받습니다
   (예: `123456:ABC-DEF...`). 토큰은 비밀이니 어디에도 붙여넣지 마세요.
2. 뉴스를 받을 **채널을 생성**하고, 방금 만든 봇을 그 채널의 **관리자(Administrator)** 로
   추가합니다(메시지 게시 권한 필요).
3. **채널 ID** 확인:
   - 공개 채널이면 `@채널이름` 을 그대로 쓰면 됩니다.
   - 비공개 채널이면 채널에 글을 하나 올린 뒤
     `https://api.telegram.org/bot<토큰>/getUpdates` 를 열어 `"chat":{"id":-100...}` 의
     숫자(`-100`으로 시작)를 사용합니다.
4. 깃허브 저장소 **Settings → Secrets and variables → Actions → New repository secret** 에서
   두 개를 등록:
   - `TELEGRAM_BOT_TOKEN` = 1번의 봇 토큰
   - `TELEGRAM_CHAT_ID` = 3번의 채널 ID(`@채널이름` 또는 `-100...`)
5. **Actions → "Telegram AI news" → Run workflow** 로 한 번 수동 실행해 동작을 확인합니다.

이후로는 **30분마다 자동**으로 새 뉴스가 채널에 올라옵니다.

> **참고**
> - 비밀 값(봇 토큰/채널 ID)은 **GitHub Secrets 에만** 두고 코드/커밋에 넣지 마세요.
> - **첫 실행은 "시딩"** 입니다 — 그 시점의 기존 뉴스를 한꺼번에 쏟아내지 않으려고
>   "이미 본 것"으로만 표시하고 전송은 안 합니다. 그다음 실행부터 진짜 새 기사가 전송됩니다.
>   처음부터 현재 목록을 보내고 싶으면 Secret `TELEGRAM_SEND_FIRST_RUN=1` 을 추가하세요.
> - 한 번에 보낼 최대 건수는 `TELEGRAM_MAX_PER_RUN`(기본 10), 전송 주기는 워크플로의
>   `cron`(기본 `*/30 * * * *`)으로 조정합니다.
> - 자격증명 없이 로컬에서 미리 보려면: `SUH_DH_DEMO=1 python3 notify_telegram.py --dry-run`
>   (실제 전송 없이 메시지만 출력).

새 프로그램을 추가하려면: `static/<프로그램>/` 폴더를 만들고,
`static/index.html` 의 `APPS` 배열에 카드 한 줄(`name/emoji/desc/href`)만 추가하면
허브에 자동으로 나타납니다.

API 예시:

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/highs` | 섹터→소섹터로 그룹된 신고가 종목(시총순) |
| `GET /api/reason/{ticker}` | 최신 뉴스 + 최근 실적발표 여부 |
| `GET /api/earnings/{ticker}` | 분기별 실적 발표일 + EPS 컨센서스 상회/하회/부합 판정 + (있으면) 차분기 가이던스 vs 당시 컨센서스 |
| `GET /api/drift/{ticker}` | 위 실적 표 + 발표일 기준 직전1일·D+1·D+7·D+30·D+60 주가 수익률 + 분기 평균/상승횟수 |
| `GET /api/chart/{ticker}?range=max\|6mo` | OHLCV + 거래량 + MA5/20/50/120 |
| `GET /api/news` | 선별된 AI 투자 뉴스 10~20건(한국어 요약 + 원문 링크) |

## 네트워크 접근 안내 (중요)

이 대시보드는 `finviz.com`, `query1/query2.finance.yahoo.com`,
그리고 글로벌 뉴스 RSS 호스트(`www.reutersagency.com`, `www.cnbc.com`,
`finance.yahoo.com`, `www.datacenterdynamics.com`, `www.theregister.com`,
`asia.nikkei.com`, `feeds.bloomberg.com`, `feeds.a.dj.com`, `www.ft.com`), 그리고
텔레그램 전송 시 `api.telegram.org` 로
아웃바운드 요청을 보냅니다. 로컬 PC에서는 보통 문제없이 동작하지만,
**Claude Code on the web 같은 egress allowlist가 적용된 샌드박스에서는 차단**됩니다.
그런 환경에서 라이브로 쓰려면 해당 호스트를 네트워크 허용 목록에 추가하거나,
미리보기는 `--demo` 모드를 사용하세요.

## 테스트

```bash
python3 -m pytest tests/ -q
```

## 향후 개선 아이디어

- 상승 이유의 정확도 향상(실적 서프라이즈 % 표시, 뉴스 요약).
- 관심 섹터/시총 필터, 신고가 외 추가 시그널.
- 유료 실시간 데이터 소스 연동 옵션.
