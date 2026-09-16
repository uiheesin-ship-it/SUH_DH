"""Market Regime Lab — Streamlit entry point.

Run it with::

    streamlit run app/regime/streamlit_app.py     # 또는 ./run_regime.sh

The page is deliberately thin: it reads parameters from the sidebar
(``app/regime/ui.py``), calls the analysis modules (data → features →
similarity/matching → forward → validation) and draws the figures built in
``app/regime/viz.py``. Every number on screen comes from those modules, so the
same analysis can be scripted or unit-tested without Streamlit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # `streamlit run` 은 스크립트로 실행하므로 경로를 잡아 준다.
    sys.path.insert(0, str(ROOT))

from app.regime import matching, similarity, ui, validation, viz  # noqa: E402
from app.regime.config import Params, load_config  # noqa: E402
from app.regime.data import load_market  # noqa: E402
from app.regime.features import build_features  # noqa: E402
from app.regime.forward import analyze, forward_returns  # noqa: E402

st.set_page_config(page_title="Market Regime Lab", page_icon="📈", layout="wide")


# ---------------------------------------------------------------- data caching
@st.cache_data(ttl=3600, show_spinner="시장 데이터를 불러오는 중…")
def _load(ticker: str, years: int, exog_json: str, source: str):
    return load_market(ticker, years, json.loads(exog_json), source=source)


@st.cache_data(ttl=3600, show_spinner=False)
def _features(_market, signature: str):
    return build_features(_market, _signature_params(signature))


def _signature_params(signature: str) -> Params:
    """Rebuild the Params used for feature construction from its cache key."""
    return _PARAM_CACHE[signature]


_PARAM_CACHE: dict[str, Params] = {}


def _feature_signature(params: Params) -> str:
    sig = json.dumps({
        "ticker": params.ticker, "years": params.years,
        "features": params.features.__dict__, "distribution": params.distribution.__dict__,
        "exog": [e.get("key") for e in params.exogenous],
    }, default=str, sort_keys=True)
    _PARAM_CACHE[sig] = params
    return sig


@st.cache_data(ttl=3600, show_spinner="Walk-forward 검증 실행 중…")
def _walk_forward(_values, _close, _valid, weights_json: str, sim_json: str, signature: str):
    params = _PARAM_CACHE[signature]
    weights = json.loads(weights_json)
    return validation.walk_forward(_values, _close, weights, params.similarity, params, valid=_valid)


# ------------------------------------------------------------------- rendering
def _pct(x, digits: int = 2) -> str:
    return "–" if x is None or not np.isfinite(x) else f"{x:+.{digits}f}%"


def _ci(pair, digits: int = 2) -> str:
    lo, hi = pair
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return "–"
    return f"[{lo:+.{digits}f}, {hi:+.{digits}f}]"


def header(market, params: Params) -> None:
    st.title("📈 Market Regime Lab")
    st.caption(f"{market.ticker} · 현재 시장 상태를 정량화하고, 과거의 비슷한 국면과 그 이후 수익률을 찾아봅니다.")
    cols = st.columns(max(2, len(market.meta.get("series", {}))))
    for col, (symbol, info) in zip(cols, market.meta.get("series", {}).items()):
        stale = info.get("stale_days")
        note = f"출처 {info.get('source')}"
        if stale:
            note += f" · {stale}일 지연"
        col.metric(f"{info.get('label', symbol)} 최종 업데이트", info.get("last_date") or "–", help=note)
        col.caption(f"{info.get('first_date')} ~ {info.get('last_date')} · {info.get('rows', 0):,}행 · {note}")


def state_tab(market, fs, params: Params, anchor) -> None:
    st.subheader(f"기준일 {pd.Timestamp(anchor).date()} 의 시장 상태")
    px_row = market.prices.loc[anchor]
    c = st.columns(4)
    c[0].metric("종가", f"{px_row['close']:,.2f}")
    if "ret_5" in fs.values.columns:
        c[1].metric("5일 수익률", _pct(fs.values.loc[anchor, "ret_5"]))
    if "dd_52w" in fs.values.columns:
        c[2].metric(f"{params.features.high_window}일 고점 대비", _pct(fs.values.loc[anchor, "dd_52w"]))
    if "vol_realized" in fs.values.columns:
        c[3].metric("실현 변동성", fs.specs["vol_realized"].format(fs.values.loc[anchor, "vol_realized"]))

    row = fs.values.loc[anchor]
    for group, specs in fs.by_group().items():
        st.markdown(f"**{group}**")
        cols = st.columns(min(5, max(1, len(specs))))
        for i, spec in enumerate(specs):
            cols[i % len(cols)].metric(spec.label, spec.format(row.get(spec.key)),
                                       help=spec.description or None)

    dp = params.distribution
    st.markdown("**분산일 상세**")
    st.caption(f"조건: 일간 수익률 ≤ -{dp.drop_pct}% · 거래량 ≥ 전일 × {1 + dp.volume_bump_pct / 100:.2f} · "
               f"CLV ≤ {dp.clv_max} · 최근 {dp.lookback} 거래일")
    flags = fs.aux.loc[:anchor]
    recent = flags[flags["dd_flag"].fillna(False)].tail(10)
    if recent.empty:
        st.info("설정한 조건을 만족하는 분산일이 최근에 없습니다.")
    else:
        show = recent[["ret_pct", "vol_ratio", "clv"]].copy()
        show.columns = ["일간 수익률 (%)", "거래량 배수", "CLV"]
        st.dataframe(show.sort_index(ascending=False).round(3), width="stretch")


def matches_tab(market, fs, params: Params, state: ui.UIState, matches, info, table) -> None:
    if info.dropped_keys:
        st.warning("다음 feature 는 매칭에서 제외됐습니다 — " +
                   ", ".join(f"{fs.specs[k].label if k in fs.specs else k}({v})"
                             for k, v in info.dropped_keys.items()))
    if matches.empty:
        st.error("조건을 만족하는 과거 날짜가 없습니다. 조건을 완화하거나 가중치를 조정해 보세요.")
        return
    mode_label = "Similarity Match" if state.mode == "similarity" else "Strict Match"
    st.caption(f"{mode_label} · {len(matches)}개 · de-clustering {params.similarity.min_gap}거래일 "
               f"({'유사도 최고' if params.similarity.episode_pick == 'best' else '가장 먼저'} 기준) · "
               f"사용 feature {len(info.used_keys)}개")

    st.plotly_chart(
        viz.price_chart(market, fs, table, params.forward.horizons,
                        shade_horizon=state.shade_horizon, log_scale=state.log_scale,
                        show_sma=state.show_sma, anchor=state.anchor,
                        exog_label=(params.exogenous[0]["label"] if params.exogenous else "Macro")),
        width="stretch")

    display = table.copy()
    rename = {"score": "유사도", "distance": "거리", "close": "종가"}
    for k in list(display.columns):
        if k in fs.specs:
            rename[k] = fs.specs[k].label
    for h in params.forward.horizons:
        rename[f"fwd_{int(h)}"] = f"+{int(h)}일 (%)"
    rename[f"mdd_{int(max(params.forward.horizons))}"] = f"+{int(max(params.forward.horizons))}일 최대낙폭 (%)"
    display = display.rename(columns=rename)
    display.index = [pd.Timestamp(d).date() for d in display.index]
    display.index.name = "날짜"
    st.dataframe(display.round(2), width="stretch", height=420)
    st.download_button("매칭 결과 CSV", display.to_csv().encode("utf-8-sig"),
                       file_name=f"regime_matches_{market.ticker.strip('^')}.csv", mime="text/csv")


def forward_tab(market, fs, params: Params, matches, results) -> None:
    horizons = sorted(results)
    st.subheader("Forward Return — 매칭 표본 vs 전체 기간")
    rows = []
    for h in horizons:
        r = results[h]
        for name, stats in (("Matched", r.matched), ("Baseline", r.baseline)):
            rows.append({
                "Horizon": f"+{h}일", "표본": name, "N": stats["n"],
                "평균 (%)": stats["mean"], "중앙값 (%)": stats["median"],
                "승률 (%)": stats["win_rate"], "25% (%)": stats["p25"], "75% (%)": stats["p75"],
                "최소 (%)": stats["min"], "최대 (%)": stats["max"], "표준편차 (%)": stats["std"],
                "구간 내 평균 최대낙폭 (%)": stats["mdd_mean"],
                f"평균 {int(params.forward.ci_level * 100)}% CI": _ci(stats["ci_mean"]),
                f"중앙값 {int(params.forward.ci_level * 100)}% CI": _ci(stats["ci_median"]),
            })
    st.dataframe(pd.DataFrame(rows).round(2), width="stretch", hide_index=True)

    st.markdown("**Baseline 대비 초과/부족**")
    diff = pd.DataFrame([{
        "Horizon": f"+{h}일",
        "평균 차이 (%p)": results[h].diff_mean,
        "중앙값 차이 (%p)": results[h].diff_median,
        "승률 차이 (%p)": results[h].diff_win_rate,
        "Baseline 분포 내 백분위": results[h].baseline_pctile,
        "평균 CI 가 0 을 제외": "예" if results[h].ci_excludes_zero else "아니오",
    } for h in horizons]).round(2)
    st.dataframe(diff, width="stretch", hide_index=True)

    st.plotly_chart(viz.forward_bar_chart(results, params.forward.ci_level), width="stretch")

    pick = st.selectbox("분포를 볼 horizon", horizons, index=min(1, len(horizons) - 1),
                        format_func=lambda h: f"+{h} 거래일")
    fwd = forward_returns(market.prices["close"], horizons)[f"fwd_{pick}"]
    valid = fs.valid_mask()
    st.plotly_chart(viz.distribution_chart(fwd.reindex(matches.index), fwd[valid], pick),
                    width="stretch")

    for h in horizons:
        for msg in results[h].warnings:
            st.warning(f"+{h}일: {msg}")
    st.caption("Baseline CI 는 forward 구간이 겹치는 특성을 반영해 block bootstrap (블록 길이 = horizon) 으로, "
               "matched CI 는 de-clustering 된 표본에 대해 i.i.d. bootstrap 으로 계산합니다.")


def validation_tab(market, fs, params: Params, weights: dict, signature: str) -> None:
    v = params.validation
    st.subheader("Out-of-Sample / Walk-forward 검증")
    st.markdown(
        "같은 데이터로 규칙을 만들고 같은 데이터로 성과를 재면 과최적화를 피할 수 없습니다. "
        "여기서는 **파라미터를 고정한 채** 평가일마다 그 시점까지의 정보만으로 매칭을 다시 수행하고, "
        f"매칭된 날들의 **+{v.horizon}거래일 수익률 중앙값**을 신호로 삼아 실제로 뒤따른 수익률과 비교합니다. "
        "정규화 통계와 후보 날짜 모두 평가일 기준으로 잘라 쓰며, forward 구간이 아직 끝나지 않은 날은 후보에서 제외합니다.")
    st.caption(f"방식: {'고정 분할' if v.mode == 'fixed' else 'Expanding window'} · "
               f"평가일 간격 {v.step}거래일 · horizon +{v.horizon}일")

    if not weights:
        st.info("가중치가 모두 0 입니다 — 사이드바에서 feature 가중치를 설정하세요.")
        return
    if not st.button("검증 실행", type="primary"):
        st.caption("※ 전 구간을 다시 계산하므로 수십 초가 걸릴 수 있습니다.")
        return

    results = _walk_forward(fs.values, market.prices["close"], fs.valid_mask(),
                            json.dumps(weights, sort_keys=True), json.dumps({}), signature)
    summary = validation.summary_table(results)
    st.dataframe(summary.round(3), width="stretch", hide_index=True)
    st.plotly_chart(viz.validation_chart(summary), width="stretch")

    is_rows = summary[summary["구분"] == "In-Sample"]
    oos_rows = summary[summary["구분"] == "Out-of-Sample"]
    c1, c2, c3 = st.columns(3)
    c1.metric("In-Sample 초과수익 (%p)", f"{is_rows['초과(%p)'].mean():+.2f}" if len(is_rows) else "–")
    c2.metric("Out-of-Sample 초과수익 (%p)", f"{oos_rows['초과(%p)'].mean():+.2f}" if len(oos_rows) else "–")
    gap = (is_rows["초과(%p)"].mean() - oos_rows["초과(%p)"].mean()) if len(is_rows) and len(oos_rows) else np.nan
    c3.metric("IS − OOS 격차 (%p)", f"{gap:+.2f}" if np.isfinite(gap) else "–",
              help="격차가 크면 규칙이 과거 구간에 과적합됐다는 신호입니다.")
    st.download_button("검증 결과 CSV", summary.to_csv(index=False).encode("utf-8-sig"),
                       file_name="regime_validation.csv", mime="text/csv")


def data_tab(market, fs, params: Params) -> None:
    st.subheader("데이터 / 방법론")
    meta = pd.DataFrame(market.meta.get("series", {})).T
    st.dataframe(meta, width="stretch")
    st.markdown(f"""
**정렬 / 결측치 처리**
- 가격 시계열의 거래일이 기준 달력입니다. 10년물 금리 등 외생 시계열은 그 달력에 맞춰 **forward-fill 로만**
  채웁니다 (과거 값을 현재로 끌어오는 것은 그 시점 관찰자가 실제로 가졌던 정보). 뒤에서 앞으로 채우거나
  보간하면 미래 정보가 새기 때문에 이 프로젝트 어디에서도 쓰지 않습니다.
- 5거래일 넘게 비어 있는 구간은 채우지 않고 결측으로 둡니다.

**Look-ahead 방지**
- 모든 feature 는 t 시점까지의 값만 사용합니다 (rolling window, shift).
- 유사도 정규화(중앙값/MAD)도 기준일까지의 데이터로만 추정합니다.
- Forward return 은 평가 전용이며 feature 로 되돌아가지 않습니다.
- 검증 모드에서는 "forward 구간이 아직 끝나지 않은 날"을 후보에서 제외해, 평가 시점에 알 수 없는 결과가
  신호에 섞이지 않게 합니다.

**확장**
- `regime_config.yaml` 의 `market.exogenous` 에 한 줄 추가하면 VIX·크레딧 스프레드·Fed Funds 등이
  같은 feature framework (수준 / 변화 / 백분위) 로 들어옵니다.
- 새 feature 계열은 `app/regime/features/` 에 builder 하나를 추가하고 `register()` 하면 됩니다.
""")
    st.download_button("전체 feature CSV", fs.values.to_csv().encode("utf-8-sig"),
                       file_name=f"regime_features_{market.ticker.strip('^')}.csv", mime="text/csv")


def main() -> None:
    defaults = Params.from_config(load_config())
    ticker, years, source = ui.data_section(defaults)
    market = _load(ticker, years, json.dumps(list(defaults.exogenous)), source)
    if market.empty:
        st.error(f"`{ticker}` 데이터를 가져오지 못했습니다. 티커를 확인하거나, 네트워크가 막힌 환경이라면 "
                 "사이드바의 **오프라인 데모 데이터**를 켜고 UI/계산을 먼저 확인해 보세요.")
        st.stop()

    features, distribution = ui.feature_section(defaults)
    params = ui.apply(defaults, ticker=ticker, years=years, features=features,
                      distribution=distribution, similarity=defaults.similarity,
                      forward=defaults.forward, validation=defaults.validation)
    signature = _feature_signature(params)
    fs = _features(market, signature)

    mode, sim, conditions = ui.match_section(defaults, fs)
    fwd_params = ui.forward_section(defaults)
    val_params = ui.validation_section(defaults, market.calendar)
    shade, log_scale, show_sma = ui.chart_section(params)
    params = ui.apply(params, ticker=ticker, years=years, features=features,
                      distribution=distribution, similarity=sim, forward=fwd_params,
                      validation=val_params)
    signature = _feature_signature(params)

    header(market, params)
    valid = fs.valid_mask()
    usable = market.calendar[valid.reindex(market.calendar).fillna(False)]
    if len(usable) == 0:
        st.error("feature 를 계산할 수 있는 날짜가 없습니다. 기간을 늘리거나 window 를 줄여 보세요.")
        st.stop()

    anchor_date = st.sidebar.date_input("기준일 (기본: 최신 거래일)", value=usable.max().date(),
                                        min_value=usable.min().date(), max_value=usable.max().date())
    prior = usable[usable <= pd.Timestamp(anchor_date)]
    anchor = prior.max() if len(prior) else usable.max()

    state = ui.UIState(params=params, mode=mode, conditions=conditions, anchor=anchor,
                       shade_horizon=shade, log_scale=log_scale, show_sma=show_sma, source=source)

    max_h = int(max(params.forward.horizons))
    if mode == "similarity":
        matches, info = similarity.find_similar(fs.values, anchor, params.similarity.weights,
                                                params.similarity, valid=valid, max_horizon=max_h)
    else:
        matches, info = matching.strict_match(fs.values, conditions, anchor, params.similarity,
                                              weights=params.similarity.weights, max_horizon=max_h,
                                              valid=valid)
        matches = matches.head(params.similarity.top_n)

    table = viz.build_match_table(matches, fs, market.prices["close"], params.forward.horizons,
                                  keys=info.used_keys or list(fs.values.columns)[:6])
    results = analyze(market.prices["close"], matches.index, params.forward,
                      baseline_mask=valid, min_gap=params.similarity.min_gap)

    tabs = st.tabs(["① 현재 시장 상태", "② 과거 유사 국면", "③ Forward Return",
                    "④ 통계적 검증", "⑤ 데이터 / 방법론"])
    with tabs[0]:
        state_tab(market, fs, params, anchor)
    with tabs[1]:
        matches_tab(market, fs, params, state, matches, info, table)
    with tabs[2]:
        if matches.empty:
            st.info("매칭된 날짜가 없어 forward 분석을 건너뜁니다.")
        else:
            forward_tab(market, fs, params, matches, results)
    with tabs[3]:
        validation_tab(market, fs, params, params.similarity.weights, signature)
    with tabs[4]:
        data_tab(market, fs, params)


if __name__ == "__main__":
    main()
