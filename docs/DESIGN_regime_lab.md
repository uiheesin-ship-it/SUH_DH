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
    align.py           거래일 달력 정렬 (forward-fill only)
    loader.py          MarketData 조립 + 디스크 캐시
  features/
    base.py            FeatureSpec / FeatureSet / builder 레지스트리
    trend.py           SMA 이격률, 배열, 기울기
    momentum.py        5/20/60/120일 수익률, 52주 고점 대비 낙폭
    volatility.py      realized volatility, ATR%
    distribution.py    분산일 판정 · 개수 · 경과일
    macro.py           외생 시계열(현재 10년물) 수준/변화/백분위 — 자동 생성
  similarity.py        as-of 정규화 · 가중 거리 · de-clustering
  matching.py          strict 조건 매칭
  forward.py           forward return 통계 · bootstrap CI · baseline 비교
  validation.py        walk-forward / out-of-sample
  viz.py               Plotly figure (Streamlit 비의존)
  ui.py                사이드바 위젯 → 파라미터 dataclass
  streamlit_app.py     화면 조립 (얇게)
regime_config.yaml     모든 기본값
tests/test_regime.py   오프라인 단위 테스트 (look-ahead 검증 포함)
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
| 1차 소스 | Yahoo Finance (yfinance) |
| 폴백 | Stooq CSV → 디스크 캐시(만료 무시) → 합성 데이터(데모) |
| 캐시 | `data/regime/<symbol>.csv`, 기본 TTL 6시간 (`SUH_DH_REGIME_TTL`) |
| 표시 | 시리즈별 **최종 업데이트 날짜 · 출처 · 행 수 · 지연일**을 화면 상단에 노출 |

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

### 불확실성
* 평균·중앙값에 대해 **percentile bootstrap 95% CI**(반복 수·신뢰수준 조정 가능).
* **baseline 은 block bootstrap**(블록 길이 = horizon). 겹치는 forward 구간은
  자기상관이 강해서 i.i.d. bootstrap 을 쓰면 구간이 실제보다 좁게 나옵니다.
* **matched 는 de-clustering 된 표본이므로 i.i.d.** bootstrap. 단, 최소 간격이
  horizon 보다 짧으면 구간이 겹치므로 화면에 경고를 띄웁니다.
* 표본이 기준치(기본 10개) 미만이면 경고, 평균 CI 가 0을 포함하면 "방향성 결론
  불가"를 명시합니다.

---

## 6. 시각화

* 20년 종가 라인(로그 스케일 토글) + 선택한 SMA.
* match 는 **날짜부터 horizon 만큼 음영 처리**하고 마커에 hover 로 날짜 ·
  similarity score · 주요 feature · 분산일 개수 · 5/20/60/120일 forward return 표시.
* **x축을 공유하는 하단 패널에 미국 10년물 금리**.
* 별도 표에서 similarity 순으로 정렬해 보고 CSV 로 내보낼 수 있습니다.
* matched vs baseline 평균 막대그래프(오차막대 = bootstrap CI), 분포 히스토그램.

---

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
* 지수 거래량(^IXIC)은 구성종목 합산 거래량이며, 개별 종목에서는 분할일에
  거래량 배수가 일시적으로 왜곡될 수 있습니다.
* 결과는 리서치 도구이며 투자 권유가 아닙니다.
