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
  qtable.py      분기 실적표(과거 가이던스/컨센서스/실적/향후 가이던스) — 회계분기 계산 + 큐레이션 병합
  news.py        주요 외신 RSS 수집 → AI/데이터센터 뉴스 선별/중복제거 → 한국어 요약
  backlog.py     한국 수주잔고 대시보드(data/kr_backlog.json 로드 + 전분기/전년 증감 계산)
  dartdoc.py     OpenDART 문서 클라이언트 + 수주잔고 표 파서(순수 함수, 오프라인 테스트)
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
    qtable/      분기 실적표 프로그램(HTML/CSS/JS)
tools/
  guidance.py            가이던스 vs 컨센서스 큐레이션 도우미(add/consensus)
  qtable.py              분기 실적표 CLI(표 출력·TSV/CSV/JSON 내보내기 + 큐레이션 add)
  kr_dart_backlog.py     DART에서 한국 수주잔고 수집 → data/kr_backlog.json (백필/증분)
data/
  guidance.json          가이던스 vs 컨센서스 큐레이션 데이터(스키마 내장)
  guidance_table.json    분기 실적표 큐레이션 데이터(가이던스·과거 컨센서스, 스키마 내장)
  kr_backlog.json        회사별 분기 수주잔고(DART, kr-backlog 워크플로가 갱신)
```

### 화면 구조 (허브 + 프로그램)

- `/` — **대시보드 허브**. 프로그램들을 카드로 보여주고 눌러서 들어갑니다.
- `/highs/` — 52주 신고가 프로그램.
- `/news/` — AI 투자 뉴스 프로그램.
- `/base/` — **베이스 스크리너** 프로그램 (아래 참고).
- `/flat/` — **평평 스크리너** 프로그램 (아래 참고).
- `/qtable/` — **분기 실적표** 프로그램 (아래 참고).

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

### 평평 스크리너 프로그램 (`/flat/`)

미국 상장 보통주 중 **"지금 평평한 베이스(수평·좁은 밀집)를 형성 중인 종목"** 만 자동으로
찾아 주는 스크리너입니다. **베이스 스크리너와는 완전히 별개 프로그램**이며(코드도
`app/flat/` 로 분리), 목적과 채점 방식이 다릅니다.

> **목적**: 주가 돌파를 예측하거나 매수 종목을 추천하는 것이 **아닙니다.** 일정 기간
> 주가가 수평적이고 좁은 범위에 밀집된 종목을 찾아 **후보군을 제공**하는 것이 목적이며,
> 이후 거래량·변동성·실적·펀더멘털은 사용자가 직접 검토합니다.

**핵심 원칙 (스펙 그대로)**

- 상승 후 베이스(**Continuation**)뿐 아니라 하락 후 바닥 다지기(**Turnaround**)도 포함합니다.
- 이전 상승 추세는 **하드 필터가 아니라 태그**로만 씁니다.
- **평평도(Flatness)와 과거 활동성(Historical Activity)은 반드시 별도로 계산**합니다.
  과거 활동성·이전 수익률은 **Flatness Score에 절대 넣지 않습니다.**
- REIT·장기간 죽어있는 종목이 "평평하다"는 이유만으로 상위에 오르지 않도록 별도의
  **Historical Activity Filter** 와 **Chronically Low Volatility 제외**를 적용합니다.
- **이 버전에서 계산/채점하지 않는 것**: 거래량 감소·거래량 고갈·ATR·과거대비 변동성
  축소·VCP·볼린저밴드·이동평균 정배열·Minervini·RS(상대강도)·SPY 상대수익률·섹터
  동조화·실적/EPS·펀더멘털·돌파확률/목표가. (섹터와 RS 백분위는 **표시 전용 열**로만
  넣고 점수엔 미포함.)

**동작 방식**

- **1차 유니버스** (`app/flat/universe.py`): NYSE·NASDAQ 보통주. **품질 필터는 저가주 컷이
  아니라 시총**으로 겁니다 — Finviz로 **시총 ≥ $300M(소형주 이상)**, 주가 ≥ $1(서브-$1 페니주
  데이터 노이즈 방지용 최소값), 거래량, 펀드 제외를 1차로 거른 뒤, **REIT**(industry가
  `REIT - …` 이거나 종목명에 REIT)·ETF/ETN·우선주·SPAC·워런트·유닛을 제외합니다. Real Estate
  **섹터 전체가 아니라 REIT만** 제외합니다. 이동평균 필터는 쓰지 않습니다(평평한 베이스는
  어디든 생기므로). 20일 평균 거래대금 $10M 미만은 정밀분석 후 제외(시총이 작아도 유동성은
  보장).
- **복수 기간 탐색** (`app/flat/bases.py`): 현재 거래일을 끝으로 **20·30·40·50·60·80·100·120**
  거래일을 각각 독립 베이스 후보로 계산하고, 기간별 기준을 통과한 것 중 **Flatness Score가
  가장 높은 기간**을 최적 베이스로 선택합니다(짧다고 유리하지 않도록 기간별 허용치를 다르게).
- **평평도 지표** (`app/flat/metrics.py`): Close Band = `(Q90−Q10)/median`, Base Drift =
  `exp(회귀기울기×(일수−1))−1`(로그종가 OLS), Containment(중앙값 ±7.5% 안 비율),
  Center Shift(후반/전반 중앙값 차), Outlier Ratio(|일간수익률|≥8% 비율), Current Position
  (밴드 내 현재가 위치). 하루 꼬리 영향을 줄이려 **고저가 대신 종가 분위수**를 씁니다.
- **과거 활동성** (`app/flat/activity.py`): **베이스 시작 이전 데이터만** 사용(룩어헤드
  방지). 이전 120/252일 Close Band, 과거 252일 내 최대 |20·60일 수익률|, Base Distinctness
  (이전252일밴드/현재밴드). `이전120밴드≥20% OR 최대이동≥15% OR distinctness≥1.5` 중
  하나면 통과. 넷 다 낮으면 **만성 저변동성**으로 기본 제외(체크박스로 포함 가능).
- **이전 추세 태그** (`app/flat/trend_tag.py`): 베이스 직전 60·120일 수익률 중 절대값 큰 값이
  ≥+20% → Continuation, ≤−20% → Turnaround, 그 사이 → Neutral. Neutral/Turnaround는 하락 중간
  휴식이 섞이지 않도록 §8의 더 엄격한 기준(40일·80점·밀집85%·드리프트5%·중심5%·활동성통과)을
  요구합니다.
- **Flatness Score** (`app/flat/scoring.py`, 100점): Close Band 35 · Base Drift 25 ·
  Containment 20 · Center Shift 10 · Outlier 10. 각 항목은 **그 기간의 허용치 대비** 0~1로
  클립. 등급: **Very Flat ≥85 · Flat ≥75 · Moderately Flat ≥65 · Not Flat <65.**

**필터/정렬/저장**: 상단에서 최소 Flatness·유형·상태·과거활동성·기간·Close Band·밀집도·
섹터·저변동성/REIT/미달 포함 여부·검색으로 거르고, 헤더 클릭 정렬, **CSV ↓ / Excel ↓**
(둘 다 순수 클라이언트 생성, 서버 의존성 없음), **★ 관심종목**(브라우저 localStorage)으로
저장합니다. 종목을 누르면 베이스 구간 음영 + Q10/Q90 + 중앙값 + 회귀 추세선 + 전·후반
중앙값을 얹은 가격 차트가 열립니다(거래량·이동평균은 오버레이하지 않음).

**설정 (`flat_config.yaml`)** — 모든 임계값을 여기서 조정합니다. 파일이 없으면
`app/flat/config.py`의 기본값으로 동작하고, 일부만 적어도 그 값만 덮어씁니다.
사용자 변경 항목: `universe.include_reit`(REIT 포함), `universe.include_adr`, `min_price`,
`min_market_cap`, `min_avg_dollar_volume_20d`, 기간별 `thresholds.*`, `historical_activity.*`,
`chronic_low_vol.*`, 점수 배점 `score.*`.

**합리적 기본값(스펙에 명시 안 된 부분)** — 코드에 고정하지 않고 설정으로 노출했습니다.

- **회귀**: scipy Theil-Sen 대신 **순수 numpy OLS**로 로그종가 기울기를 구합니다(의존성 0;
  이상치는 Outlier Ratio가 별도로 통제). 필요하면 scipy로 교체 가능.
- **Excel 다운로드**: openpyxl 없이 **브라우저에서 HTML 테이블(.xls)** 로 생성(서버 의존성 0).
- **REIT 판정**: 무료 데이터 한계상 Finviz industry(`REIT - …`)·종목명 휴리스틱.
- **유니버스 상한**: `universe.max_candidates`(기본 1500) + 시총 구간 균등표본(대형 편중 방지).
- **관심종목**: 서버 상태 없이 브라우저 localStorage.
- **데이터 부족**: 임의 값으로 채우지 않고 스캔 요약에 "데이터부족"으로 별도 집계합니다.

**실행**

```bash
# 라이브(백엔드가 스캔): 대시보드 실행 후 /flat/ 로 접속
python3 -m uvicorn app.main:app --port 8000     # → http://127.0.0.1:8000/flat/
curl http://127.0.0.1:8000/api/flat             # API 직접 호출

# 네트워크 없이 UI/로직 미리보기(합성 데이터)
SUH_DH_DEMO=1 python3 -m uvicorn app.main:app --port 8000

# 핵심 계산 로직 오프라인 테스트
python -m pytest tests/test_flat.py -q
```

정적 사이트(GitHub Pages)에서는 `build.py`가 결과를 `data/flat.json`으로 미리 만들고
개별 차트를 `data/chart/`(베이스 스크리너와 공유)로 프리빌드합니다. 스캔이 무거워서
베이스 스크리너와 같은 캐던스로 예약/수동 빌드에서만 전체 스캔하고, 일반 push·잦은
intraday 빌드(`SUH_DH_SKIP_BASE=1`)에서는 커밋된 스냅샷을 재사용합니다. 후보 수는
`SUH_DH_FLAT_LIMIT`, 차트 프리빌드 수는 `SUH_DH_FLAT_CHART_LIMIT`, 강제 재스캔은
`SUH_DH_FORCE_FLAT=1`로 조절합니다.

**주요 출력 컬럼**: `ticker, company_name, security_type, sector, industry, current_price,
market_cap, avg_dollar_volume_20d, base_start_date, base_end_date, base_days, close_band,
raw_high_low_range, base_drift, containment_ratio, center_shift, outlier_days, outlier_ratio,
current_position, flatness_score, flatness_grade, prior_60d_return, prior_120d_return,
representative_prior_return, prior_120_close_band, prior_252_close_band, max_abs_20d_return,
max_abs_60d_return, base_distinctness, historical_activity_pass, chronically_low_vol,
base_category, base_status, is_reit, rs_percentile, beta, exclude_reason`.
(`rs_percentile`·`beta`·섹터는 **표시 전용**이며 Flatness Score에는 포함하지 않습니다.)

**한계점 (반드시 유의)**

- 가격 기반 스크리너는 **투자 추천이 아니며**, 정성적 차트 판독을 대체하지 않습니다.
- Flatness Score는 **"지금 평평한 정도"만** 재며, 앞으로 돌파할지/살 만한지와 무관합니다.
- 무료 데이터(Yahoo/Stooq/Finviz)는 지연·누락·오류가 있을 수 있고, REIT/증권유형 판정은
  무료 데이터 한계상 휴리스틱입니다.
- 가격은 **조정 종가(auto_adjust)** 를 씁니다. 배당·액면분할이 일관 반영되어 배당 락이
  베이스 드리프트로 오인되지 않도록 했습니다.

### 한국 수주잔고 프로그램 (`/backlog/`)

분기별로 **수주잔고(order backlog)를 공시하는 회사**(건설·조선·방산·기계·플랜트·SI 등)의
**최근 1개년 분기별 수주잔고 추이**를 정리합니다. 소스는 **DART 전자공시**입니다.

- **데이터 출처**: 수주잔고는 DART의 정형 API(재무제표)에 없고, **정기보고서(분기·반기·
  사업보고서) 본문 "사업의 내용 → 수주상황" 표** 안에 있습니다. 그래서 `list.json`으로
  정기보고서를 찾고 `document.xml`로 보고서 원본을 받아 **수주잔고/수주잔액 열**을 파싱합니다.
  회사마다 표 양식이 달라 **근사치**이며, 각 행에 **DART 원문 링크**를 함께 실어 검증할 수 있게 했습니다.
- **화면**: 회사·섹터·최신 분기·수주잔고(₩ 조/억)·**전분기比·전년비** 증감. 회사 행을 누르면
  **분기별 수주잔고 추이**(막대)가 펼쳐지고, 각 분기의 DART 원문으로 이동할 수 있습니다.
  외화(USD 등) 표기 회사는 원문 단위 그대로 표시합니다(원화 환산하지 않음).

**부하 걱정 없이 유지되는 이유 — 매일 전 종목을 스캔하지 않습니다.**
수주잔고는 **회사가 정기보고서를 제출할 때만** 바뀝니다(1년에 4번). 그래서:

- **매일 갱신(증분)**: `list.json` 을 `pblntf_ty=A`(정기공시) + 최근 날짜로 **딱 한 번 시장
  전체 조회** → 그날 정기보고서를 낸 회사만 몇 개~수십 개가 나오고, **그 회사들만** 문서를
  파싱합니다. 대부분의 날은 몇 건, 마감 시즌(5·8·11월 중순, 3월 말)에만 잠깐 수백 건 몰릴 뿐,
  **상장사 ~2,600개를 매일 확인하지 않습니다.**
- **최초 백필(1회)**: 전 종목의 최근 ~15개월 정기보고서를 훑어 **수주잔고를 실제로 공시하는
  회사만** 추려 과거 이력을 채웁니다. 무겁지만 **한 번만** 돌리면 됩니다(재실행 가능·체크포인트 저장).

**설정 (최초 1회):**

1. <https://opendart.fss.or.kr> 에서 무료 **인증키**를 발급받습니다.
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret** 에
   `DART_API_KEY` 를 등록합니다(실적일 프로그램과 공유).
3. **Actions → "Refresh KR order backlog (DART)" → Run workflow** 에서 **mode=backfill** 로
   한 번 실행해 과거 이력을 채웁니다(전체는 30~60분; `limit`으로 일부만 테스트 가능).
4. 이후로는 **매일 자동(증분)** 으로 그날 제출된 정기보고서만 반영됩니다
   (`.github/workflows/kr-backlog.yml` 의 `cron`, 기본 `0 14 * * *` = 23:00 KST).

**실행 (로컬/CI, DART 접근 가능한 환경):**

```bash
DART_API_KEY=xxx python tools/kr_dart_backlog.py --backfill        # 최초 전체 백필
DART_API_KEY=xxx python tools/kr_dart_backlog.py --backfill --limit 300  # 일부만 테스트
DART_API_KEY=xxx python tools/kr_dart_backlog.py --days 2          # 증분(최근 2일)
# 화면 미리보기(네트워크 불필요, 합성 데이터)
SUH_DH_DEMO=1 python3 -m uvicorn app.main:app --port 8000          # → /backlog/
```

> ⚠️ `opendart.fss.or.kr` 는 egress allowlist 샌드박스(Claude Code on the web 등)에서 **차단**됩니다.
> 실제 수집은 GitHub Actions처럼 해당 호스트에 접근 가능한 곳에서 돌아갑니다. 파싱 로직은
> `tests/test_backlog.py` 로 오프라인 단위테스트합니다.

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

### 분기 실적표 프로그램 (`/qtable/`)

`/qtable/` — **티커 하나를 입력하면** 최근 발표 분기를 기준으로 **이전 6개 분기 +
향후 4개 분기**(총 10열) 표를 자동으로 만들어 줍니다. 행은

| 행 블록 | 뜻 | 출처 |
| --- | --- | --- |
| 과거 가이던스 | 그 분기를 앞두고 회사가 제시했던 가이던스 | 큐레이션 |
| 컨센서스 | 발표 직전 애널리스트 컨센서스 | EPS·향후 2개 분기 매출은 Yahoo 자동, 나머지는 큐레이션 |
| 실적 | 실제 발표치 | Yahoo 자동(GAAP) — 큐레이션이 있으면 그 값(non-GAAP) 우선 |
| 향후 가이던스(연간) | 그 분기 발표 때 제시한 **연간(FY)** 가이던스 | 큐레이션 |
| 향후 가이던스(QoQ) | 그 분기 발표 때 제시한 **차분기** 가이던스 | 큐레이션 |

이고, 각 블록마다 **매출 · 영업이익 · EBITDA · EPS** 네 줄입니다.

- **열 이름은 회사의 회계연도 기준**입니다. 예를 들어 3월 결산인 디지털터빈(APPS)은
  2026년 3월 마감 분기가 `2026 4Q`, 2026년 6월 마감 분기가 `2027 1Q` 입니다. 결산월은
  Yahoo 정보에서 자동 추정하고, 큐레이션의 `meta.fy_end_month` 로 고정할 수 있습니다.
- **자동으로 채워지는 것**: 분기 손익계산서(매출·영업이익·EBITDA·EPS. EBITDA 행이
  없으면 영업이익+감가상각으로 역산), `get_earnings_dates()` 의 **EPS 컨센서스**,
  그리고 **향후 2개 분기**의 매출/EPS 컨센서스(`0q`/`+1q` 추정치).
- **무료 API에 없어 큐레이션이 필요한 것**: 회사 가이던스 전부(과거·향후·연간·QoQ)와
  과거 분기의 **매출 컨센서스**. `data/guidance_table.json` 에 출처와 함께 적습니다.
  같은 칸에 자동값과 큐레이션이 겹치면 **큐레이션이 이깁니다**(회사 발표 non-GAAP 기준).
- **실적 색**: 컨센서스 대비 상회는 빨강, 하회는 파랑. 셀에 마우스를 올리면 밴드·출처·메모가 뜹니다.
- **엑셀로 가져가기**: 상단 **📋 복사**(탭 구분 — 엑셀에 Ctrl+V 하면 표 그대로) 또는
  **⬇ CSV**.

**실행**

```bash
# 웹으로 (라이브 백엔드)
python3 -m uvicorn app.main:app --port 8000   # → http://127.0.0.1:8000/qtable/#APPS

# 터미널에서 바로
python3 tools/qtable.py APPS                  # 표 출력
python3 tools/qtable.py APPS --tsv            # 엑셀 붙여넣기용(탭 구분)
python3 tools/qtable.py APPS --csv apps.csv   # 파일로 저장
python3 tools/qtable.py APPS --past 8 --ahead 2   # 열 개수 조정

# API
curl 'http://127.0.0.1:8000/api/qtable/APPS' | python3 -m json.tool
```

**가이던스 입력(`tools/qtable.py add`)** — 발표 자료/보도자료의 숫자를 한 줄씩 넣습니다.
분기 가이던스는 `--for`(대상 분기)와 `--given-at`(제시한 분기)을 함께 주면 **과거
가이던스**와 **향후 가이던스(QoQ)** 두 칸이 한 번에 채워집니다.

```bash
# FY26 3Q 발표 때 제시한 4분기 매출 가이던스 130.3~135.3
python3 tools/qtable.py add APPS --kind quarter_guidance --metric revenue \
    --for FY2026Q4 --given-at FY2026Q3 --low 130.3 --high 135.3 \
    --source https://ir.digitalturbine.com/... --note "3Q 발표 자료"

# FY26 4Q 발표 때 제시한 FY27 연간 EBITDA 가이던스
python3 tools/qtable.py add APPS --kind annual_guidance --metric ebitda \
    --for FY2027 --given-at FY2026Q4 --low 135 --high 145

# 숫자 대신 문구만("미제공" / "연간 제공")
python3 tools/qtable.py add APPS --kind quarter_guidance --metric eps \
    --given-at FY2027Q1 --text 미제공 --sections fwd_qoq

python3 tools/qtable.py list        # 큐레이션된 종목 보기
```

> 네트워크가 막힌 환경(웹 샌드박스 등)에서는 `SUH_DH_DEMO=1` 을 앞에 붙이면 Yahoo 호출
> 없이 큐레이션 값만으로 표를 그립니다. 정적 사이트(GitHub Pages)에는 큐레이션된 종목 +
> `SUH_DH_QTABLE_TICKERS` 기본 목록이 미리 빌드되고, 그 외 티커는 `SUH_DH_API_BASE`
> 백엔드가 연결돼 있으면 라이브로 조회됩니다.

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
| `GET /api/backlog` | 한국 수주잔고 공시 회사의 분기별 수주잔고(전분기/전년 증감 + DART 원문 링크) |
| `GET /api/backlog/{stock_code}` | 한 종목의 수주잔고를 DART에서 라이브 재수집(DART_API_KEY 필요) |

## 네트워크 접근 안내 (중요)

이 대시보드는 `finviz.com`, `query1/query2.finance.yahoo.com`,
그리고 글로벌 뉴스 RSS 호스트(`www.reutersagency.com`, `www.cnbc.com`,
`finance.yahoo.com`, `www.datacenterdynamics.com`, `www.theregister.com`,
`asia.nikkei.com`, `feeds.bloomberg.com`, `feeds.a.dj.com`, `www.ft.com`),
한국 실적일·수주잔고 수집 시 `opendart.fss.or.kr`, 그리고
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
