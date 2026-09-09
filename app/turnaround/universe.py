"""Candidate universe for the turnaround (bottom base) screener.

US common stock on NYSE/NASDAQ. Two deliberate differences from the base and
flat screeners' universes:

  * No moving-average pre-filter. The base screener asks Finviz for names above
    their 50- and 200-day; this screener's whole hunting ground is underneath
    the 200-day, so that filter would return an empty intersection.
  * ETFs and REITs are excluded outright, not optional. A turnaround is a
    single-company story — an index fund does not have one, and a REIT's base is
    a rates chart. Both would otherwise dominate a list ranked on tightness.
"""

from __future__ import annotations

import os

from .. import cache
from ..flat.universe import (
    _looks_like_fund,
    _looks_like_reit,
    _to_float,
)

UNIVERSE_TTL = float(os.environ.get("SUH_DH_TURNAROUND_UNIVERSE_TTL", "900"))

DEMO_UNIVERSE = [
    {"ticker": "TURNA", "company": "Turn Alpha Corp", "sector": "Technology",
     "industry": "Software - Application", "market_cap": 2.4e9, "price": 18.0,
     "country": "USA"},
    {"ticker": "TURNB", "company": "Basing Beta Industries", "sector": "Industrials",
     "industry": "Specialty Industrial Machinery", "market_cap": 1.1e9, "price": 27.0,
     "country": "USA"},
    {"ticker": "KNIFE", "company": "Falling Knife Energy", "sector": "Energy",
     "industry": "Oil & Gas E&P", "market_cap": 8.0e8, "price": 6.5,
     "country": "USA"},
    {"ticker": "GONEC", "company": "Already Gone Chemicals", "sector": "Basic Materials",
     "industry": "Specialty Chemicals", "market_cap": 3.2e9, "price": 44.0,
     "country": "USA"},
]


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _fetch_finviz(cfg: dict) -> list[dict]:
    from finvizfinance.screener.overview import Overview

    from ..screener import _clean_tickers, _prime_finviz

    _prime_finviz()
    uni = cfg["universe"]
    fos = Overview()

    # Wide net; the real filtering happens in-code once bars are available.
    # Note what is NOT here: no SMA filter, no new-high signal. Liquidity is a
    # dollar-volume gate applied after fetching bars, so a high-priced but
    # thinly-traded-in-shares name is judged fairly.
    desired: list[tuple[str, str]] = [
        ("Price", "Over $1"),
        ("Market Cap.", "Small (over $300mln)"),
        ("Industry", "Stocks only (ex-Funds)"),
    ]
    if not uni.get("include_adr", True):
        desired.append(("Country", "USA"))

    applied: dict[str, str] = {}
    for key, val in desired:
        trial = dict(applied)
        trial[key] = val
        try:
            fos.set_filter(filters_dict=trial)
            applied = trial
        except Exception:
            continue

    df = fos.screener_view(verbose=0)
    if df is None or df.empty:
        return []

    tickers = _clean_tickers([str(r.get("Ticker") or "") for _, r in df.iterrows()])
    rows: list[dict] = []
    for (_, r), ticker in zip(df.iterrows(), tickers):
        company = r.get("Company")
        industry = r.get("Industry")
        if _looks_like_fund(company, industry):
            continue
        if _looks_like_reit(company, industry):
            continue
        rows.append({
            "ticker": ticker,
            "company": company,
            "sector": (r.get("Sector") or "Unknown") or "Unknown",
            "industry": industry if industry and str(industry) != "nan" else None,
            "market_cap": _to_float(r.get("Market Cap")),
            "price": _to_float(r.get("Price")),
            "country": r.get("Country"),
        })
    return rows


def get_candidates(cfg: dict) -> list[dict]:
    if _demo():
        return list(DEMO_UNIVERSE)

    def producer():
        try:
            return _fetch_finviz(cfg)
        except Exception:
            return []

    rows = cache.get_or_set("turnaround_universe", UNIVERSE_TTL, producer,
                            cache_when=lambda r: bool(r))

    uni = cfg["universe"]
    include_adr = uni.get("include_adr", True)
    min_mcap = float(cfg["min_market_cap"])
    min_price = float(cfg["min_price"])

    filtered = []
    for r in rows:
        mc = r.get("market_cap")
        px = r.get("price")
        if min_mcap and mc is not None and mc < min_mcap:
            continue
        if px is not None and px < min_price:
            continue
        if not include_adr and (r.get("country") or "USA") != "USA":
            continue
        filtered.append(r)

    # Even market-cap sampling so a truncated universe isn't all mega-cap.
    cap = int(uni.get("max_candidates", 3000))
    if os.environ.get("SUH_DH_TURNAROUND_LIMIT"):
        cap = int(os.environ["SUH_DH_TURNAROUND_LIMIT"])
    filtered.sort(key=lambda r: r.get("market_cap") or 0, reverse=True)
    if 0 < cap < len(filtered):
        step = len(filtered) / cap
        return [filtered[int(i * step)] for i in range(cap)]
    return filtered
