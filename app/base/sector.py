"""Sector-ETF mapping and the "sector action" score.

Mapping precedence:
  1. data/sector_mapping.csv  (user file: ticker,sector_etf) — highest priority
  2. Finviz sector/industry name -> a default ETF (DEFAULT_SECTOR_ETF below)

Tickers with no mapping get a NEUTRAL sector score (not excluded), per spec.
Sector-ETF price series are provided by the caller (fetched once per scan).
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import metrics

ROOT = Path(__file__).resolve().parents[2]
MAPPING_CSV = ROOT / "data" / "sector_mapping.csv"

# Finviz "Sector" -> a broad, liquid ETF as a sensible default. Users override
# per-ticker with data/sector_mapping.csv (e.g. a software name -> IGV).
DEFAULT_SECTOR_ETF = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Healthcare": "XLV",
    "Financial": "XLF",
    "Financial Services": "XLF",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
}

# The richer sub-sector ETF menu from the spec — exposed so build.py can make
# sure their price series get downloaded, and users can reference them in
# data/sector_mapping.csv.
SUBSECTOR_ETFS = {
    "Software": ["IGV", "WCLD", "SKYY"],
    "Cybersecurity": ["BUG", "CIBR", "HACK"],
    "Semiconductor": ["SMH", "SOXX", "SOXQ"],
    "Fabless": ["SMHX"],
    "Memory": ["DRAM"],
    "Photonics": ["FOTO", "EUV"],
    "Energy": ["XLE", "XOP", "OIH", "CRAK", "AMLP", "FCG"],
    "Healthcare": ["XLV", "XBI", "IBB", "IHI", "IHF"],
    "Financials": ["XLF", "KRE", "KBE", "KIE"],
    "Industrials": ["XLI", "ITA", "XAR", "PAVE", "GRID"],
    "Materials": ["XLB", "LIT", "COPX", "REMX", "GDX"],
}


def load_mapping() -> dict[str, str]:
    """Return {TICKER: SECTOR_ETF} from the optional user CSV (may be empty)."""
    mapping: dict[str, str] = {}
    if not MAPPING_CSV.exists():
        return mapping
    try:
        with MAPPING_CSV.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").strip().upper()
                etf = (row.get("sector_etf") or "").strip().upper()
                if t and etf:
                    mapping[t] = etf
    except Exception:
        return {}
    return mapping


def all_referenced_etfs() -> list[str]:
    """Every ETF the mapper might need — for the downloader to pre-fetch."""
    etfs = set(DEFAULT_SECTOR_ETF.values())
    etfs.update(load_mapping().values())
    for lst in SUBSECTOR_ETFS.values():
        etfs.update(lst)
    return sorted(etfs)


def resolve_etf(ticker: str, finviz_sector: str | None, mapping: dict[str, str]) -> str | None:
    """Pick the sector ETF for a ticker: user CSV first, else Finviz-sector default."""
    t = ticker.upper()
    if t in mapping:
        return mapping[t]
    if finviz_sector:
        return DEFAULT_SECTOR_ETF.get(finviz_sector.strip())
    return None


def sector_action(stock_ret_3m: float | None, etf: str | None,
                  etf_bars: dict | None, spy_ret_3m: float | None, cfg: dict) -> dict:
    """Score how constructive the mapped sector ETF is (0..5 by default weight).

    Returns a normalized 0..1 ``sector_action_score`` plus the raw comparisons;
    scoring.py scales it to the sector weight. No mapping -> neutral (0.5).
    """
    weight = cfg["scoring"]["sector_weight"]
    near_high_ratio = float(cfg["sector"]["near_high_ratio"])
    out = {
        "sector_etf": etf,
        "sector_return_3m": None,
        "stock_vs_sector_3m": None,
        "sector_vs_spy_3m": None,
        "sector_trend_pass": None,
        "sector_action_score": 0.5,   # neutral
        "sector_action_points": round(weight * 0.5, 2),
    }
    if not etf or not etf_bars or not etf_bars.get("close"):
        return out

    close = etf_bars["close"]
    high = etf_bars.get("high", close)
    sret3 = metrics.pct_return(close, metrics.TRADING_DAYS_3M)
    sma50 = metrics.sma(close, 50)
    sma200 = metrics.sma(close, 200)
    price = close[-1] if close else None
    high52 = metrics.high_52w(high)

    out["sector_return_3m"] = round(sret3, 4) if sret3 is not None else None
    if stock_ret_3m is not None and sret3 is not None:
        out["stock_vs_sector_3m"] = round(stock_ret_3m - sret3, 4)
    if sret3 is not None and spy_ret_3m is not None:
        out["sector_vs_spy_3m"] = round(sret3 - spy_ret_3m, 4)

    trend_ok = bool(
        price is not None and sma50 is not None and sma200 is not None
        and price > sma50 and sma50 > sma200
    )
    out["sector_trend_pass"] = trend_ok

    # Build a 0..1 score from the constructive conditions.
    score = 0.0
    if sret3 is not None and spy_ret_3m is not None and sret3 > spy_ret_3m:
        score += 0.35           # sector stronger than market
    if stock_ret_3m is not None and sret3 is not None and stock_ret_3m > sret3:
        score += 0.35           # stock stronger than its sector
    if trend_ok:
        score += 0.20           # sector in an uptrend (above 50>200)
    if price is not None and high52 and price >= high52 * near_high_ratio:
        score += 0.10           # sector ETF near its own 52w high
    score = min(1.0, score)
    out["sector_action_score"] = round(score, 3)
    out["sector_action_points"] = round(weight * score, 2)
    return out
