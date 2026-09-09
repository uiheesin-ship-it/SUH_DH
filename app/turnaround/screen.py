"""Orchestrate a full bottom-base scan.

Pipeline per ticker (every step wrapped so one bad name never aborts a scan):

  1. Fetch ~2y adjusted OHLCV (shares app.base.data.fetch_bars and its cache
     with the base and flat screeners).
  2. Liquidity gate — price, 20-day dollar volume.
  3. Bottom gate — far enough below the 52-week high, not already doubled off
     the low, no fresh 52-week low. This is the base screener's trend template
     turned around: there it keeps names near their highs, here it requires the
     damage that makes a turnaround possible in the first place.
  4. Trough anchor + candidate base windows (bases.select_windows).
  5. Score every surviving window on all four axes and keep the best. Scoring
     each window rather than picking one up front is what lets the sweep
     self-correct: an over-long window that swallowed part of the decline loses
     on the right-edge axis to the correct shorter one.
  6. Drop the ticker if its best window is extended — past the point of entry.
  7. After the loop: RS percentiles (display only) and, for the top names, the
     next-earnings D-day column.

Look-ahead safety: every window ends at the last bar and every quality metric
reads from the trough forward, so no metric can see data it would not have had.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import numpy as np

from ..base import data as basedata
from ..base import metrics as bmetrics
from . import bases, edge as edge_mod, quality as quality_mod, scoring
from . import setup as setup_mod, triggers as trig_mod
from .config import load as load_config


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _fetch_bars(ticker: str) -> dict:
    if _demo():
        from . import demo
        return demo.bars(ticker)
    return basedata.fetch_bars(ticker)


def _avg_dollar_volume_20d(close, volume) -> float | None:
    if len(close) < 20 or len(volume) < 20:
        return None
    c = np.asarray(close[-20:], dtype=float)
    v = np.asarray(volume[-20:], dtype=float)
    dv = (c * v)[np.isfinite(c * v)]
    return float(dv.mean()) if dv.size else None


def bottom_gate(close, high, low, cfg: dict) -> tuple[bool, dict]:
    """Has this name actually fallen, and has it stopped falling?

    The drawdown is measured against the ``high_lookback`` peak, NOT the
    52-week high. A base that has been building for a year pushes the old peak
    out of a 252-day window, so the 52-week high ends up being a high made
    inside the base itself — off_52w_high collapses toward zero and the gate
    would reject exactly the long, well-formed bottom bases it exists to find.
    The 52-week figures are still reported, for display and for the fresh-low
    test where a one-year window is the right horizon.

    Returns (passed, metrics) so the metrics are available for display even when
    the gate fails (useful when tuning thresholds against a known ticker).
    """
    b = cfg["bottom"]
    price = close[-1]
    high52 = bmetrics.high_52w(high)
    low52 = bmetrics.low_52w(low)
    peak = bmetrics.high_52w(high, window=int(b.get("high_lookback", 756)))

    off_high = (1.0 - price / peak) if (peak and peak > 0) else None
    off_low = (price / low52 - 1.0) if (low52 and low52 > 0) else None

    # Is the decline still live? Comparing the recent low against the 52-week low
    # does not answer that: a flat base sitting on its lows re-touches the
    # 52-week low every other week, and would be flagged forever. The question
    # is whether the stock is making a NEW low, so compare the recent window
    # against the low of everything before it.
    nd = int(b["no_new_low_days"])
    tol = float(b.get("new_low_tolerance", 0.01))
    recent_low = prior_low = None
    if len(low) >= nd + 20:
        seg = np.asarray(low[-nd:], dtype=float)
        seg = seg[np.isfinite(seg)]
        recent_low = float(seg.min()) if seg.size else None
        prev = np.asarray(low[-bmetrics.WEEK52:-nd], dtype=float)
        prev = prev[np.isfinite(prev)]
        prior_low = float(prev.min()) if prev.size else None
    fresh_low = bool(recent_low is not None and prior_low is not None
                     and recent_low < prior_low * (1.0 - tol))

    metrics = {
        "high_52w": high52, "low_52w": low52,
        "peak_high": peak,
        "off_peak_high": round(off_high, 4) if off_high is not None else None,
        "off_52w_high": (round(1.0 - price / high52, 4)
                         if (high52 and high52 > 0) else None),
        "off_52w_low": round(off_low, 4) if off_low is not None else None,
        "recent_low": recent_low,
        "prior_low": prior_low,
        "fresh_52w_low": fresh_low,
    }
    ok = (
        off_high is not None and off_high >= float(b["min_off_52w_high"])
        and off_low is not None and off_low <= float(b["max_off_52w_low"])
        and not fresh_low
    )
    return ok, metrics


def _score_window(close, high, low, volume, dates, window, cfg, bench_closes,
                  earnings_dates=None, sma50=None) -> dict:
    q = quality_mod.compute(close, high, low, volume, window, cfg)
    e = edge_mod.compute(close, high, low, window, cfg, sma50)
    s = setup_mod.compute(close, window, cfg, bench_closes)
    t = trig_mod.compute(close, high, low, volume, dates, window, cfg,
                         bench_closes, earnings_dates)
    total = scoring.total(q, e, s, t)
    return {"window": window, "quality": q, "edge": e, "setup": s,
            "trigger": t, "total": total}


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

    passed, bottom = bottom_gate(close, high, low, cfg)
    if not passed:
        return None

    windows = bases.select_windows(close, high, low, cfg)
    if not windows:
        return None

    bench_closes = (spy or {}).get("close") if spy else None
    sma50 = bmetrics.sma(close, 50)
    scored = [_score_window(close, high, low, volume, dates, w, cfg, bench_closes,
                            sma50=sma50)
              for w in windows]
    # An extended window is past the entry this screener looks for. Drop those
    # windows rather than the ticker: a name can be extended against a short
    # base while still building a longer one, and that longer base is valid.
    live = [s for s in scored if not s["edge"]["extended"]]
    if not live:
        return None
    best = max(live, key=lambda s: s["total"])

    w = best["window"]
    start = w["base_start_idx"]
    total = best["total"]

    rec = {
        "ticker": cand["ticker"],
        "company_name": cand.get("company"),
        "sector": cand.get("sector"),
        "industry": cand.get("industry"),
        "current_price": round(price, 4),
        "market_cap": cand.get("market_cap"),
        "avg_dollar_volume_20d": round(adv20, 0) if adv20 is not None else None,
        # --- base window ---
        "base_start_date": dates[start] if 0 <= start < len(dates) else None,
        "base_end_date": dates[-1] if dates else None,
        "trough_date": (dates[w["global_trough_idx"]]
                        if 0 <= w["global_trough_idx"] < len(dates) else None),
        "base_low_date": (dates[w["base_low_idx"]]
                          if 0 <= w["base_low_idx"] < len(dates) else None),
        "base_days": w["base_days"],
        "base_high": w["base_high"],
        "base_low": w["base_low"],
        "base_depth": w["base_depth"],
        "base_drift": w["base_drift"],
        "base_median": w["base_median"],
        "base_low_q10": w["base_low_q10"],
        "base_high_q90": w["base_high_q90"],
        "base_recovery": w["base_recovery"],
        "low_position": w["low_position"],
        "low_offset": w["low_offset"],
        "base_daily_vol": w["base_daily_vol"],
        "front_third_drift": w["front_third_drift"],
        # --- axes ---
        **best["quality"],
        **best["edge"],
        **best["setup"],
        **best["trigger"],
        # --- bottom gate context ---
        **bottom,
        # --- totals ---
        "turnaround_score": total,
        "grade": scoring.grade(total, cfg),
        "stage": scoring.stage(best["edge"], best["trigger"]),
        "window_count": len(live),
        # --- display-only ---
        "ret_1m": bmetrics.pct_return(close, bmetrics.TRADING_DAYS_1M),
        "ret_3m": bmetrics.pct_return(close, bmetrics.TRADING_DAYS_3M),
        "ret_6m": bmetrics.pct_return(close, bmetrics.TRADING_DAYS_6M),
        "ret_12m": bmetrics.pct_return(close, bmetrics.TRADING_DAYS_12M),
        "adr_pct": bmetrics.adr_pct(high, low, 20),
        "rs_percentile": None,          # filled after the loop
        "next_earnings_date": None,     # filled after the loop
        "days_to_earnings": None,
        "recent_beats": None,
        "yahoo": cand["ticker"],
    }
    return rec


def _assign_rs(records: list[dict]) -> None:
    """12-month return percentile across the surviving universe. Display only —
    a bottom base is in the bottom decile of any market-wide RS ranking by
    construction, so this never gates or scores anything here."""
    vals = [(r, r.get("ret_12m")) for r in records if r.get("ret_12m") is not None]
    n = len(vals)
    if n <= 1:
        for r in records:
            r["rs_percentile"] = 50 if r.get("ret_12m") is not None else None
        return
    for rank, (r, _v) in enumerate(sorted(vals, key=lambda t: t[1])):
        r["rs_percentile"] = round(100.0 * rank / (n - 1))


def _attach_earnings(records: list[dict], cfg: dict) -> None:
    """Next-earnings D-day for the top names.

    The pairing this screener is built around — a bottom base at its right edge
    with a report due — needs the date, not the numbers. Costs one cached call
    per name, so it is capped to the top ``max_lookup`` by score.
    """
    ecfg = cfg.get("earnings") or {}
    if not ecfg.get("enabled", True):
        return
    from .. import earnings as earnings_mod

    today = datetime.now(timezone.utc).date()
    for rec in records[:int(ecfg.get("max_lookup", 120))]:
        try:
            data = earnings_mod.get_earnings(rec["ticker"], limit=8)
        except Exception:
            continue
        quarters = data.get("quarters") or []
        upcoming = sorted(q["date"] for q in quarters if q.get("upcoming"))
        if upcoming:
            rec["next_earnings_date"] = upcoming[0]
            try:
                y, m, d = (int(x) for x in upcoming[0].split("-"))
                rec["days_to_earnings"] = (datetime(y, m, d).date() - today).days
            except Exception:
                pass
        reported = [q for q in quarters if q.get("reported")][:4]
        if reported:
            rec["recent_beats"] = sum(1 for q in reported if q.get("result") == "beat")


def run_scan(cfg: dict | None = None, limit: int | None = None,
             progress: bool = False) -> dict:
    from . import universe

    cfg = cfg or load_config()
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    candidates = universe.get_candidates(cfg)
    if limit:
        candidates = candidates[:limit]

    try:
        spy = _fetch_bars("SPY")
        if not spy.get("close"):
            spy = None
    except Exception:
        spy = None

    records: list[dict] = []
    failures = 0
    insufficient = 0
    demo = _demo()
    for i, cand in enumerate(candidates):
        try:
            bars = _fetch_bars(cand["ticker"])
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
            print(f"  ... {i + 1}/{len(candidates)} scanned, {len(records)} bottom bases")

    _assign_rs(records)
    records.sort(key=lambda r: (r.get("turnaround_score") or 0), reverse=True)
    _attach_earnings(records, cfg)

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
