"""Korean (KOSPI+KOSDAQ) base screener — the 국장 twin of screen.py.

Reuses ALL the pure computation (metrics / detect / rs / scoring) unchanged; only
the *inputs* differ:
  - universe  : krhighs.kr_universe() (FDR KRX listing, cap floor, excl SPAC/ETF/우)
  - bars      : Yahoo .KS/.KQ via base.data.fetch_bars (proven on the build server)
  - benchmarks: KOSPI ^KS11 (stored in the "spy" slots) and KOSDAQ ^KQ11 ("qqq"),
                so scoring.py — which reads rs_line_spy_*/rs_vs_spy_3m — works as-is.
  - sector    : neutral (no Korean sector-ETF mapping yet), so every name gets the
                same 0.5 sector score instead of being excluded.

USD liquidity gates (min_price=$10, min $-volume) don't apply to won-denominated
prices, so they're skipped here; the 1,500억원 market-cap floor in kr_universe()
already bounds liquidity.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import numpy as np

from . import detect, inbase, metrics, rs, scoring, sector
from .config import load as load_config

KOSPI = "^KS11"
KOSDAQ = "^KQ11"


def _daily_range_pct(high, low, close) -> list[float]:
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        dr = np.where(c != 0, (h - l) / c, np.nan)
    return [float(x) if np.isfinite(x) else 0.0 for x in dr]


def _avg_won_volume_20d(close, volume) -> float | None:
    if len(close) < 20:
        return None
    c = np.asarray(close[-20:], dtype=float)
    v = np.asarray(volume[-20:], dtype=float)
    dv = (c * v)[np.isfinite(c * v)]
    return float(dv.mean()) if dv.size else None


def _yahoo(code: str, market: str) -> str:
    return f"{code}.{'KQ' if market == 'KOSDAQ' else 'KS'}"


def _build_record(cand: dict, bars: dict, kospi: dict | None, kosdaq: dict | None,
                  cfg: dict, kospi_ret_3m: float | None) -> dict | None:
    close = bars.get("close") or []
    high = bars.get("high") or []
    low = bars.get("low") or []
    volume = bars.get("volume") or []
    dates = bars.get("dates") or []

    if len(close) < int(cfg["min_history_days"]):
        return None
    price = close[-1]
    if not price or price <= 0:
        return None
    if len(volume) and volume[-1] <= 0:
        return None
    adv20 = _avg_won_volume_20d(close, volume)  # won turnover — shown, not gated

    sma50 = metrics.sma(close, 50)
    sma150 = metrics.sma(close, 150)
    sma200 = metrics.sma(close, 200)
    sma200_20 = metrics.value_n_days_ago(metrics.sma_series(close, 200), 20)
    high52 = metrics.high_52w(high)
    low52 = metrics.low_52w(low)

    ret_3m = metrics.pct_return(close, metrics.TRADING_DAYS_3M)
    ret_6m = metrics.pct_return(close, metrics.TRADING_DAYS_6M)
    ret_12m = metrics.pct_return(close, metrics.TRADING_DAYS_12M)

    atr_len = int(cfg["volatility"]["atr_length"])
    atr_vals = metrics.atr_series(high, low, close, atr_len)
    atr10 = metrics.atr_last(high, low, close, 10)
    atr50 = metrics.atr_last(high, low, close, 50)
    hl = np.asarray(high, dtype=float) - np.asarray(low, dtype=float)
    recent_range10 = float(hl[-10:].mean()) if len(hl) >= 10 else None
    recent_range50 = float(hl[-50:].mean()) if len(hl) >= 50 else None
    dr_pct = _daily_range_pct(high, low, close)

    base = detect.detect_base(high, low, close, dates, cfg)
    vol = detect.volume_dry_up(close, volume, base, cfg)
    pivot = detect.pivot_analysis(price, base, high, close, volume, vol["avg_volume_50d"], cfg)
    vcp = detect.vcp_structure(high, low, base, cfg)
    volat = detect.volatility_contraction(
        atr_vals, dr_pct, base, cfg, atr10, atr50, recent_range10, recent_range50)

    prior_ret = None
    if len(close) >= 121 and close[-121]:
        prior_ret = round(close[-21] / close[-121] - 1.0, 4)
    prior_pass = bool(prior_ret is not None and prior_ret >= float(cfg["prior_uptrend"]["min_return"]))

    dist_sma50 = round((price - sma50) / sma50, 4) if sma50 else None
    sma50_pass = bool(
        sma50 and float(cfg["sma50"]["min_ratio"]) * sma50 <= price <= float(cfg["sma50"]["max_ratio"]) * sma50
    )

    # RS line vs KOSPI (spy slot) / KOSDAQ (qqq slot) so scoring.py works unchanged.
    near_ratio = float(cfg["rs_line"]["near_high_ratio"])
    rs_spy_near = rs_qqq_near = None
    rs_vs_spy_3m = rs_vs_qqq_3m = None
    if kospi and kospi.get("close"):
        line = metrics.rs_line(close, kospi["close"])
        rs_spy_near = metrics.near_rolling_high(line, 252, near_ratio)
        b3 = metrics.pct_return(kospi["close"], metrics.TRADING_DAYS_3M)
        if ret_3m is not None and b3 is not None:
            rs_vs_spy_3m = round(ret_3m - b3, 4)
    if kosdaq and kosdaq.get("close"):
        line = metrics.rs_line(close, kosdaq["close"])
        rs_qqq_near = metrics.near_rolling_high(line, 252, near_ratio)
        b3 = metrics.pct_return(kosdaq["close"], metrics.TRADING_DAYS_3M)
        if ret_3m is not None and b3 is not None:
            rs_vs_qqq_3m = round(ret_3m - b3, 4)

    # Sector: neutral (no KR sector-ETF map) — never excluded, just 0.5.
    sect = sector.sector_action(ret_3m, None, None, kospi_ret_3m, cfg)

    return {
        "ticker": cand["code"],
        "company_name": cand.get("name"),
        "sector": cand.get("sector") or cand.get("market"),
        "industry": cand.get("industry"),
        "market": cand.get("market"),
        "yahoo": _yahoo(cand["code"], cand.get("market", "KOSPI")),
        "current_price": round(price, 2),
        "market_cap": cand.get("market_cap"),
        "avg_won_volume_20d": round(adv20, 0) if adv20 is not None else None,
        "sma50": sma50, "sma150": sma150, "sma200": sma200, "sma200_20d_ago": sma200_20,
        "high_52w": high52, "low_52w": low52,
        "ret_3m": ret_3m, "ret_6m": ret_6m, "ret_12m": ret_12m,
        "prior_uptrend_return": prior_ret, "prior_uptrend_pass": prior_pass,
        "rs_vs_spy_3m": rs_vs_spy_3m, "rs_vs_qqq_3m": rs_vs_qqq_3m,
        "rs_line_spy_near_high": rs_spy_near, "rs_line_qqq_near_high": rs_qqq_near,
        "distance_to_sma50": dist_sma50, "sma50_position_pass": sma50_pass,
        "base": base, "pivot": pivot, "vcp": vcp, "volatility": volat,
        "volume": vol, "sector_detail": sect,
        "sector_etf": None, "sector_return_3m": None,
        "sector_action_score": sect.get("sector_action_score"),
        **inbase.short_term_metrics(close, high, low, base),
    }


def run_scan(cfg: dict | None = None, limit: int | None = None,
             progress: bool = False) -> dict:
    from .. import krdata, krhighs

    cfg = cfg or load_config()
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")

    candidates = krhighs.kr_universe(limit=limit)
    # Same-day KOSPI/KOSDAQ index benchmarks (FDR/Naver, Yahoo fallback).
    kospi = krdata.fetch_kr_index("KOSPI")
    kosdaq = krdata.fetch_kr_index("KOSDAQ")
    kospi_ret_3m = metrics.pct_return(kospi["close"], metrics.TRADING_DAYS_3M) \
        if kospi and kospi.get("close") else None

    records: list[dict] = []
    failures = 0
    demo = os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")
    for i, cand in enumerate(candidates):
        try:
            bars = krdata.fetch_kr_bars(cand["code"], cand.get("market"))
            rec = _build_record(cand, bars, kospi, kosdaq, cfg, kospi_ret_3m)
            if rec:
                records.append(rec)
        except Exception:
            failures += 1
        if not demo:
            time.sleep(0.15)
        if progress and (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(candidates)} scanned, {len(records)} kept")

    rs.assign_rs(records, cfg)

    tt_cfg = cfg["trend_template"]
    for rec in records:
        tt = metrics.trend_template(
            rec["current_price"], rec["sma50"], rec["sma150"], rec["sma200"],
            rec.get("sma200_20d_ago"), rec["high_52w"], rec["low_52w"], rec["rs_percentile"],
            min_rs_percentile=tt_cfg["min_rs_percentile"],
            min_vs_low=tt_cfg["min_price_vs_52w_low"],
            min_vs_high=tt_cfg["min_price_vs_52w_high"],
        )
        rec["trend"] = tt
        rec["trend_template_pass"] = tt["trend_template_pass"]
        scoring.compute_scores(rec, cfg)
        inbase.compute(rec, cfg)

    def _sort_key(rec):
        total = rec.get("total_score") or 0
        dist = rec.get("pivot", {}).get("distance_to_pivot")
        dist = abs(dist) if dist is not None else 9.99
        return (-total, dist, -(rec.get("rs_percentile") or 0))

    records.sort(key=_sort_key)

    return {
        "built": built,
        "count": len(records),
        "universe_size": len(candidates),
        "failures": failures,
        "demo": demo,
        "market": "KR",
        "stocks": records,
    }
