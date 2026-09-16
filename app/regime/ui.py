"""Streamlit sidebar: every parameter in one place, none of the maths.

Each section takes the defaults loaded from ``regime_config.yaml`` and returns
the immutable parameter dataclasses the analysis layer consumes, so the UI can
be swapped (or scripted around) without touching a single calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd
import streamlit as st

from .config import (DistributionParams, FeatureParams, ForwardParams, Params,
                     SimilarityParams, ValidationParams)
from .matching import Condition

SMA_CHOICES = [10, 20, 50, 100, 150, 200]
RETURN_CHOICES = [5, 10, 20, 60, 120, 250]
HORIZON_CHOICES = [5, 10, 20, 60, 120, 250]
GAP_CHOICES = [1, 5, 10, 20, 40, 60]
STRICT_OPS = ["<=", "<", ">=", ">", "between"]


@dataclass
class UIState:
    params: Params
    mode: str = "similarity"                 # similarity | strict
    conditions: list[Condition] = field(default_factory=list)
    anchor: pd.Timestamp | None = None
    shade_horizon: int = 20
    log_scale: bool = True
    show_sma: tuple[int, ...] = (50, 200)
    source: str = "auto"
    hist_horizon: int = 20


def data_section(defaults: Params) -> tuple[str, int, str]:
    st.sidebar.header("1. 데이터")
    ticker = st.sidebar.text_input(
        "티커", value=defaults.ticker,
        help="^IXIC(나스닥 종합), ^GSPC, QQQ, AAPL … 야후 파이낸스 심볼이면 무엇이든 동일하게 분석합니다.")
    years = st.sidebar.slider("기간 (년)", 5, 25, int(defaults.years))
    offline = st.sidebar.checkbox(
        "오프라인 데모 데이터", value=False,
        help="네트워크가 막힌 환경에서 UI/계산을 확인할 때 쓰는 합성 시계열입니다. 실제 시장 데이터가 아닙니다.")
    if st.sidebar.button("데이터 새로고침 (캐시 비우기)"):
        st.cache_data.clear()
        st.rerun()
    return ticker.strip() or defaults.ticker, years, ("synthetic" if offline else "auto")


def feature_section(defaults: Params) -> tuple[FeatureParams, DistributionParams]:
    fp, dp = defaults.features, defaults.distribution
    st.sidebar.header("2. 시장 상태 정의")

    with st.sidebar.expander("추세 (Trend)", expanded=False):
        sma_windows = st.multiselect("이동평균", SMA_CHOICES, default=list(fp.sma_windows))
        slope_smas = st.multiselect("기울기를 볼 이동평균", SMA_CHOICES, default=list(fp.slope_smas))
        slope_window = st.slider("기울기 측정 구간 (N일)", 5, 120, int(fp.slope_window), step=5)

    with st.sidebar.expander("모멘텀 / 위치", expanded=False):
        return_windows = st.multiselect("수익률 구간", RETURN_CHOICES, default=list(fp.return_windows))
        high_window = st.slider("고점 기준 구간 (52주=252)", 60, 500, int(fp.high_window), step=1)

    with st.sidebar.expander("변동성", expanded=False):
        vol_window = st.slider("실현 변동성 구간", 5, 120, int(fp.vol_window), step=1)
        atr_window = st.slider("ATR 구간", 5, 60, int(fp.atr_window), step=1)

    with st.sidebar.expander("분산일 (Distribution Day)", expanded=True):
        lookback = st.slider("Lookback (거래일)", 5, 120, int(dp.lookback), step=1)
        drop_pct = st.slider("X: 일간 하락률 ≥ (%)", 0.0, 3.0, float(dp.drop_pct), step=0.05,
                             help="일간 수익률이 -X% 이하인 날")
        volume_bump = st.slider("Y: 거래량 증가 ≥ 전일 대비 (%)", -20.0, 100.0,
                                float(dp.volume_bump_pct), step=1.0)
        clv_max = st.slider("Z: Close Location Value ≤", 0.0, 1.0, float(dp.clv_max), step=0.05,
                            help="(종가-저가)/(고가-저가). 낮을수록 종가가 저가 근처")

    with st.sidebar.expander("매크로 (10년물 등)", expanded=False):
        yield_changes = st.multiselect("금리 변화 구간", [5, 20, 60, 120, 250],
                                       default=list(fp.yield_change_windows))
        yield_pctile = st.slider("금리 백분위 구간", 120, 1000, int(fp.yield_pctile_window), step=10)

    features = FeatureParams(
        sma_windows=tuple(sorted(sma_windows or fp.sma_windows)),
        slope_window=int(slope_window),
        slope_smas=tuple(sorted(slope_smas)),
        return_windows=tuple(sorted(return_windows or fp.return_windows)),
        high_window=int(high_window),
        vol_window=int(vol_window),
        atr_window=int(atr_window),
        yield_change_windows=tuple(sorted(yield_changes)),
        yield_pctile_window=int(yield_pctile),
    )
    dist = DistributionParams(lookback=int(lookback), drop_pct=float(drop_pct),
                              volume_bump_pct=float(volume_bump), clv_max=float(clv_max),
                              days_since_cap=dp.days_since_cap)
    return features, dist


def match_section(defaults: Params, fs) -> tuple[str, SimilarityParams, list[Condition]]:
    sp = defaults.similarity
    st.sidebar.header("3. 과거 유사 국면 찾기")
    mode = st.sidebar.radio("모드", ["Similarity Match", "Strict Match"], index=0,
                            help="Similarity: feature 벡터 거리로 순위 / Strict: 조건을 모두 만족하는 날짜")
    mode_key = "similarity" if mode.startswith("Similarity") else "strict"

    top_n = st.sidebar.slider("상위 N개", 5, 100, int(sp.top_n), step=1)
    min_gap = st.sidebar.select_slider("De-clustering 최소 간격 (거래일)", options=GAP_CHOICES,
                                       value=int(sp.min_gap) if int(sp.min_gap) in GAP_CHOICES else 20)
    pick = st.sidebar.radio("한 episode 에서 고를 날", ["유사도 최고", "가장 먼저"],
                            index=0 if sp.episode_pick == "best" else 1, horizontal=True)
    exclude_recent = st.sidebar.slider("최근 N거래일 제외", 0, 250, int(sp.exclude_recent), step=5,
                                       help="기준일과 겹치는 직전 구간을 '과거 유사 사례'로 세지 않기 위한 장치")
    normalization = st.sidebar.selectbox("정규화", ["robust (중앙값/MAD)", "zscore (평균/표준편차)"],
                                         index=0 if sp.normalization == "robust" else 1)
    require_full = st.sidebar.checkbox("최장 horizon 이 다 채워진 날짜만", value=bool(sp.require_full_horizon))

    weights: dict[str, float] = {}
    if mode_key == "similarity":
        st.sidebar.caption("Feature 가중치 (0 = 사용 안 함)")
        for group, specs in fs.by_group().items():
            with st.sidebar.expander(f"가중치 · {group}", expanded=(group == "Trend")):
                for spec in specs:
                    default = float(sp.weights.get(spec.key, spec.default_weight))
                    weights[spec.key] = st.slider(spec.label, 0.0, 3.0, default, step=0.25,
                                                  key=f"w_{spec.key}", help=spec.description or None)

    conditions: list[Condition] = []
    if mode_key == "strict":
        st.sidebar.caption("조건 (모두 AND)")
        keys = st.sidebar.multiselect(
            "조건을 걸 feature", list(fs.values.columns),
            default=[k for k in ("dd_52w", "dd_count") if k in fs.values.columns],
            format_func=lambda k: fs.specs[k].label if k in fs.specs else k)
        for key in keys:
            spec = fs.specs.get(key)
            series = fs.values[key].dropna()
            with st.sidebar.expander(spec.label if spec else key, expanded=True):
                op = st.selectbox("조건", STRICT_OPS, key=f"op_{key}")
                lo = float(series.quantile(0.10)) if len(series) else 0.0
                hi = float(series.quantile(0.90)) if len(series) else 1.0
                v1 = st.number_input("값", value=round(lo, 2), step=0.1, key=f"v1_{key}")
                v2 = None
                if op == "between":
                    v2 = st.number_input("상한", value=round(hi, 2), step=0.1, key=f"v2_{key}")
            conditions.append(Condition(key=key, op=op, value=float(v1),
                                        value2=None if v2 is None else float(v2)))
        # Strict 모드에서도 표/차트 정렬용 유사도는 기본 가중치로 계산한다.
        weights = {k: float(sp.weights.get(k, fs.specs[k].default_weight))
                   for k in fs.values.columns if k in fs.specs}

    sim = SimilarityParams(
        weights={k: v for k, v in weights.items() if v > 0},
        top_n=int(top_n), min_gap=int(min_gap),
        episode_pick="best" if pick == "유사도 최고" else "first",
        exclude_recent=int(exclude_recent),
        require_full_horizon=bool(require_full),
        normalization="robust" if normalization.startswith("robust") else "zscore",
        min_history=sp.min_history, max_distance=sp.max_distance)
    return mode_key, sim, conditions


def forward_section(defaults: Params) -> ForwardParams:
    fwd = defaults.forward
    st.sidebar.header("4. Forward Return")
    horizons = st.sidebar.multiselect("Horizon (거래일)", HORIZON_CHOICES, default=list(fwd.horizons))
    n_boot = st.sidebar.select_slider("Bootstrap 반복 수", options=[500, 1000, 2000, 5000],
                                      value=int(fwd.bootstrap_samples))
    ci = st.sidebar.select_slider("신뢰수준", options=[0.80, 0.90, 0.95, 0.99], value=float(fwd.ci_level))
    warn = st.sidebar.number_input("표본 경고 기준 (개)", 3, 100, int(fwd.min_sample_warn))
    indep = st.sidebar.radio(
        "표본 독립성", ["전체 사용 (겹침은 CI 에 반영)", "horizon 별 독립 표본"],
        index=0 if fwd.independence == "all" else 1,
        help="전체 사용: 모든 match 를 쓰고 겹침을 cluster bootstrap·유효표본수로 반영합니다. "
             "horizon 별 독립: 5/20/60/120일 각각에 대해 최소 간격을 그 horizon 만큼 다시 강제해 "
             "구간이 겹치지 않는 표본만 씁니다(표본 수는 줄어듭니다).")
    ci_method = st.sidebar.selectbox(
        "신뢰구간 재표본 방식", ["cluster (겹치는 에피소드 단위)", "iid (단순 — 비교용)"],
        index=0 if fwd.ci_method == "cluster" else 1)
    return ForwardParams(horizons=tuple(sorted(horizons or fwd.horizons)),
                         bootstrap_samples=int(n_boot), ci_level=float(ci),
                         min_sample_warn=int(warn), seed=fwd.seed,
                         independence="all" if indep.startswith("전체") else "horizon",
                         ci_method="cluster" if ci_method.startswith("cluster") else "iid")


def validation_section(defaults: Params, index: pd.DatetimeIndex) -> ValidationParams:
    v = defaults.validation
    st.sidebar.header("5. 통계적 검증")
    mode = st.sidebar.radio("방식", ["고정 분할", "Expanding window"],
                            index=0 if v.mode == "fixed" else 1, horizontal=True)
    lo = index.min().date() if len(index) else pd.Timestamp(v.train_end).date()
    hi = index.max().date() if len(index) else pd.Timestamp(v.validation_end).date()

    def _clamp(value: str):
        d = pd.Timestamp(value).date()
        return min(max(d, lo), hi)

    if mode == "고정 분할":
        train_end = st.sidebar.date_input("Training 종료", value=_clamp(v.train_end),
                                          min_value=lo, max_value=hi)
        valid_end = st.sidebar.date_input("Validation 종료", value=_clamp(v.validation_end),
                                          min_value=lo, max_value=hi)
        expanding_start = v.expanding_start
    else:
        expanding_start = str(st.sidebar.date_input("Expanding 평가 시작",
                                                    value=_clamp(v.expanding_start),
                                                    min_value=lo, max_value=hi))
        train_end, valid_end = pd.Timestamp(v.train_end).date(), pd.Timestamp(v.validation_end).date()
    step = st.sidebar.slider("평가일 간격 (거래일)", 1, 20, int(v.step))
    horizon = st.sidebar.selectbox("검증 horizon", HORIZON_CHOICES,
                                   index=HORIZON_CHOICES.index(int(v.horizon)) if int(v.horizon) in HORIZON_CHOICES else 2)
    return ValidationParams(mode="fixed" if mode == "고정 분할" else "expanding",
                            train_end=str(train_end), validation_end=str(valid_end),
                            step=int(step), expanding_start=str(expanding_start),
                            horizon=int(horizon))


def chart_section(defaults: Params) -> tuple[int, bool, tuple[int, ...]]:
    st.sidebar.header("6. 차트")
    shade = st.sidebar.selectbox("Match 음영 구간 (거래일)", list(defaults.forward.horizons), index=0)
    log_scale = st.sidebar.checkbox("로그 스케일", value=True)
    smas = st.sidebar.multiselect("차트에 표시할 SMA", list(defaults.features.sma_windows),
                                  default=[w for w in (50, 200) if w in defaults.features.sma_windows])
    return int(shade), bool(log_scale), tuple(smas)


def apply(defaults: Params, *, ticker: str, years: int, features: FeatureParams,
          distribution: DistributionParams, similarity: SimilarityParams,
          forward: ForwardParams, validation: ValidationParams) -> Params:
    return replace(defaults, ticker=ticker, years=years, features=features,
                   distribution=distribution, similarity=similarity,
                   forward=forward, validation=validation)
