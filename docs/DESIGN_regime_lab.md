# Market Regime Lab — 구조 및 계산 방법론

Nasdaq Composite(^IXIC) 약 20년 일봉으로 **현재 시장 상태를 정량화**하고,
**과거의 유사한 국면**을 찾아 그 **이후 5/20/60/120거래일 수익률 분포**를 보는
인터랙티브 웹앱(Python + pandas + Streamlit + Plotly)의 설계 문서입니다.

우선 ^IXIC 하나로 동작하지만, 티커는 사이드바 입력값일 뿐이며 데이터 수집 /
feature engineering / similarity / visualization 이 분리돼 있어 임의 종목·지표로
확장할 수 있습니다.

---

## 1. 모듈 구조

```
app/regime/
  config.py            파라미터 dataclass + regime_config.yaml 로딩
  data/
    sources.py         yfinance / stooq / 오프라인 합성 — 세 provider, 한 시그니처
    upload.py          Manual Upload (CSV/XLSX) 파싱 · 컬럼 매핑 · 단위 추정
    align.py           거래일 달력 정렬 (forward-fill only)
    loader.py          MarketData 조립 + 디스크 캐시 + DataOverrides(업로드 우선)
  features/
    base.py            FeatureSpec / FeatureSet / builder 레지스트리
    trend.py           SMA 이격률, 배열, 기울기
    momentum.py        5/20/60/120일 수익률, 52주 고점 대비 낙폭
    volatility.py      realized volatility, ATR%
    distribution.py    분산일 판정 · 개수 · 경과일
    macro.py           외생 시계열(현재 10년물) 수준/변화/백분위 — 자동 생성
  quality.py           데이터 품질 검사 (CLI 겸용)
  similarity.py        as-of 정규화 · 가중 거리 · de-clustering
  matching.py          strict 조건 매칭
  forward.py           forward return 통계 · cluster bootstrap · 유효표본수 · baseline 비교
  audit.py             한 날짜의 계산 과정을 전부 펼쳐 보여 주는 감사 뷰
  validation.py        walk-forward / out-of-sample
  viz.py               Plotly figure (Streamlit 비의존)
  ui.py                사이드바 위젯 → 파라미터 dataclass
  streamlit_app.py     화면 조립 (얇게)
regime_config.yaml     모든 기본값
tests/test_regime.py         오프라인 단위 테스트 (look-ahead 검증 포함)
tests/test_regime_audit.py   감사 화면 값의 독립 재계산 + 품질/독립성 테스트
```

데이터 흐름은 한 방향입니다:

```
load_market ──> build_features ──> similarity / strict match ──> forward analysis
     │                │                      │                         │
     └── meta(출처·최종 업데이트)  specs(라벨·포맷·기본가중치)   viz / validation
```

---

## 2. 데이터

| 항목 | 내용 |
|---|---|
| 가격 | `^IXIC` 일봉 OHLCV, 기본 20년 (`auto_adjust=True`) |
| 금리 | 미국 10년물 `^TNX` (퍼센트 단위로 정규화) |
| 입력 방식 | **Auto Download** 또는 **Manual Upload** (사이드바에서 선택) |
| 1차 소스 | Yahoo Finance (yfinance) |
| 폴백 | Stooq CSV → 디스크 캐시(만료 무시) → 합성 데이터(데모) |
| 캐시 | `data/regime/<symbol>.csv`, 기본 TTL 6시간 (`SUH_DH_REGIME_TTL`) |
| 표시 | 화면 최상단에 **Price / Volume / 10Y 각각의 입력 방식과 파일명(또는 제공자)** 을 항상 표기 |

### Manual Upload (`app/regime/data/upload.py`)

내려받기가 막혀 있거나, 공급자마다 정의가 다른 거래량을 직접 통제하고 싶을 때
쓰는 경로입니다. 업로드된 파일은 **다운로드 결과와 완전히 같은 스키마**로
정규화되어, 그 아래(feature / similarity / forward / audit / validation)는 어느
쪽에서 왔는지 알 수 없습니다.

| 파일 | 최소 컬럼 | 비고 |
|---|---|---|
| ① 가격 (OHLCV) | `Date, Close` (+ `Open/High/Low/Volume`) | CSV·XLSX. O/H/L 이 없으면 종가로 대체하고 경고(CLV·ATR 무의미) |
| ② 거래량 (선택) | `Date, Volume` | 별도 파일을 **Date 기준 정확 매칭**으로 병합 (forward-fill 하지 않음) |
| ③ 미국 10년물 (선택) | `Date, Yield` | 단위 자동 추정(% / decimal / bp / tenths) + 사용자 override |

* **컬럼 매핑** — 헤더 이름이 달라도 자동 추정한 매핑을 사이드바에서 직접 고칠 수
  있습니다 (`날짜`, `Close/Last`, `Vol.`, `DGS10`, `observation_date` 등 인식).
* **값 파싱** — `$1,234.56`, `2,345,678`, `1.2M`, `(123)`(음수), Excel serial 날짜,
  `DD/MM/YYYY`, cp949 한글 헤더, 탭·세미콜론 구분자.
* **조용히 버리지 않음** — 해석 불가 행·필수값 결측·중복 날짜는 **개수를 화면에 보고**한
  뒤 처리합니다(중복은 마지막 값 유지).
* **Proxy 거래량** — 지수 거래량이 쓸 수 없을 때 QQQ 등으로 대체할 수 있지만,
  **자동 대체는 없습니다.** 사용자가 종목을 지정하고 동의 체크박스를 눌러야만 적용되며,
  적용되면 화면 상단과 품질 탭에
  `Volume Source: QQQ proxy — not Nasdaq Composite volume` 경고가 항상 표시됩니다.
* **Data Source Summary** — Price / Volume / 각 매크로 시리즈별로 입력 방식 ·
  파일명(제공자) · 기간 · 행 수 · 사용 가능 관측치를 한 표로 보여 줍니다. 가격과
  거래량을 따로 올린 경우 **병합 커버리지**(붙은 행 수, 거래량 없는 날, 쓰이지 않은
  거래량 행)도 함께 검사합니다.
* 샘플 파일: `docs/samples/` (가격·거래량·10년물 각 1개, 300거래일).

### Data Quality Check (`app/regime/quality.py`)

화면 상단에 종합 판정 배너, **⑥ 데이터 품질 탭**에 전체 표가 뜨고, 같은 검사를
터미널에서도 돌릴 수 있습니다.

```bash
python3 -m app.regime.quality --ticker '^IXIC'          # 실데이터
python3 -m app.regime.quality --ticker '^IXIC' --demo   # 네트워크 없이 파이프라인만
python3 -m app.regime.quality --ticker '^IXIC' --no-cache
```

| 검사 | 보는 것 |
|---|---|
| 기간 / 거래일 수 | 시작·종료일, 행 수, 연 거래일(미국 ≈252) |
| 중복 날짜 | 같은 날짜가 두 번 들어왔는지 |
| 연속성 | 5영업일 넘는 공백과 그 위치 |
| 결측치 | 컬럼별 NaN 개수 |
| 최신성 | 마지막 봉이 며칠 전인지 (캐시 정체 감지) |
| OHLC 정합성 | high<low, 종가가 범위 밖, 0 이하 |
| **거래량 사용 가능성** | 결측·0 비율, 최근 60봉 상태 → 분산일 판정 가능 여부 |
| **거래량 단위 일관성** | 60일 중앙값이 5배 이상 급변(주↔천주 등 단위 변경) |
| 거래량 배수 분포 | 전일 대비 배수의 중앙값이 1 근처인지 |
| 거래량 정의 | 지수는 composite(구성종목 합산)임을 명시 (ℹ️ 정보) |
| 분산일 검출 빈도 | 현재 임계값으로 연 몇 회 잡히는지 (0회·과다 모두 경고) |
| **금리 단위** | 중앙값으로 percent / tenths / bp / decimal 추정 + 적용된 변환 |
| 금리 값 범위 | 0.2~10% 밖 비율 → "가격 지수를 받아온 것 아닌지" |
| 금리 일간 변동 | 하루 50bp 초과 급변 횟수 |
| 정렬 커버리지 | 거래일 중 값이 있는 비율, forward-fill 비중 |
| 입력 방식 / 소스 | Price·Volume 이 Auto Download / Manual Upload / Proxy 중 무엇인지 |
| 병합 커버리지 | 가격과 거래량을 따로 올렸을 때 날짜가 얼마나 맞물리는지 |

같은 검사가 **업로드 데이터에도 그대로** 적용됩니다 — 로더가 두 경로를 한 스키마로
정규화하기 때문에 품질 검사 쪽에는 분기 자체가 없습니다.

거래량이 분산일 판정에 부적합하면(결측·0 비율이 높으면) **대체 소스를 함께
제안**합니다: ① QQQ/ONEQ 등 추종 ETF 거래량, ② Stooq(^ndq) 등 다른 소스,
③ 지수 대신 ETF 자체를 티커로 분석, ④ 거래량 조건(Y)을 끄고 하락률·CLV 두
조건으로 분산일 정의.

#### 실행 절차 (로컬에서 실데이터로 검증할 때)

```bash
pip install -r requirements-regime.txt

# 1) 데이터 품질만 먼저 (앱을 띄우지 않음, 종료코드 0=ok/warn, 1=fail, 2=수신 실패)
python3 -m app.regime.quality --ticker '^IXIC' --no-cache

# 2) 통과하면 앱 실행 → 상단 배너와 ⑥ 데이터 품질 탭에서 같은 표를 확인
./run_regime.sh
```

출력 형태 (아래는 `--demo` 합성 데이터 예시이며, 실데이터도 같은 표가 나옵니다):

```
     시리즈                항목                       값                                   판정
 ✅ ^IXIC                기간  2006-09-18 ~ 2026-09-16 · 5,032행       20.0년치 · 연 252거래일
 ✅ ^IXIC          연간 거래일 수                 251.7일/년       미국 거래일(약 252일) 범위 안
 ✅ ^IXIC             중복 날짜                        0개                              중복 없음
 ✅ ^IXIC           연속성(공백)                 최대 3영업일                 5영업일 넘는 공백 없음
 ✅ ^IXIC               결측치                        0개                                  없음
 ✅ ^IXIC               최신성                 2026-09-16                   마지막 봉이 0영업일 전
 ✅ ^IXIC          OHLC 정합성                        0건              고가≥저가, 종가가 범위 안
 ✅ ^IXIC     거래량 사용 가능성                 유효 100.0%   결측·0 거래량이 사실상 없음 — 사용 가능
 ✅ ^IXIC     거래량 단위 일관성    중앙값 변화 배수 0.85~1.11              전 구간 단위가 일관됩니다
 ℹ️ ^IXIC            거래량 정의                  composite   지수 거래량은 구성종목 합산(composite)
 ✅ ^IXIC         분산일 검출 빈도                   총 561일        연 28.1회 — 신호로 쓸 만한 빈도
 ✅  ^TNX      10Y yield 단위     중앙값 3.37 · 범위 2.04~4.43   추정 단위 percent · 로더 처리: 변환 없음
 ✅  ^TNX     10Y yield 값 범위                 2.04~4.43%   100.0% 가 0.2~10.0% 안 — yield 로 보임
 ✅  ^TNX    10Y yield 일간 변동                   최대 21bp          하루 50bp 초과 0일 — 정상 범위
 ✅  ^TNX    10Y yield 정렬 커버리지                   100.0%   거래일의 100.0% 에 값 있음(ffill 3.5%)

종합 판정: ✅ OK
```

거래량이나 금리 단위에 문제가 있으면 마지막에 `제안` 열의 내용이 목록으로 함께
출력됩니다 (예: "^IXIC 의 거래량이 분산일 판정에 부적합합니다. 대안: ① QQQ/ONEQ …").

### 거래일 정렬과 결측치 (look-ahead 방지)

* **가격 시계열의 거래일이 기준 달력**입니다. 금리 등 외생 시계열은 이 달력에
  맞춰 재색인합니다.
* 빈 칸은 **forward-fill 로만** 채웁니다. 과거 값을 현재로 끌어오는 것은 그
  시점 관찰자가 실제로 가졌던 정보이기 때문입니다. backward-fill 이나 보간은
  미래 값을 과거로 옮기므로 이 프로젝트 어디에서도 쓰지 않습니다.
* 5거래일을 넘겨 끊긴 구간은 채우지 않고 결측으로 둡니다(없는 데이터를 있는
  것처럼 만들지 않기 위해). 그런 날은 feature 가 미완성이므로 매칭 후보에서도
  자동으로 빠집니다.
* 어떤 외생 시계열을 아예 못 받아 온 경우, 그 컬럼만 무시하고 나머지 분석은
  계속합니다(10년물 장애가 전체를 막지 않도록).

---

## 3. 현재 시장 상태 정의 (feature)

모든 feature 는 **t일 종가 시점까지의 정보만** 사용합니다. 사이드바에서 창
길이·임계값을 바꾸면 즉시 재계산됩니다.

### Trend
| key | 계산 |
|---|---|
| `px_vs_sma{20,50,100,200}` | `Close/SMA_w − 1` (이격률, %) |
| `sma_stack` | 인접 SMA 쌍(20>50, 50>100, 100>200)의 정배열 비율을 `2·p − 1` 로 환산 → **+1 완전 정배열, −1 완전 역배열** |
| `sma{50,200}_slope` | `SMA_w(t)/SMA_w(t−N) − 1` (%, N 기본 20일) |

### Momentum / Position
| key | 계산 |
|---|---|
| `ret_{5,20,60,120}` | `Close_t/Close_{t−k} − 1` (%) |
| `dd_52w` | `Close_t / max(Close_{t−251..t}) − 1` (%) — **t 까지의** 고점만 사용 |

### Volatility
| key | 계산 |
|---|---|
| `vol_realized` | 로그수익률 N일 표준편차 × √252 (연율 %) |
| `atr_pct` | Wilder ATR(N) / Close (%) |

### Distribution Day (분산일)
세 조건을 **모두** 만족한 날:

1. `r_t = Close_t/Close_{t−1} − 1 ≤ −X%`
2. `Volume_t ≥ Volume_{t−1} × (1 + Y%)`
3. `CLV = (Close−Low)/(High−Low) ≤ Z` (당일 범위 안 종가 위치, 1=고가 마감)

* `dd_count` : 최근 lookback 거래일 안의 분산일 개수
* `dd_days_since` : 마지막 분산일 이후 경과 거래일(상한 클리핑 — 거리 계산에서
  이상치가 되지 않도록)
* X / Y / Z / lookback 전부 사용자 조정. 범위가 0인 날(High=Low)은 CLV 0.5로 중립 처리.

### Macro (확장 슬롯)
`regime_config.yaml` 의 `market.exogenous` 에 등록된 시계열마다 **수준 /
N일 변화 / 백분위**가 자동 생성됩니다. 지금은 10년물뿐이고, VIX·credit
spread·Fed Funds 를 추가하면 코드 수정 없이 같은 형태로 붙습니다.

---

## 4. Historical Match

### A. Strict Match
사용자가 고른 feature 에 `<=, <, >=, >, between` 조건을 걸고 **AND** 로 교집합을
구합니다. 결측 feature 가 있는 날은 매칭되지 않습니다.

### B. Similarity Match
1. **정규화** — feature 마다 스케일이 달라 그대로는 더할 수 없습니다. 기본은
   **robust z**: 중앙값과 `1.4826 × MAD`. 중요한 점은 이 통계량을 **기준일까지의
   데이터로만** 추정한다는 것입니다(`normalize_asof`). 실시간 화면에서는 "오늘까지
   아는 전부", 검증 모드에서는 "평가일까지"가 되어 어느 쪽에서도 미래가 새지 않습니다.
2. **거리** — 가중 유클리드 거리, 가중치 합으로 정규화하여 가중치 세트가 달라도
   숫자가 비교 가능하도록 합니다.

   `d = sqrt( Σ wᵢ (zᵢ − zᵢ*)² / Σ wᵢ )`
3. **점수** — 가우시안 커널 `score = 100 · exp(−d²/2)`.
   d=0 → 100, d≈1 → 61, d=2 → 14, d=3 → 1.
4. **후보 제한** — (a) 기준일 이전, (b) 최근 N거래일 제외(기준일과 구간이 겹치는
   어제·그제를 "과거 유사 사례"라 부르지 않도록), (c) 옵션으로 최장 horizon 이
   완결된 날짜만.
5. **De-clustering** — 같은 국면의 연속된 날들이 표본을 부풀리지 않도록 선택된
   match 끼리 최소 간격(1/5/10/20/40/60거래일 선택)을 강제합니다. 한 episode 의
   대표는 **유사도 최고일** 또는 **가장 먼저 나온 날** 중 선택.

---

## 5. Forward Return 분석

각 match 날짜 t의 종가 기준:

* `fwd_h = Close_{t+h}/Close_t − 1`  (h = 5/20/60/120 거래일)
* `mdd_h = min_{j≤h} ( Close_{t+j} / max(Close_t..Close_{t+j}) − 1 )` — 구간 내 최대 낙폭

horizon 별로 **관측 수 / 평균 / 중앙값 / 승률 / 25·75 분위 / 최소 / 최대 /
표준편차 / 평균 최대낙폭**을 매칭 표본과 **전체 20년 무조건부(baseline)** 양쪽에
대해 계산하고, 차이(%p)와 baseline 분포 내 백분위를 함께 보여 줍니다.

### 표본 독립성과 불확실성

de-clustering 간격을 20거래일로 두면 5D·20D 는 겹치지 않지만 **60D·120D 는 여전히
크게 겹칩니다.** n=25 로 보이는 표본이 실제로는 몇 개 국면일 뿐인 상황이라, 다음
세 가지를 함께 제공합니다.

1. **유효 표본수 (effective sample size)**

   `n_eff = n² / Σᵢⱼ max(0, 1 − |tᵢ−tⱼ|/h)`

   두 match 가 horizon 의 절반만큼 떨어져 있으면 forward 구간의 절반을 공유하므로
   2개가 아니라 약 1.5개의 정보량입니다. 이를 모두 더해 n 을 할인한 값으로,
   화면에 `n`, `독립 에피소드 수`, `n_eff`, `n_eff/n` 을 나란히 표시합니다.
2. **Cluster bootstrap (기본값)** — forward 구간이 겹치는 match 들을 하나의
   **에피소드**로 묶고(단일 연결: 0·15·30일은 h=20에서 한 에피소드), 관측치가
   아니라 **에피소드를 통째로 재표본**합니다. 표본을 버리지 않으면서 종속성을
   반영하는 방법이며, 같은 화면에 i.i.d. bootstrap 의 구간 폭도 함께 보여 줘
   **"단순 i.i.d. 를 썼다면 구간이 몇 % 좁게 나왔을지"** 를 바로 확인할 수 있습니다.
   (합성 데이터 실측: h=120, n=25 → n_eff 11.5, 에피소드 9개, cluster CI 폭 12.3%p
   vs i.i.d. 8.8%p — i.i.d. 가 약 29% 좁게 나옵니다.)
3. **Horizon 별 독립 표본 모드 (선택)** — 5D→5일, 20D→20일, 60D→60일, 120D→120일
   간격을 horizon 마다 다시 강제해 **완전히 겹치지 않는 표본**만 사용합니다. 겹침이
   0이 되는 대신 표본이 줄어드므로(25 → 11 수준) 기본값은 1·2번이고, 이 모드는
   사이드바에서 켭니다. 제외된 개수는 결과에 함께 표시됩니다.

baseline 은 시계열 전체가 겹치는 구간이므로 그대로 **moving-block bootstrap**
(블록 길이 = horizon) 을 씁니다. 표본이 기준치(기본 10개) 미만, 평균 CI 가 0을
포함, n_eff 가 n 의 80% 미만인 경우 각각 경고가 뜹니다.

---

## 6. 시각화

* 20년 종가 라인(로그 스케일 토글) + 선택한 SMA.
* match 는 **날짜부터 horizon 만큼 음영 처리**하고 마커에 hover 로 날짜 ·
  similarity score · 주요 feature · 분산일 개수 · 5/20/60/120일 forward return 표시.
* **x축을 공유하는 하단 패널에 미국 10년물 금리**.
* 별도 표에서 similarity 순으로 정렬해 보고 CSV 로 내보낼 수 있습니다.
* matched vs baseline 평균 막대그래프(오차막대 = bootstrap CI), 분포 히스토그램.

---

## 6-1. 계산 감사 (Calculation Audit)

**④ 계산 감사 탭**에서 match 한 날짜를 고르면 그 날짜의 계산 전 과정을 펼쳐 봅니다.

1. 원본 OHLCV (전일·당일·익일)
2. SMA 값과 이격률 — 저장된 값과 "그 날짜까지의 종가로 다시 계산한 값"을 나란히
3. 분산일 판정 근거 — 세 조건의 값·임계값·비교연산자·통과 여부, lookback 안의 분산일 목록
4. feature 별 raw / center / scale / z(과거일) / z(기준일) / z차이 / weight /
   가중 기여 `w·Δz²` / 기여 비중(%)
5. 거리 `d = √(Σw·Δz² / Σw)` 와 점수 `100·exp(−d²/2)`, 그리고 엔진이 계산한 거리와의
   차이(검산 — 실측 0.00e+00)
6. de-clustering 전 순위·후보 총수·최종 선택 여부, 탈락했다면 **어느 날짜에 자리를
   내줬는지**(간격·점수 포함)
7. 5/20/60/120D forward return 의 시작일·시작 종가·종료일·종료 종가·재계산 수익률·
   구간 최대낙폭·구간 최저 종가일

`tests/test_regime_audit.py` 는 임의의 과거 5개 날짜에 대해 위 값들을 **plain
pandas 로 독립 재계산**해 감사 화면 값과 일치하는지 검증합니다.

## 7. 통계적 검증 (Out-of-Sample / Walk-forward)

같은 데이터로 규칙을 만들고 같은 데이터로 성과를 재면 과최적화를 피할 수 없습니다.
검증 모드에서는 **파라미터를 고정한 채** 평가일마다 다음을 반복합니다.

1. 정규화 통계는 평가일 t까지의 데이터로만 추정.
2. 후보는 **자신의 forward 구간이 t 이전에 끝난 날**만 — t 시점에는 아직 진행 중인
   구간의 결과를 알 수 없기 때문입니다.
3. 매칭된 날들의 `+H일 수익률 중앙값`을 **신호**로 삼고,
4. t 이후 실제로 실현된 `+H일 수익률`과 비교.

fold 별로 평가 횟수 · 신호 평균 · 실현 평균 · 같은 기간 무조건부 평균 ·
초과(%p) · 방향 적중률 · Spearman 상관 · 신호 상·하위 tercile 스프레드를 보여 주고,
**In-Sample 과 Out-of-Sample 을 구분 표시**하며 둘의 격차를 지표로 제공합니다
(격차가 크면 과적합 신호).

레이아웃 두 가지:
* **고정 분할** — 예: Training 2006–2015 / Validation 2016–2020 / OOS 2021–현재
* **Expanding window** — 2016, 2017, 2018 … 연도별로 이어서 평가

---

## 8. 확장

* **임의 티커** — 사이드바 입력. 아래 계층은 티커를 모릅니다.
* **입력 방식** — Auto Download 와 Manual Upload 는 `loader.DataOverrides` 에서만
  갈라지고, 그 아래로는 동일한 `MarketData` 하나만 흐릅니다.
* **새 시계열(VIX, credit spread, Fed Funds, breadth)** — `regime_config.yaml`
  `market.exogenous` 에 한 줄. 수준/변화/백분위 feature 가 자동 생성됩니다.
* **새 feature 계열** — `app/regime/features/` 에 builder 를 하나 만들고
  `register()`. similarity·forward·validation·UI 는 손대지 않습니다.
* **새 데이터 소스** — `data/sources.py` 에 `fetch_*` 하나 추가.

---

## 9. 한계

* 유사도는 인과가 아니라 **조건부 분포**입니다. 매칭 표본이 작고 forward 구간이
  겹치면 신뢰구간이 넓어지며, 이는 화면에 그대로 드러납니다.
* 20년(약 5,000거래일) 안에 진짜로 독립적인 하락 국면은 손에 꼽습니다.
  de-clustering 후 n=10~30 은 흔하고, 그때의 평균은 몇 개 episode 가 좌우합니다.
* 지수 거래량(^IXIC)은 구성종목 합산(composite) 거래량이며, 개별 종목에서는 분할일에
  거래량 배수가 일시적으로 왜곡될 수 있습니다. 데이터 품질 탭이 이를 항상 명시합니다.
* 60D·120D 통계는 표본이 겹칩니다. n 대신 `n_eff` 와 에피소드 수를 함께 읽어야 하며,
  i.i.d. bootstrap 구간은 (비교용으로만 표시되고) 실제보다 좁습니다.
* 결과는 리서치 도구이며 투자 권유가 아닙니다.
