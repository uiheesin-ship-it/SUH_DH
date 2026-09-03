"""Orchestrate a full flat-base scan (spec §2-§13, §17).

Pipeline per ticker (all wrapped so one bad name never aborts the scan):
  1. Fetch ~2y adjusted OHLCV (reuses app.base.data.fetch_bars).
  2. Liquidity gate: price >= min_price, 20d avg $-volume >= min.
  3. Evaluate all 8 base periods; keep those meeting the §5 thresholds.
  4. For each qualifying period compute prior-trend tag (§7) + historical activity
     (§9/§10) on strictly pre-base data, then §8 acceptance. Choose the best
     accepted period (highest Flatness Score); if none is accepted, keep the
     top-scoring qualifying period flagged not-accepted with reasons.
  5. Emit a record with every §13 column. Flatness Score never sees prior
     returns / historical activity / volume / RS / sector.
  6. After the loop: RS percentile (12m return rank) as a DISPLAY-ONLY column.

Look-ahead safety: the base window is closes[start:] and every historical
metric uses only closes[:start], so the two never overlap.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import numpy as np

from ..base import data as basedata
from ..base import metrics as bmetrics
from . import activity, bases, setup as setup_mod, trend_tag
from .config import load as load_config


def _avg_dollar_volume_20d(close, volume) -> float | None:
    if len(close) < 20 or len(volume) < 20:
        return None
    c = np.asarray(close[-20:], dtype=float)
    v = np.asarray(volume[-20:], dtype=float)
    dv = (c * v)[np.isfinite(c * v)]
    return float(dv.mean()) if dv.size else None


def _security_type(cand: dict) -> str:
    if cand.get("is_etf"):
        return "ETF"
    if cand.get("is_reit"):
        return "REIT"
    if (cand.get("country") or "USA") != "USA":
        return "ADR"
    return "Common Stock"


def _evaluate_candidate_base(base: dict, closes: list, cfg: dict) -> dict:
    """Attach prior-trend tag, historical activity and §8 acceptance to one base."""
    start = base["base_start_idx"]
    trend = trend_tag.prior_trend(closes, start, cfg)
    hist = activity.historical_activity(closes, start, base["close_band"], cfg)
    accepted, reasons = trend_tag.acceptance_check(base, trend["base_category"], hist, cfg)
    return {"trend": trend, "hist": hist, "accepted": accepted, "reasons": reasons}


def _build_record(cand: dict, bars: dict, cfg: dict, spy: dict | None = None) -> dict | None:
    close = bars.get("close") or []
    high = bars.get("high") or []
    low = bars.get("low") or []
    volume = bars.get("volume") or []
    dates = bars.get("dates") or []

    if len(close) < int(cfg["min_history_days"]):
        return {"_insufficient": True, "ticker": cand["ticker"],
                "company_name": cand.get("company")}
    price = close[-1]
    if not price or price < float(cfg["min_price"]):
        return None
    if len(volume) and volume[-1] <= 0:
        return None
    adv20 = _avg_dollar_volume_20d(close, volume)
    if adv20 is not None and adv20 < float(cfg["min_avg_dollar_volume_20d"]):
        return None

    qualifying = bases.select_bases(close, high, low, price, cfg)
    if not qualifying:
        return None   # not a flat base right now — not shown in the flat list

    # Enrich each qualifying period; prefer the best *accepted* one (spec §8).
    enriched = []
    for b in qualifying:
        meta = _evaluate_candidate_base(b, close, cfg)
        enriched.append((b, meta))
    accepted = [(b, m) for b, m in enriched if m["accepted"]]
    if accepted:
        best, bmeta = accepted[0]        # already score-sorted
        accepted_flag = True
    else:
        best, bmeta = enriched[0]
        accepted_flag = False

    start = best["base_start_idx"]
    base_start_date = dates[start] if 0 <= start < len(dates) else None
    base_end_date = dates[-1] if dates else None
    hist = bmeta["hist"]
    trend = bmeta["trend"]

    # Reasons: acceptance failures + chronic-low-vol / activity fail (spec §13).
    reasons = list(bmeta["reasons"])
    if hist["chronically_low_vol"]:
        reasons.append("만성 저변동성")
    if not hist["historical_activity_pass"]:
        reasons.append("과거활동성 미달")

    # Top runner-up periods (spec §17) — compact view.
    top_n = int(cfg.get("top_candidates", 3))
    candidates_view = [{
        "base_days": b["base_days"], "flatness_score": b["flatness_score"],
        "flatness_grade": b["flatness_grade"], "base_status": b["base_status"],
        "accepted": m["accepted"],
    } for b, m in enriched[:top_n]]

    ret_2w = bmetrics.pct_return(close, bmetrics.TRADING_DAYS_2W)
    ret_1m = bmetrics.pct_return(close, bmetrics.TRADING_DAYS_1M)
    ret_3m = bmetrics.pct_return(close, bmetrics.TRADING_DAYS_3M)
    ret_6m = bmetrics.pct_return(close, bmetrics.TRADING_DAYS_6M)
    ret_12m = bmetrics.pct_return(close, bmetrics.TRADING_DAYS_12M)
    # Beta vs SPY — DISPLAY ONLY, never enters the Flatness Score (same policy as
    # sector / RS%). A flat base can be low- or high-beta; we just surface it.
    beta_val = bmetrics.beta(close, spy["close"]) if spy and spy.get("close") else None

    # Moving-average / trend "Setup" context — a SEPARATE dimension from the
    # Flatness Score (§1). Grades whether the tight base rides rising MAs near
    # highs (continuation) or reclaims its MAs off a bottom (turnaround), so a
    # flat-but-trendless base can be filtered out / ranked below real setups.
    setup = setup_mod.compute_setup(
        close, start, best.get("base_low_q10"), best.get("base_high_q90"),
        price, best.get("current_position"), cfg)
    flat_s = best["flatness_score"] or 0
    setup_s = setup.get("setup_score")
    composite = round(0.5 * flat_s + 0.5 * setup_s, 1) if setup_s is not None else flat_s

    rec = {
        "ticker": cand["ticker"],
        "company_name": cand.get("company"),
        "security_type": _security_type(cand),
        "sector": cand.get("sector"),
        "industry": cand.get("industry"),
        "is_reit": bool(cand.get("is_reit")),
        "is_etf": bool(cand.get("is_etf")),
        "current_price": round(price, 4),
        "market_cap": cand.get("market_cap"),
        "avg_dollar_volume_20d": round(adv20, 0) if adv20 is not None else None,
        # --- base window ---
        "base_start_date": base_start_date,
        "base_end_date": base_end_date,
        "base_days": best["base_days"],
        # --- flatness metrics (§4) ---
        "close_band": best["close_band"],
        "raw_high_low_range": best["raw_high_low_range"],
        "base_drift": best["base_drift"],
        "containment_ratio": best["containment_ratio"],
        "center_shift": best["center_shift"],
        "outlier_days": best["outlier_days"],
        "outlier_ratio": best["outlier_ratio"],
        "base_daily_vol": best.get("base_daily_vol"),
        "current_position": best["current_position"],
        "base_low_q10": best["base_low_q10"],
        "base_high_q90": best["base_high_q90"],
        "base_median": best["base_median"],
        # --- score (§11) ---
        "range_score": best["range_score"],
        "slope_score": best["slope_score"],
        "containment_score": best["containment_score"],
        "center_score": best["center_score"],
        "outlier_score": best["outlier_score"],
        "flatness_score": best["flatness_score"],
        "flatness_grade": best["flatness_grade"],
        # --- prior trend tag (§7) ---
        "prior_60d_return": trend["prior_60d_return"],
        "prior_120d_return": trend["prior_120d_return"],
        "representative_prior_return": trend["representative_prior_return"],
        "base_category": trend["base_category"],
        # --- historical activity (§9/§10) ---
        "prior_120_close_band": hist["prior_120_close_band"],
        "prior_252_close_band": hist["prior_252_close_band"],
        "max_abs_20d_return": hist["max_abs_20d_return"],
        "max_abs_60d_return": hist["max_abs_60d_return"],
        "base_distinctness": hist["base_distinctness"],
        "historical_activity_pass": hist["historical_activity_pass"],
        "chronically_low_vol": hist["chronically_low_vol"],
        "historical_activity_insufficient": hist["historical_activity_insufficient"],
        # --- status / acceptance ---
        "base_status": best["base_status"],
        "accepted": accepted_flag,
        "exclude_reason": ", ".join(reasons) if reasons else None,
        # --- moving-average / trend Setup (SEPARATE from flatness score) ---
        **setup,
        "composite_score": composite,
        # --- display-only extras (NOT in flatness score) ---
        "ret_2w": ret_2w, "ret_1m": ret_1m, "ret_3m": ret_3m,
        "ret_6m": ret_6m, "ret_12m": ret_12m,
        "beta": beta_val,        # vs SPY (252d) — display only
        "adr_pct": bmetrics.adr_pct(high, low, 20),  # avg daily range %, display only
        "rs_percentile": None,   # filled after the loop (= 12m percentile)
        # per-period RS percentiles (filled after the loop)
        "rs_pct_2w": None, "rs_pct_1m": None, "rs_pct_3m": None,
        "rs_pct_6m": None, "rs_pct_12m": None,
        "candidate_periods": candidates_view,
        # chart series key
        "yahoo": cand["ticker"],
    }
    return rec


def _assign_rs(records: list[dict]) -> None:
    """Per-period return percentiles across the surviving universe (display only):
    2주/1개월/3개월/6개월/12개월. rs_percentile stays = the 12-month percentile
    (its long-standing meaning, used by filters/sorts elsewhere)."""
    def _rank_pct(ret_key: str, pct_key: str) -> None:
        vals = [(r, r.get(ret_key)) for r in records if r.get(ret_key) is not None]
        n = len(vals)
        if n <= 1:
            for r in records:
                r[pct_key] = 50 if r.get(ret_key) is not None else None
            return
        for rank, (r, _v) in enumerate(sorted(vals, key=lambda t: t[1])):
            r[pct_key] = round(100.0 * rank / (n - 1))

    _rank_pct("ret_2w", "rs_pct_2w")
    _rank_pct("ret_1m", "rs_pct_1m")
    _rank_pct("ret_3m", "rs_pct_3m")
    _rank_pct("ret_6m", "rs_pct_6m")
    _rank_pct("ret_12m", "rs_pct_12m")
    for r in records:
        r["rs_percentile"] = r.get("rs_pct_12m")


def run_scan(cfg: dict | None = None, limit: int | None = None,
             progress: bool = False) -> dict:
    from . import universe

    cfg = cfg or load_config()
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    candidates = universe.get_candidates(cfg)
    if limit:
        candidates = candidates[:limit]

    # SPY once, for the display-only beta column (not in the Flatness Score).
    try:
        spy = basedata.fetch_bars("SPY")
        if not spy.get("close"):
            spy = None
    except Exception:
        spy = None

    records: list[dict] = []
    failures = 0
    insufficient = 0
    demo = os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")
    for i, cand in enumerate(candidates):
        try:
            bars = basedata.fetch_bars(cand["ticker"])
            rec = _build_record(cand, bars, cfg, spy)
            if rec is None:
                pass
            elif rec.get("_insufficient"):
                insufficient += 1
            else:
                records.append(rec)
        except Exception:
            failures += 1
        if not demo:
            time.sleep(0.2)
        if progress and (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(candidates)} scanned, {len(records)} flat bases")

    _assign_rs(records)
    # Default order: Flatness Score desc (spec §13).
    records.sort(key=lambda r: (r.get("flatness_score") or 0), reverse=True)

    return {
        "built": built,
        "count": len(records),
        "universe_size": len(candidates),
        "failures": failures,
        "insufficient": insufficient,
        "demo": demo,
        "market": "US",
        "stocks": records,
    }
