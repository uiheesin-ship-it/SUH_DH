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

from app.regime import audit, matching, quality, similarity, ui, validation, viz  # noqa: E402
from app.regime.config import Params, load_config  # noqa: E402
from app.regime.data import load_market  # noqa: E402
from app.regime.features import build_features  # noqa: E402
from app.regime.forward import analyze, forward_returns  # noqa: E402

st.set_page_config(page_title="Market Regime Lab", page_icon="📈", layout="wide")


# ---------------------------------------------------------------- data caching
@st.cache_data(ttl=3600, show_spinner="시장 데이터를 불러오는 중…")
def _load(ticker: str, years: int, exog_json: str, source: str, data_key: str = "auto",
          _overrides=None):
    """``data_key`` is the cache key for a manual upload (file bytes + mapping
    digest); the overrides object itself is skipped by the hasher."""
    return load_market(ticker, years, json.loads(exog_json), source=source,
                       overrides=_overrides)


@st.cache_data(ttl=3600, show_spinner=False)
def _features(_market, signature: str):
    return build_features(_market, _signature_params(signature))


def _signature_params(signature: str) -> Params:
    """Rebuild the Params used for feature construction from its cache key."""
    return _PARAM_CACHE[signature]


_PARAM_CACHE: dict[str, Params] = {}


def _feature_signature(params: Params, data_id: str = "") -> str:
    """Cache key for anything derived from (parameters × dataset).

    ``data_id`` is what makes switching Auto Download → Manual Upload safe:
    without it a cached FeatureSet from the previous dataset would be served
    against a different trading calendar.
    """
    sig = json.dumps({
        "ticker": params.ticker, "years": params.years,
        "features": params.features.__dict__, "distribution": params.distribution.__dict__,
        "exog": [e.get("key") for e in params.exogenous],
        "data": data_id,
    }, default=str, sort_keys=True)
    _PARAM_CACHE[sig] = params
    return sig


def _data_id(market, data_key: str) -> str:
    last = market.last_date
    return f"{data_key}|{market.ticker}|{len(market.prices)}|{'' if last is None else last.date()}"


@st.cache_data(ttl=3600, show_spinner=False)
def _quality(_market, signature: str):
    return quality.run_checks(_market, _PARAM_CACHE[signature])


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


def source_line(market) -> None:
    """어떤 데이터로 지금 분석하고 있는지 — 화면 최상단에 항상 명시."""
    srcs = market.meta.get("sources", {}) or {}
    price, vol = srcs.get("price", {}), srcs.get("volume", {})
    exog = [(k.split(":", 1)[1], v) for k, v in srcs.items() if str(k).startswith("exog:")]
    kind = quality.KIND_LABELS
    bits = [f"**Price** {kind.get(price.get('kind'), '–')} · `{price.get('name')}`",
            f"**Volume** {kind.get(vol.get('kind'), '–')} · `{vol.get('name')}`"]
    bits += [f"**{k}** {kind.get(v.get('kind'), '–')} · `{v.get('name')}`" for k, v in exog]
    st.markdown("데이터 소스 — " + "  |  ".join(bits))
    if vol.get("kind") == "proxy":
        name = quality.INDEX_NAMES.get(market.ticker.upper(), market.ticker)
        st.warning(f"**Volume Source: {vol.get('name')} — not {name} volume** · "
                   "분산일 개수는 지수 자체의 거래량이 아니라 대용 종목의 거래량으로 계산됩니다.")


def header(market, params: Params) -> None:
    st.title("📈 Market Regime Lab")
    st.caption(f"{market.ticker} · 현재 시장 상태를 정량화하고, 과거의 비슷한 국면과 그 이후 수익률을 찾아봅니다.")
    source_line(market)
    cols = st.columns(max(2, len(market.meta.get("series", {}))))
    for col, (symbol, info) in zip(cols, market.meta.get("series", {}).items()):
        stale = info.get("stale_days")
        note = f"출처 {info.get('source')}"
        if stale:
            note += f" · {stale}일 지연"
        col.metric(f"{info.get('label', symbol)} 최종 업데이트", info.get("last_date") or "–", help=note)
        col.caption(f"{info.get('first_date')} ~ {info.get('last_date')} · {info.get('rows', 0):,}행 · {note}")


def quality_banner(reports) -> None:
    status = quality.overall_status(reports)
    problems = [(r.series, c) for r in reports for c in r.problems()]
    if status == "fail":
        st.error("데이터 품질 검사에서 **치명적 문제**가 발견됐습니다 — " +
                 " / ".join(f"[{sr}] {c.label}: {c.detail}" for sr, c in problems[:3]) +
                 "  ⟶ ⑥ 데이터 품질 탭에서 전체 확인")
    elif status == "warn":
        st.warning("데이터 품질 경고 " + str(len(problems)) + "건 — " +
                   " / ".join(f"[{sr}] {c.label}" for sr, c in problems[:4]) +
                   "  ⟶ ⑥ 데이터 품질 탭에서 확인")
    else:
        st.success("데이터 품질 검사 통과 (기간·중복·공백·결측·최신성·거래량·금리 단위)")


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
    indep_label = ("전체 사용 (겹침은 CI 에 반영)" if params.forward.independence == "all"
                   else "horizon 별 독립 표본")
    st.caption(f"표본 독립성: {indep_label} · 신뢰구간 재표본: {params.forward.ci_method} "
               f"· bootstrap {params.forward.bootstrap_samples:,}회")
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

    st.markdown("**표본 독립성 진단** — 겹치는 forward 구간을 n 그대로 세면 안 됩니다")
    indep = pd.DataFrame([{
        "Horizon": f"+{h}일",
        "사용 표본 n": results[h].matched["n"],
        "독립 에피소드 수": results[h].matched.get("n_episodes", 0),
        "유효 표본수 n_eff": results[h].ess,
        "n_eff / n": (results[h].ess / results[h].matched["n"]) if results[h].matched["n"] else np.nan,
        "제외된 match": results[h].dropped,
        "CI 방식": results[h].matched.get("ci_method", "–"),
        "평균 CI 폭 (%p)": results[h].ci_width,
        "i.i.d. CI 폭 (%p)": results[h].ci_width_iid,
        "i.i.d. 과소추정 (%)": ((1 - results[h].ci_width_iid / results[h].ci_width) * 100
                                if results[h].ci_width else np.nan),
    } for h in horizons]).round(2)
    st.dataframe(indep, width="stretch", hide_index=True)
    st.caption("n_eff = n² / Σᵢⱼ max(0, 1 − |tᵢ−tⱼ|/h) — forward 구간이 얼마나 겹치는지로 n 을 할인한 값. "
               "'i.i.d. 과소추정'이 양수면, 단순 i.i.d. bootstrap 을 썼을 때 신뢰구간이 그만큼 좁게 나왔다는 뜻입니다.")

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
    st.caption("Baseline CI 는 block bootstrap(블록 길이 = horizon), matched CI 는 기본적으로 "
               "cluster bootstrap(겹치는 match 들을 한 에피소드로 묶어 에피소드 단위로 재표본)으로 계산합니다. "
               "사이드바에서 horizon 별 독립 표본 모드나 i.i.d. 재표본으로 바꿔 비교할 수 있습니다.")


def audit_tab(market, fs, params: Params, anchor, scored, matches, mode: str) -> None:
    st.subheader("계산 감사 (Calculation Audit)")
    st.caption("선택한 날짜 하나에 대해 원본 OHLCV부터 최종 similarity score, forward return 까지 "
               "모든 중간값을 펼쳐 보여 줍니다. 표의 숫자만으로 결과를 손으로 재현할 수 있어야 합니다.")
    if matches is None or matches.empty:
        st.info("매칭된 날짜가 없습니다.")
        return

    options = list(matches.index)
    col1, col2 = st.columns([2, 1])
    picked = col1.selectbox("감사할 match 날짜", options,
                            format_func=lambda d: f"{pd.Timestamp(d).date()}  ·  유사도 "
                                                  f"{matches.loc[d, 'score']:.1f}")
    free = col2.checkbox("다른 날짜 직접 조회")
    if free:
        cal = market.calendar
        d = col2.date_input("날짜", value=pd.Timestamp(picked).date(),
                            min_value=cal.min().date(), max_value=cal.max().date())
        prior = cal[cal <= pd.Timestamp(d)]
        picked = prior.max() if len(prior) else picked

    res = audit.audit_match(market, fs, params, anchor, picked,
                            weights=params.similarity.weights, scored=scored, matches=matches,
                            horizons=params.forward.horizons)

    c = st.columns(4)
    c[0].metric("기준일(현재)", str(pd.Timestamp(anchor).date()))
    c[1].metric("감사 대상일", str(pd.Timestamp(picked).date()))
    c[2].metric("거리 d", f"{res.distance['거리 d = √(Σw·Δz²/Σw)']:.4f}")
    c[3].metric("유사도 score", f"{res.distance['점수 100·exp(−d²/2)']:.2f}")

    st.markdown("**① 원본 OHLCV** (전일·당일·익일)")
    st.dataframe(res.ohlcv.round(2), width="stretch")

    st.markdown("**② 이동평균과 이격률** — 저장된 값 vs 해당 날짜까지의 종가로 다시 계산한 값")
    st.dataframe(res.trend.round(4), width="stretch", hide_index=True)

    st.markdown("**③ 분산일 판정 근거** — 세 조건 모두 통과해야 분산일")
    st.dataframe(res.distribution.round(4), width="stretch", hide_index=True)
    st.caption(f"lookback {params.distribution.lookback}거래일 안의 분산일 "
               f"{len(res.dd_days)}일 (= feature `dd_count`)")
    if len(res.dd_days):
        st.dataframe(res.dd_days.round(3), width="stretch")

    st.markdown("**④ feature 별 raw → 표준화 → 거리 기여도**")
    st.dataframe(res.features.round(4), width="stretch", hide_index=True)
    st.caption("z = (raw − center) / scale, center·scale 은 기준일까지의 중앙값·MAD(또는 평균·표준편차). "
               "기여도 = weight × (z차이)², 거리 = √(기여도 합 / 가중치 합).")
    summary = {k: v for k, v in res.distance.items() if k != "제외된 feature"}
    st.dataframe(pd.DataFrame([summary]).round(6), width="stretch", hide_index=True)

    st.markdown("**⑤ de-clustering 전후 포함 여부**")
    st.dataframe(pd.DataFrame([{k: str(v) for k, v in res.declustering.items()}]).T
                 .rename(columns={0: "값"}), width="stretch")

    st.markdown("**⑥ forward return 계산에 쓰인 시작·종료 가격**")
    st.dataframe(res.forward.round(4), width="stretch", hide_index=True)

    for note in res.notes:
        st.caption("· " + note)
    st.download_button("이 날짜 feature 감사표 CSV", res.features.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"regime_audit_{pd.Timestamp(picked).date()}.csv", mime="text/csv")


def quality_tab(market, fs, params: Params, reports) -> None:
    st.subheader("Data Source Summary")
    st.dataframe(quality.data_source_summary(market), width="stretch", hide_index=True)
    st.caption("업로드 데이터와 자동 수신 데이터는 같은 스키마로 정규화되어 동일한 분석 로직을 탑니다.")

    st.subheader("데이터 품질 요약 (Data Quality Summary)")
    status = quality.overall_status(reports)
    {"fail": st.error, "warn": st.warning, "ok": st.success}.get(status, st.info)(
        {"fail": "치명적 문제가 있습니다 — 아래 항목을 먼저 해결하세요.",
         "warn": "주의할 항목이 있습니다.",
         "ok": "모든 검사를 통과했습니다."}.get(status, "검사 결과를 확인하세요."))
    st.dataframe(quality.summary_frame(reports), width="stretch", hide_index=True)
    sugg = [(r.series, c) for r in reports for c in (r.problems() + r.notes()) if c.suggestion]
    if sugg:
        st.markdown("**제안**")
        for series, c in sugg:
            st.markdown(f"- `{series}` · **{c.label}** — {c.suggestion}")
    st.caption("터미널에서도 같은 검사를 돌릴 수 있습니다:  "
               "`python3 -m app.regime.quality --ticker '^IXIC'` (오프라인 확인은 `--demo`)")


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
    st.subheader("데이터 원본 / 방법론")
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
    data_in = ui.data_section(defaults)
    ticker, years = data_in.ticker, data_in.years
    market = _load(ticker, years, json.dumps(list(defaults.exogenous)), data_in.source,
                   data_in.key, _overrides=data_in.overrides)
    for level, message in data_in.notes:
        {"fail": st.error, "warn": st.warning, "info": st.info}.get(level, st.info)(message)
    if market.empty:
        st.error(f"`{ticker}` 데이터를 가져오지 못했습니다. Manual Upload 를 쓰는 중이라면 컬럼 매핑을, "
                 "Auto Download 라면 티커를 확인하세요. 네트워크가 막힌 환경이라면 사이드바의 "
                 "**오프라인 데모 데이터**로 UI/계산을 먼저 확인할 수 있습니다.")
        st.stop()

    data_id = _data_id(market, data_in.key)
    features, distribution = ui.feature_section(defaults)
    params = ui.apply(defaults, ticker=ticker, years=years, features=features,
                      distribution=distribution, similarity=defaults.similarity,
                      forward=defaults.forward, validation=defaults.validation)
    signature = _feature_signature(params, data_id)
    fs = _features(market, signature)

    mode, sim, conditions = ui.match_section(defaults, fs)
    fwd_params = ui.forward_section(defaults)
    val_params = ui.validation_section(defaults, market.calendar)
    shade, log_scale, show_sma = ui.chart_section(params)
    params = ui.apply(params, ticker=ticker, years=years, features=features,
                      distribution=distribution, similarity=sim, forward=fwd_params,
                      validation=val_params)
    signature = _feature_signature(params, data_id)

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
                       shade_horizon=shade, log_scale=log_scale, show_sma=show_sma, source=data_in.source)

    max_h = int(max(params.forward.horizons))
    if mode == "similarity":
        scored, info = similarity.candidate_scores(fs.values, anchor, params.similarity.weights,
                                                   params.similarity, valid=valid, max_horizon=max_h)
        matches = similarity.decluster(scored, market.calendar, params.similarity.min_gap,
                                       pick=params.similarity.episode_pick,
                                       top_n=params.similarity.top_n)
    else:
        scored, info = matching.strict_candidates(fs.values, conditions, anchor, params.similarity,
                                                  weights=params.similarity.weights,
                                                  max_horizon=max_h, valid=valid)
        matches = similarity.decluster(scored.fillna({"score": 0.0}), market.calendar,
                                       params.similarity.min_gap,
                                       pick=params.similarity.episode_pick if params.similarity.weights else "first",
                                       top_n=None)
        matches = matches.sort_values("score", ascending=False).head(params.similarity.top_n)

    table = viz.build_match_table(matches, fs, market.prices["close"], params.forward.horizons,
                                  keys=info.used_keys or list(fs.values.columns)[:6])
    results = analyze(market.prices["close"], matches, params.forward,
                      baseline_mask=valid, min_gap=params.similarity.min_gap,
                      index=market.calendar, episode_pick=params.similarity.episode_pick)

    reports = _quality(market, signature)
    quality_banner(reports)

    tabs = st.tabs(["① 현재 시장 상태", "② 과거 유사 국면", "③ Forward Return",
                    "④ 계산 감사", "⑤ 통계적 검증", "⑥ 데이터 품질", "⑦ 원본 / 방법론"])
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
        audit_tab(market, fs, params, anchor, scored, matches, mode)
    with tabs[4]:
        validation_tab(market, fs, params, params.similarity.weights, signature)
    with tabs[5]:
        quality_tab(market, fs, params, reports)
    with tabs[6]:
        data_tab(market, fs, params)


if __name__ == "__main__":
    main()
