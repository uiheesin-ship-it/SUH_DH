"""Streamlit sidebar: every parameter in one place, none of the maths.

Each section takes the defaults loaded from ``regime_config.yaml`` and returns
the immutable parameter dataclasses the analysis layer consumes, so the UI can
be swapped (or scripted around) without touching a single calculation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

import pandas as pd
import streamlit as st

from .config import (DistributionParams, FeatureParams, ForwardParams, Params,
                     SimilarityParams, ValidationParams)
from .data import loader, upload
from .matching import Condition

SMA_CHOICES = [10, 20, 50, 100, 150, 200]
RETURN_CHOICES = [5, 10, 20, 60, 120, 250]
HORIZON_CHOICES = [5, 10, 20, 60, 120, 250]
GAP_CHOICES = [1, 5, 10, 20, 40, 60]
STRICT_OPS = ["<=", "<", ">=", ">", "between"]


NONE_LABEL = "(없음)"
UNIT_CHOICES = ["auto (자동 추정)", "percent (4.28)", "decimal (0.0428)",
                "basis_points (428)", "tenths (42.8)"]
UNIT_KEYS = {"auto (자동 추정)": "auto", "percent (4.28)": "percent",
             "decimal (0.0428)": "decimal", "basis_points (428)": "basis_points",
             "tenths (42.8)": "tenths"}


@dataclass
class DataInput:
    """What the data section resolved to — the only thing the app needs to load."""

    ticker: str = "^IXIC"
    years: int = 20
    source: str = "auto"                 # auto | synthetic
    mode: str = "auto"                   # auto | manual
    overrides: object | None = None      # loader.DataOverrides
    notes: list[tuple[str, str]] = field(default_factory=list)
    key: str = ""                        # 캐시 키 (파일 내용 + 매핑 해시)


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


def _file_bytes(f) -> bytes:
    return f.getvalue() if hasattr(f, "getvalue") else f.read()


def _mapping_widgets(columns, fields, prefix: str, required: tuple[str, ...]) -> dict:
    """Column mapping selectboxes, pre-filled with the auto-detected guess."""
    guess = upload.suggest_mapping(columns, fields)
    options = [NONE_LABEL] + list(columns)
    mapping: dict[str, str | None] = {}
    cols = st.columns(2)
    for i, fld in enumerate(fields):
        default = guess.get(fld)
        idx = options.index(default) if default in options else 0
        label = fld.capitalize() + (" *" if fld in required else "")
        picked = cols[i % 2].selectbox(label, options, index=idx, key=f"{prefix}_{fld}")
        mapping[fld] = None if picked == NONE_LABEL else picked
    return mapping


def _read_upload(f, prefix: str):
    """Uploaded file → raw DataFrame (+ sheet picker for workbooks)."""
    data = _file_bytes(f)
    sheet = 0
    names = upload.sheet_names(data, f.name)
    if names:
        sheet = st.selectbox("시트", names, key=f"{prefix}_sheet")
    return upload.read_table(data, f.name, sheet=sheet), data


def data_section(defaults: Params, host=None) -> DataInput:
    """Data input step.

    ``host`` is any Streamlit container: ``st.sidebar`` keeps the old sidebar
    layout, ``st`` puts the whole step at the top of the page — which is what
    the dashboard-embedded flow uses (업로드 → 매핑 → 품질 → 분석 실행이 한 화면에서
    이어지도록).
    """
    host = host or st.sidebar
    inline = host is not st.sidebar

    if inline:
        host.subheader("① 데이터")
    else:
        host.header("1. 데이터")
    top = host.columns([2, 1, 2]) if inline else None
    tbox = top[0] if inline else host
    ybox = top[1] if inline else host
    mbox = top[2] if inline else host

    ticker = tbox.text_input(
        "티커", value=defaults.ticker,
        help="^IXIC(나스닥 종합), ^GSPC, QQQ, AAPL … Auto Download 시 야후 파이낸스 심볼. "
             "Manual Upload 에서는 화면 표기용 이름으로만 쓰입니다.")
    years = ybox.slider("기간 (년)", 5, 25, int(defaults.years))
    mode = mbox.radio("데이터 입력 방식", ["Auto Download", "Manual Upload"], index=0,
                      horizontal=inline,
                      help="Manual Upload 를 고르면 업로드한 파일이 Auto Download 보다 "
                           "우선 사용됩니다. 업로드한 파일은 이 세션에서만 쓰이고 저장되지 않습니다.")
    if host.button("데이터 새로고침 (캐시 비우기)"):
        st.cache_data.clear()
        st.rerun()

    if mode == "Auto Download":
        offline = host.checkbox(
            "오프라인 데모 데이터", value=False,
            help="네트워크가 막힌 환경에서 UI/계산을 확인할 때 쓰는 합성 시계열입니다. 실제 시장 데이터가 아닙니다.")
        return DataInput(ticker=ticker.strip() or defaults.ticker, years=years,
                         source="synthetic" if offline else "auto", mode="auto",
                         key="auto:synthetic" if offline else "auto")

    notes: list[tuple[str, str]] = []
    digest = hashlib.sha1()
    ov = loader.DataOverrides()

    with host.expander("① 가격 파일 (OHLCV)", expanded=True):
        st.caption("CSV / XLSX · 최소 컬럼: Date, Close (Open/High/Low/Volume 있으면 함께)")
        f = st.file_uploader("가격 파일", type=["csv", "txt", "tsv", "xlsx", "xlsm", "xls"],
                             key="price_file")
        if f is not None:
            raw, data = _read_upload(f, "price")
            digest.update(data)
            mapping = _mapping_widgets(raw.columns, upload.PRICE_FIELDS, "pm", ("date", "close"))
            digest.update(str(sorted(mapping.items())).encode())
            res = upload.build_prices(raw, mapping, f.name)
            notes += [(i.level, f"[가격 {f.name}] {i.message}") for i in res.issues]
            if res.ok:
                ov.prices, ov.price_label = res.frame, f.name
                st.success(f"{res.stats['rows']:,}행 · {res.stats['first']} ~ {res.stats['last']}")
            else:
                st.error(" / ".join(i.message for i in res.failed) or "파일을 해석하지 못했습니다.")

    with host.expander("② 거래량 (선택)", expanded=False):
        st.caption("가격 파일에 Volume 이 없거나, 다른 출처의 거래량을 쓰고 싶을 때만.")
        vol_mode = st.radio("거래량 소스", ["가격 파일 그대로", "별도 파일 업로드", "다른 종목의 거래량(proxy)"],
                            index=0, key="vol_mode")
        if vol_mode == "별도 파일 업로드":
            vf = st.file_uploader("거래량 파일", type=["csv", "txt", "tsv", "xlsx", "xlsm", "xls"],
                                  key="volume_file")
            if vf is not None:
                raw, data = _read_upload(vf, "vol")
                digest.update(data)
                mapping = _mapping_widgets(raw.columns, ("date", "volume"), "vm", ("date", "volume"))
                digest.update(str(sorted(mapping.items())).encode())
                res = upload.build_volume(raw, mapping, vf.name)
                notes += [(i.level, f"[거래량 {vf.name}] {i.message}") for i in res.issues]
                if res.ok:
                    ov.volume, ov.volume_label, ov.volume_kind = res.series, vf.name, "upload"
                    st.success(f"{res.stats['rows']:,}행 · {res.stats['first']} ~ {res.stats['last']}")
                else:
                    st.error(" / ".join(i.message for i in res.failed))
        elif vol_mode == "다른 종목의 거래량(proxy)":
            proxy = st.text_input("Proxy 종목", value="QQQ", key="proxy_symbol")
            st.warning(f"Volume Source: {proxy} proxy — 지수 자체의 거래량이 아닙니다. "
                       "분산일 개수는 이 종목 거래량으로 계산됩니다.")
            if st.checkbox(f"{proxy} 거래량을 대용으로 사용하는 데 동의", key="proxy_ack"):
                start = (pd.Timestamp.today().normalize()
                         - pd.DateOffset(years=int(years))).strftime("%Y-%m-%d")
                df, prov = loader.fetch_symbol(proxy, start)
                if len(df):
                    ov.volume = df["volume"]
                    ov.volume_label, ov.volume_kind = f"{proxy} proxy", "proxy"
                    digest.update(f"proxy:{proxy}:{prov}:{len(df)}".encode())
                    st.success(f"{proxy} 거래량 {len(df):,}행 ({prov})")
                else:
                    st.error(f"{proxy} 거래량을 받지 못했습니다 ({prov}).")

    with host.expander("③ 미국 10년물 (선택)", expanded=False):
        st.caption("CSV / XLSX · 최소 컬럼: Date, Yield")
        yf_ = st.file_uploader("10년물 파일", type=["csv", "txt", "tsv", "xlsx", "xlsm", "xls"],
                               key="yield_file")
        unit_label = st.selectbox("단위", UNIT_CHOICES, index=0, key="yield_unit",
                                  help="auto 는 값의 중앙값으로 추정합니다. 결과가 이상하면 직접 지정하세요.")
        if yf_ is not None:
            raw, data = _read_upload(yf_, "y10")
            digest.update(data)
            mapping = _mapping_widgets(raw.columns, upload.YIELD_FIELDS, "ym", ("date", "yield"))
            digest.update((str(sorted(mapping.items())) + unit_label).encode())
            res = upload.build_yield(raw, mapping, yf_.name, unit=UNIT_KEYS[unit_label])
            notes += [(i.level, f"[10Y {yf_.name}] {i.message}") for i in res.issues]
            if res.ok:
                key = str((defaults.exogenous[0].get("key") if defaults.exogenous else "y10"))
                ov.exog[key] = res.series
                ov.exog_labels[key] = yf_.name
                st.success(f"{res.stats['rows']:,}행 · 단위 {res.stats['applied_unit']} "
                           f"(추정 {res.stats['detected_unit']}) · 중앙값 {res.stats['median']:.2f}%")
            else:
                st.error(" / ".join(i.message for i in res.failed))

    if not ov.has_prices():
        host.info("가격 파일을 올리기 전까지는 Auto Download 결과를 보여 줍니다. "
                  "CSV 또는 XLSX 를 올리면 컬럼을 자동 인식하고, 매핑을 확인한 뒤 분석을 실행합니다.")
    return DataInput(ticker=ticker.strip() or defaults.ticker, years=years, source="auto",
                     mode="manual", overrides=ov, notes=notes,
                     key="manual:" + digest.hexdigest())


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
