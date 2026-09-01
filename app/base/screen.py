"""Orchestrate a full base scan: universe -> per-ticker metrics -> RS -> score.

Pipeline
  1. Candidate universe (Finviz pre-filter, or demo).
  2. Benchmarks + sector ETFs fetched once.
  3. Per ticker: 2y adjusted OHLCV -> SMAs, returns, 52w, ATR, base, VCP,
     volume dry-up, RS line, sector action. Liquidity gate applied here.
  4. RS percentiles assigned across the surviving universe.
  5. Trend template (needs RS percentile) + weighted scoring + alerts.
  6. Sorted watchlist payload for the dashboard / static build.

Everything is wrapped so one bad ticker (NaN, halted, too-new) is skipped, never
fatal. Timestamps use datetime here (this runs in the app/build, not a workflow
script), which is fine.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import numpy as np

from . import data, detect, inbase, metrics, rs, scoring, sector
from .config import load as load_config


def _daily_range_pct(high, low, close) -> list[float]:
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        dr = np.where(c != 0, (h - l) / c, np.nan)
    return [float(x) if np.isfinite(x) else 0.0 for x in dr]


def _avg_dollar_volume_20d(close, volume) -> float | None:
    if len(close) < 20:
        return None
    c = np.asarray(close[-20:], dtype=float)
    v = np.asarray(volume[-20:], dtype=float)
    dv = c * v
    dv = dv[np.isfinite(dv)]
    return float(dv.mean()) if dv.size else None


def _build_record(cand: dict, bars: dict, benches: dict, cfg: dict,
                  sector_map: dict, spy_ret_3m: float | None) -> tuple[dict | None, str | None]:
    """Return (record, None) on success, or (None, drop_reason) so run_scan can
    report exactly why a candidate was dropped instead of it vanishing silently."""
    close = bars.get("close") or []
    high = bars.get("high") or []
    low = bars.get("low") or []
    volume = bars.get("volume") or []
    dates = bars.get("dates") or []

    if not close:
        return None, "no_bars"
    ipo_cfg = cfg.get("ipo") or {}
    ipo_enabled = bool(ipo_cfg.get("enabled"))
    # IPO mode lowers the hard history gate (a recent listing can't have 200
    # bars). Names with fewer than short_history_threshold bars are evaluated in
    # the adapted "short-history" trend-template mode below.
    min_hist = int(ipo_cfg.get("min_history_days", 40)) if ipo_enabled else int(cfg["min_history_days"])
    if len(close) < min_hist:
        return None, f"history<{min_hist}d({len(close)})"
    short_history = bool(ipo_enabled and len(close) < int(ipo_cfg.get("short_history_threshold", 200)))
    price = close[-1]
    if not price or price < float(cfg["min_price"]):
        return None, f"price<${cfg['min_price']}"
    if len(volume) and volume[-1] <= 0:
        return None, "last_volume<=0"
    adv20 = _avg_dollar_volume_20d(close, volume)
    if adv20 is not None and adv20 < float(cfg["min_avg_dollar_volume_20d"]):
        return None, f"dollar_vol<${int(float(cfg['min_avg_dollar_volume_20d'])/1e6)}M"

    # --- moving averages / structure ---
    sma50 = metrics.sma(close, 50)
    sma150 = metrics.sma(close, 150)
    sma200 = metrics.sma(close, 200)
    sma200_series = metrics.sma_series(close, 200)
    sma200_20 = metrics.value_n_days_ago(sma200_series, 20)
    sma50_series = metrics.sma_series(close, 50)
    sma50_20 = metrics.value_n_days_ago(sma50_series, 20)
    high52 = metrics.high_52w(high)
    low52 = metrics.low_52w(low)

    ret_3m = metrics.pct_return(close, metrics.TRADING_DAYS_3M)
    ret_6m = metrics.pct_return(close, metrics.TRADING_DAYS_6M)
    ret_12m = metrics.pct_return(close, metrics.TRADING_DAYS_12M)

    # --- base / pivot / vcp / volatility / volume ---
    atr_len = int(cfg["volatility"]["atr_length"])
    atr_vals = metrics.atr_series(high, low, close, atr_len)
    atr10 = metrics.atr_last(high, low, close, 10)
    atr50 = metrics.atr_last(high, low, close, 50)
    hl = (np.asarray(high, dtype=float) - np.asarray(low, dtype=float))
    recent_range10 = float(hl[-10:].mean()) if len(hl) >= 10 else None
    recent_range50 = float(hl[-50:].mean()) if len(hl) >= 50 else None
    dr_pct = _daily_range_pct(high, low, close)

    base = detect.detect_base(high, low, close, dates, cfg)

    # Drop dead / deal-pinned names: if the base window's average |daily return|
    # is essentially flat, the price is pinned (e.g. M&A quote at the deal value)
    # — not a tradable consolidation. Mirrors the flat screener's dead-base gate.
    min_dv = float(cfg.get("min_base_daily_vol", 0.0) or 0.0)
    if min_dv > 0 and base.get("base_detected"):
        L = base.get("base_length_days") or 0
        win_c = close[-int(L):] if L else close
        base_dv = metrics.mean_abs_daily_return(win_c)
        if base_dv is not None and base_dv < min_dv:
            return None, "dead_pinned(base_vol<0.5%)"

    vol = detect.volume_dry_up(close, volume, base, cfg)
    vol50 = vol["avg_volume_50d"]
    pivot = detect.pivot_analysis(price, base, high, close, volume, vol50, cfg)
    vcp = detect.vcp_structure(high, low, base, cfg)
    volat = detect.volatility_contraction(
        atr_vals, dr_pct, base, cfg, atr10, atr50, recent_range10, recent_range50)

    # --- prior uptrend: price_20d_ago / price_120d_ago - 1 ---
    prior_ret = None
    if len(close) >= 121:
        a = close[-21]
        b = close[-121]
        if b:
            prior_ret = round(a / b - 1.0, 4)
    prior_pass = bool(prior_ret is not None and prior_ret >= float(cfg["prior_uptrend"]["min_return"]))

    # --- 50-day-line distance ---
    dist_sma50 = round((price - sma50) / sma50, 4) if sma50 else None
    sma50_pass = bool(
        sma50 and float(cfg["sma50"]["min_ratio"]) * sma50 <= price <= float(cfg["sma50"]["max_ratio"]) * sma50
    )

    # --- RS line vs SPY / QQQ ---
    near_ratio = float(cfg["rs_line"]["near_high_ratio"])
    rs_spy_near = rs_qqq_near = None
    rs_vs_spy_3m = rs_vs_qqq_3m = None
    spy = benches.get("SPY")
    qqq = benches.get("QQQ")
    beta_val = metrics.beta(close, spy["close"]) if spy and spy.get("close") else None
    if spy and spy.get("close"):
        line = metrics.rs_line(close, spy["close"])
        rs_spy_near = metrics.near_rolling_high(line, 252, near_ratio)
        spy3 = metrics.pct_return(spy["close"], metrics.TRADING_DAYS_3M)
        if ret_3m is not None and spy3 is not None:
            rs_vs_spy_3m = round(ret_3m - spy3, 4)
    if qqq and qqq.get("close"):
        line = metrics.rs_line(close, qqq["close"])
        rs_qqq_near = metrics.near_rolling_high(line, 252, near_ratio)
        qqq3 = metrics.pct_return(qqq["close"], metrics.TRADING_DAYS_3M)
        if ret_3m is not None and qqq3 is not None:
            rs_vs_qqq_3m = round(ret_3m - qqq3, 4)

    # --- sector action ---
    # The stock-vs-sector-ETF comparison is meaningless for an ETF itself, so
    # skip the mapping for ETFs (sector_action then returns a neutral 0.5).
    is_etf = bool(cand.get("is_etf"))
    etf = None if is_etf else sector.resolve_etf(cand["ticker"], cand.get("sector"), sector_map)
    etf_bars = benches.get(etf) if etf else None
    sect = sector.sector_action(ret_3m, etf, etf_bars, spy_ret_3m, cfg)

    return {
        "ticker": cand["ticker"],
        "company_name": cand.get("company"),
        "sector": cand.get("sector"),
        "industry": cand.get("industry"),
        "current_price": round(price, 4),
        "market_cap": cand.get("market_cap"),
        "avg_dollar_volume_20d": round(adv20, 0) if adv20 is not None else None,
        # structure levels (for the chart overlay)
        "sma50": sma50, "sma150": sma150, "sma200": sma200,
        "sma200_20d_ago": sma200_20,
        "sma50_20d_ago": sma50_20,
        "high_52w": high52, "low_52w": low52,
        # recent listing / IPO: short history, evaluated with the adapted template
        "is_ipo": short_history,
        "history_days": len(close),
        "is_etf": is_etf,
        # returns
        "ret_3m": ret_3m, "ret_6m": ret_6m, "ret_12m": ret_12m,
        # prior uptrend
        "prior_uptrend_return": prior_ret, "prior_uptrend_pass": prior_pass,
        # rs line
        "rs_vs_spy_3m": rs_vs_spy_3m, "rs_vs_qqq_3m": rs_vs_qqq_3m,
        "rs_line_spy_near_high": rs_spy_near, "rs_line_qqq_near_high": rs_qqq_near,
        # 50d line
        "distance_to_sma50": dist_sma50, "sma50_position_pass": sma50_pass,
        # beta (vs SPY) — kept for display; the In-Base vigor haircut now uses ADR%
        "beta": beta_val,
        # ADR% (avg daily range, 20d) — beta substitute for the vigor haircut
        "adr_pct": metrics.adr_pct(high, low, 20),
        # nested detail
        "base": base, "pivot": pivot, "vcp": vcp, "volatility": volat,
        "volume": vol, "sector_detail": sect,
        # sector convenience (flattened for the table)
        "sector_etf": sect.get("sector_etf"),
        "sector_return_3m": sect.get("sector_return_3m"),
        "sector_action_score": sect.get("sector_action_score"),
        # short-term extras for the In-Base score (ret_5d/10d/21d, recent range,
        # base position, volume-confirmed pocket pivot)
        **inbase.short_term_metrics(
            close, high, low, base, volume=volume,
            pp_lookback=int((cfg.get("inbase") or {}).get("pocket_pivot_lookback", 10)),
        ),
    }, None


def run_scan(cfg: dict | None = None, limit: int | None = None,
             progress: bool = False) -> dict:
    """Run the full scan and return the dashboard payload."""
    from . import universe   # local import to keep finviz optional at import time

    cfg = cfg or load_config()
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    candidates = universe.get_candidates(cfg)
    if limit:
        candidates = candidates[:limit]

    # Benchmarks + every sector ETF we might map to, fetched once.
    bench_tickers = list(cfg["benchmarks"]) + sector.all_referenced_etfs()
    benches = data.fetch_benchmarks(bench_tickers)
    spy = benches.get("SPY")
    spy_ret_3m = metrics.pct_return(spy["close"], metrics.TRADING_DAYS_3M) if spy and spy.get("close") else None

    sector_map = sector.load_mapping()

    records: list[dict] = []
    failures = 0
    # Visibility into WHY candidates don't make the final list: every drop is
    # attributed to a reason, so a missing ticker is explainable instead of
    # vanishing silently. dropped = [{"ticker","reason"}...]; drop_reasons =
    # {reason: count}.
    dropped: list[dict] = []
    drop_reasons: dict[str, int] = {}

    def _drop(ticker: str, reason: str):
        nonlocal failures
        drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
        dropped.append({"ticker": ticker, "reason": reason})

    demo = os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")
    for i, cand in enumerate(candidates):
        try:
            bars = data.fetch_bars(cand["ticker"])
        except Exception as e:
            failures += 1
            _drop(cand["ticker"], f"fetch_error:{type(e).__name__}")
            if not demo:
                time.sleep(0.2)
            continue
        try:
            rec, reason = _build_record(cand, bars, benches, cfg, sector_map, spy_ret_3m)
        except Exception as e:
            failures += 1
            _drop(cand["ticker"], f"build_error:{type(e).__name__}")
            rec, reason = None, None
        if rec:
            records.append(rec)
        elif reason:
            _drop(cand["ticker"], reason)
        if not demo:
            time.sleep(0.2)   # be gentle with the data source
        if progress and (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(candidates)} scanned, {len(records)} kept")

    # RS percentiles across the surviving universe.
    rs.assign_rs(records, cfg)

    # Trend template (needs RS percentile) + scoring + alerts.
    tt_cfg = cfg["trend_template"]
    for rec in records:
        tt = metrics.trend_template(
            rec["current_price"], rec["sma50"], rec["sma150"], rec["sma200"],
            rec.get("sma200_20d_ago"),
            rec["high_52w"], rec["low_52w"], rec["rs_percentile"],
            sma50_20d_ago=rec.get("sma50_20d_ago"),
            short_history=bool(rec.get("is_ipo")),
            min_rs_percentile=tt_cfg["min_rs_percentile"],
            min_vs_low=tt_cfg["min_price_vs_52w_low"],
            min_vs_high=tt_cfg["min_price_vs_52w_high"],
        )
        rec["trend"] = tt
        rec["trend_template_pass"] = tt["trend_template_pass"]
        scoring.compute_scores(rec, cfg)
        inbase.compute(rec, cfg)   # In-Base health score + base-type tag + vigor

    # Drop clearly sleepy low-ADR% / no-thrust names (In-Base vigor exclude).
    for r in records:
        if r.get("low_vigor"):
            _drop(r["ticker"], "low_vigor(ADR<2%+weak)")
    records = [r for r in records if not r.get("low_vigor")]
    records.sort(key=_sort_key, reverse=False)

    return {
        "built": built,
        "count": len(records),
        "universe_size": len(candidates),
        "failures": failures,
        "dropped_count": len(dropped),
        "drop_reasons": drop_reasons,   # {reason: count}
        "dropped": dropped,             # [{ticker, reason}] — searchable "왜 빠졌나"
        "demo": demo,
        "stocks": records,
    }


def _sort_key(rec: dict):
    # total_score desc, then closest-to-pivot, then rs_percentile desc.
    total = rec.get("total_score") or 0
    dist = rec.get("pivot", {}).get("distance_to_pivot")
    dist = abs(dist) if dist is not None else 9.99
    rsp = rec.get("rs_percentile") or 0
    return (-total, dist, -rsp)
