"""Calculation audit — 한 match 날짜에 대해 숫자가 어떻게 나왔는지 전부 펼쳐 보기.

Nothing here computes anything new: it re-uses the very functions the analysis
runs on (``normalize_asof``, the distribution-day flags, the forward-return
frames) and lays out every intermediate value so a human — or a unit test —
can re-derive the final similarity score by hand:

    raw feature → (raw − center)/scale → z 차이 → 가중치 → 기여도 → 거리 → 점수

Each section is a small DataFrame so the Streamlit page can render it directly
and ``tests/test_regime_audit.py`` can recompute the same numbers from the raw
OHLCV with plain pandas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import similarity
from .features.distribution import flags as dd_flags
from .forward import forward_max_drawdown, forward_returns


@dataclass
class AuditResult:
    date: pd.Timestamp
    anchor: pd.Timestamp
    ohlcv: pd.DataFrame
    trend: pd.DataFrame
    distribution: pd.DataFrame
    dd_days: pd.DataFrame
    features: pd.DataFrame
    distance: dict
    declustering: dict
    forward: pd.DataFrame
    notes: list[str] = field(default_factory=list)


def _row_frame(market, date: pd.Timestamp, span: int = 1) -> pd.DataFrame:
    idx = pd.DatetimeIndex(market.prices.index)
    pos = int(idx.get_loc(date))
    lo, hi = max(0, pos - span), min(len(idx) - 1, pos + span)
    out = market.prices.iloc[lo:hi + 1].copy()
    out.insert(0, "구분", ["전일", "당일", "익일"][:len(out)] if lo == pos - span
               else ["당일", "익일"][:len(out)])
    return out


def trend_breakdown(market, fs, params, date: pd.Timestamp) -> pd.DataFrame:
    """SMA 값과 이격률을 원자료에서 다시 계산해 feature 값과 나란히 둔다."""
    close = market.prices["close"].astype(float)
    rows = []
    for w in sorted(int(x) for x in params.features.sma_windows):
        window = close.loc[:date].tail(w)
        manual = float(window.mean()) if len(window) == w else np.nan
        stored = float(fs.aux.loc[date, f"sma{w}"]) if f"sma{w}" in fs.aux.columns else np.nan
        gap = (float(close.loc[date]) / manual - 1.0) * 100.0 if manual else np.nan
        rows.append({
            "이동평균": f"SMA{w}",
            "표본 수": int(len(window)),
            f"재계산 SMA": manual,
            "저장된 SMA": stored,
            "종가": float(close.loc[date]),
            "이격률 재계산 (%)": gap,
            "이격률 feature (%)": float(fs.values.loc[date, f"px_vs_sma{w}"])
            if f"px_vs_sma{w}" in fs.values.columns else np.nan,
            "종가 > SMA": bool(close.loc[date] > manual) if np.isfinite(manual) else None,
        })
    return pd.DataFrame(rows)


def distribution_breakdown(market, params, date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """세 조건을 값·임계값·통과 여부로 펼치고, lookback 안의 분산일을 나열한다."""
    dp = params.distribution
    f = dd_flags(market, params)
    px = market.prices
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.get_loc(date))
    prev = idx[pos - 1] if pos > 0 else None

    ret = float(f.loc[date, "ret_pct"])
    vol_ratio = float(f.loc[date, "vol_ratio"]) if np.isfinite(f.loc[date, "vol_ratio"]) else np.nan
    clv = float(f.loc[date, "clv"])
    high, low, close = (float(px.loc[date, k]) for k in ("high", "low", "close"))

    cond = pd.DataFrame([
        {"조건": "① 일간 수익률", "계산식": "Close/전일Close − 1",
         "값": ret, "임계값": -float(dp.drop_pct), "비교": "≤",
         "통과": bool(ret <= -float(dp.drop_pct))},
        {"조건": "② 거래량 증가", "계산식": "Volume / 전일Volume",
         "값": vol_ratio, "임계값": 1.0 + float(dp.volume_bump_pct) / 100.0, "비교": "≥",
         "통과": bool(np.isfinite(vol_ratio) and vol_ratio >= 1.0 + float(dp.volume_bump_pct) / 100.0)},
        {"조건": "③ CLV", "계산식": f"({close:.2f}−{low:.2f})/({high:.2f}−{low:.2f})",
         "값": clv, "임계값": float(dp.clv_max), "비교": "≤",
         "통과": bool(clv <= float(dp.clv_max))},
    ])
    cond.attrs["prev_date"] = None if prev is None else str(prev.date())

    window = f.iloc[max(0, pos - int(dp.lookback) + 1): pos + 1]
    hits = window[window["dd_flag"].fillna(False)]
    dd_days = hits[["ret_pct", "vol_ratio", "clv"]].copy()
    dd_days.columns = ["일간 수익률 (%)", "거래량 배수", "CLV"]
    return cond, dd_days


def feature_breakdown(fs, params, anchor: pd.Timestamp, date: pd.Timestamp,
                      weights: dict[str, float]) -> tuple[pd.DataFrame, dict]:
    """raw → standardized → 차이 → 가중 기여도 → 거리 → 점수, 한 줄씩."""
    sp = params.similarity
    keys = [k for k, w in (weights or {}).items() if float(w) > 0 and k in fs.values.columns]
    z, info = similarity.normalize_asof(fs.values, anchor, keys, mode=sp.normalization,
                                        min_history=sp.min_history)
    used = list(info.used_keys)
    rows = []
    for k in keys:
        spec = fs.specs.get(k)
        raw = float(fs.values.loc[date, k]) if k in fs.values.columns else np.nan
        raw_anchor = float(fs.values.loc[anchor, k])
        if k in used:
            c, s = float(info.center[k]), float(info.scale[k])
            zi, za = float(z.loc[date, k]), float(z.loc[anchor, k])
            w = float(weights[k])
            diff = zi - za
            contrib = w * diff ** 2
        else:
            c = s = zi = za = diff = contrib = np.nan
            w = float(weights[k])
        rows.append({
            "feature": spec.label if spec else k,
            "key": k,
            "raw (과거일)": raw,
            "raw (기준일)": raw_anchor,
            "center": c, "scale": s,
            "z (과거일)": zi, "z (기준일)": za,
            "z 차이": diff,
            "weight": w,
            "가중 기여 w·Δz²": contrib,
            "사용": k in used,
        })
    table = pd.DataFrame(rows)
    w_sum = float(table.loc[table["사용"], "weight"].sum())
    contrib_sum = float(table["가중 기여 w·Δz²"].sum(skipna=True))
    distance = float(np.sqrt(contrib_sum / w_sum)) if w_sum > 0 else np.nan
    score = float(100.0 * np.exp(-0.5 * distance ** 2)) if np.isfinite(distance) else np.nan
    if len(table):
        table["기여 비중 (%)"] = table["가중 기여 w·Δz²"] / contrib_sum * 100.0 if contrib_sum else np.nan
        table = table.sort_values("가중 기여 w·Δz²", ascending=False)
    summary = {
        "사용 feature 수": int(table["사용"].sum()) if len(table) else 0,
        "가중치 합 Σw": w_sum,
        "가중 기여 합 Σw·Δz²": contrib_sum,
        "거리 d = √(Σw·Δz²/Σw)": distance,
        "점수 100·exp(−d²/2)": score,
        "제외된 feature": info.dropped_keys,
    }
    return table, summary


def declustering_breakdown(scored: pd.DataFrame, matches: pd.DataFrame,
                           index: pd.DatetimeIndex, params, date: pd.Timestamp) -> dict:
    """이 날짜가 후보였는지, 몇 등이었는지, de-clustering 후 살아남았는지."""
    sp = params.similarity
    out: dict = {"후보 여부": bool(date in scored.index),
                 "최종 선택": bool(matches is not None and date in matches.index),
                 "de-clustering 최소 간격": int(sp.min_gap),
                 "episode 대표 기준": "유사도 최고" if sp.episode_pick == "best" else "가장 먼저"}
    if date in scored.index:
        ranked = scored.sort_values("score", ascending=False)
        out["de-clustering 전 순위"] = int(ranked.index.get_loc(date)) + 1
        out["후보 총수"] = int(len(scored))
        out["점수"] = float(scored.loc[date, "score"])
    if matches is not None and len(matches) and date in scored.index:
        pos_of = pd.Series(np.arange(len(index)), index=index)
        p = int(pos_of.loc[date])
        near = [(d, int(abs(p - int(pos_of.loc[d]))), float(matches.loc[d, "score"]))
                for d in matches.index if abs(p - int(pos_of.loc[d])) < int(sp.min_gap) and d != date]
        if near and date not in matches.index:
            d0, gap, sc = sorted(near, key=lambda x: -x[2])[0]
            out["탈락 사유"] = (f"{d0.date()} (간격 {gap}거래일, 점수 {sc:.1f}) 와 같은 episode 로 묶여 "
                                f"대표 자리를 내줬습니다")
        elif date in matches.index:
            out["같은 episode 로 흡수한 이웃"] = ", ".join(
                f"{d.date()}(간격 {g})" for d, g, _ in sorted(near, key=lambda x: x[1])[:5]) or "없음"
    return out


def forward_breakdown(close: pd.Series, index: pd.DatetimeIndex, date: pd.Timestamp,
                      horizons) -> pd.DataFrame:
    """각 horizon 의 시작/종료 날짜와 가격, 그리고 그 둘로 만든 수익률."""
    fwd = forward_returns(close, horizons)
    mdd = forward_max_drawdown(close, horizons)
    pos_of = pd.Series(np.arange(len(index)), index=index)
    p = int(pos_of.loc[date])
    rows = []
    for h in (int(x) for x in horizons):
        end_pos = p + h
        end_date = index[end_pos] if end_pos < len(index) else None
        start_px = float(close.loc[date])
        end_px = float(close.iloc[end_pos]) if end_date is not None else np.nan
        manual = (end_px / start_px - 1.0) * 100.0 if end_date is not None else np.nan
        path = close.iloc[p:end_pos + 1] if end_date is not None else close.iloc[p:]
        trough = path.idxmin() if len(path) else None
        rows.append({
            "Horizon": f"+{h}일",
            "시작일": str(date.date()), "시작 종가": start_px,
            "종료일": "–" if end_date is None else str(end_date.date()),
            "종료 종가": end_px,
            "수익률 재계산 (%)": manual,
            "수익률 feature (%)": float(fwd.loc[date, f"fwd_{h}"]) if date in fwd.index else np.nan,
            "구간 최대낙폭 (%)": float(mdd.loc[date, f"mdd_{h}"]) if date in mdd.index else np.nan,
            "구간 최저 종가일": "–" if trough is None else str(pd.Timestamp(trough).date()),
        })
    return pd.DataFrame(rows)


def audit_match(market, fs, params, anchor, date, *, weights: dict[str, float] | None = None,
                scored: pd.DataFrame | None = None, matches: pd.DataFrame | None = None,
                horizons=None) -> AuditResult:
    """Everything behind one match date, in one object."""
    anchor = pd.Timestamp(anchor)
    date = pd.Timestamp(date)
    index = pd.DatetimeIndex(market.prices.index)
    weights = weights if weights is not None else dict(params.similarity.weights)
    horizons = list(horizons or params.forward.horizons)

    if scored is None:
        # 엔진과 같은 후보 조건(최근 구간 제외 등)을 적용해야 순위가 의미를 갖는다.
        scored, _ = similarity.candidate_scores(
            fs.values, anchor, weights, params.similarity, valid=fs.valid_mask(),
            max_horizon=int(max(horizons)) if horizons else 0)
    cond, dd_days = distribution_breakdown(market, params, date)
    features, summary = feature_breakdown(fs, params, anchor, date, weights)

    notes: list[str] = []
    if date not in index:
        notes.append("거래일이 아닌 날짜입니다.")
    if summary.get("제외된 feature"):
        notes.append("일부 feature 가 매칭에서 제외됐습니다: "
                     + ", ".join(f"{k}({v})" for k, v in summary["제외된 feature"].items()))
    if date in scored.index:
        stored = float(scored.loc[date, "distance"])
        if np.isfinite(stored) and np.isfinite(summary["거리 d = √(Σw·Δz²/Σw)"]):
            gap = abs(stored - summary["거리 d = √(Σw·Δz²/Σw)"])
            notes.append(f"엔진이 계산한 거리 {stored:.6f} vs 위 표를 합산한 거리 "
                         f"{summary['거리 d = √(Σw·Δz²/Σw)']:.6f} (차이 {gap:.2e})")

    return AuditResult(
        date=date, anchor=anchor,
        ohlcv=_row_frame(market, date),
        trend=trend_breakdown(market, fs, params, date),
        distribution=cond, dd_days=dd_days,
        features=features, distance=summary,
        declustering=declustering_breakdown(scored, matches, index, params, date),
        forward=forward_breakdown(market.prices["close"], index, date, horizons),
        notes=notes,
    )
