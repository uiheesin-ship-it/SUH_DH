"""Candidate universe for the Flat Base Screener (spec §2).

NYSE/NASDAQ US common stock. Excluded by default: ETF/ETN, preferred, SPAC,
warrant, unit, and REIT — but REIT is excluded *specifically* (industry/company
name says REIT), NOT the entire Real Estate sector, so a normal real-estate
operating company still qualifies. Price >= $5; the $10M average-dollar-volume
gate is applied after bars are fetched (Finviz's volume filter is share count,
not dollars). No moving-average filter — a flat base can sit anywhere.

Toggles (config): include_reit, include_adr, min_price, min_market_cap,
min_avg_dollar_volume_20d, max_candidates.
"""

from __future__ import annotations

import os
import re

from .. import cache

UNIVERSE_TTL = float(os.environ.get("SUH_DH_FLAT_UNIVERSE_TTL", "900"))

# Non-common-stock markers (exclude even if a source misclassifies the row).
_EXCLUDE_WORDS = ("etf", "etn", "exchange traded", "closed-end", "closed end",
                  "preferred", "warrant", " unit", "acquisition corp", "spac",
                  "blank check")
# On the ETF pass we keep ETFs but still drop non-ETF fund wrappers.
_ETF_EXCLUDE_WORDS = ("etn", "closed-end", "closed end", "preferred", "warrant",
                      " unit", "acquisition corp", "spac", "blank check")
# Leveraged / inverse products (daily-rebalanced, chart decays) — excluded.
_LEVERAGED_WORDS = ("leveraged", "ultrapro", "ultra", "inverse", " bull", " bear",
                    "-1x", "-2x", "-3x")
_LEVERAGED_MULT = re.compile(r"(?<![a-z0-9])\d(?:\.\d+)?x(?![a-z])")  # 2x, 3x, 1.5x
# "Short" = inverse for an equity/index fund, but short-DURATION for fixed income.
_FIXED_INCOME_WORDS = ("bond", "treasury", "duration", "term", "maturity",
                       "municipal", "govt", "government", "credit", "corporate", "yield")


def _is_leveraged(company: str | None, ticker: str | None = None) -> bool:
    text = f" {(company or '').lower()} "
    if any(w in text for w in _LEVERAGED_WORDS):
        return True
    if _LEVERAGED_MULT.search(text):
        return True
    if " short " in text and not any(w in text for w in _FIXED_INCOME_WORDS):
        return True
    return False

DEMO_UNIVERSE = [
    {"ticker": "FLATA", "company": "Flatline Alpha", "sector": "Technology",
     "industry": "Software - Application", "market_cap": 8.0e9, "price": 55.0,
     "country": "USA", "is_reit": False},
    {"ticker": "FLATB", "company": "Range Beta", "sector": "Industrials",
     "industry": "Specialty Industrial Machinery", "market_cap": 4.0e9, "price": 40.0,
     "country": "USA", "is_reit": False},
    {"ticker": "FLATC", "company": "Turn Gamma", "sector": "Healthcare",
     "industry": "Biotechnology", "market_cap": 3.0e9, "price": 22.0,
     "country": "USA", "is_reit": False},
    {"ticker": "REITX", "company": "Sleepy REIT Trust", "sector": "Real Estate",
     "industry": "REIT - Diversified", "market_cap": 6.0e9, "price": 33.0,
     "country": "USA", "is_reit": True},
]


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _to_float(v):
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _looks_like_fund(company: str | None, industry: str | None) -> bool:
    text = f"{company or ''} {industry or ''}".lower()
    return any(w in text for w in _EXCLUDE_WORDS)


def _looks_like_reit(company: str | None, industry: str | None) -> bool:
    """REIT specifically — industry "REIT - ..." or the name says REIT. Do NOT
    treat the whole Real Estate sector as REIT (spec §2)."""
    ind = (industry or "").lower()
    comp = (company or "").lower()
    return ind.startswith("reit") or "reit" in ind or "reit" in comp


def _fetch_finviz(cfg: dict, etf_pass: bool = False) -> list[dict]:
    from finvizfinance.screener.overview import Overview

    from ..screener import _clean_tickers, _prime_finviz

    _prime_finviz()

    uni = cfg["universe"]
    fos = Overview()

    # Wide net: small-cap and up ($300M+), common stock only, priced over $1
    # (only to dodge sub-$1 penny-stock data noise — the real quality floor is
    # market cap, not price). No SMA / new-high signal filter — flat bases exist
    # below and above the moving averages. And NO share-count "Average Volume"
    # filter: it unfairly excludes higher-priced-but-dollar-liquid names (a $110
    # stock at 200K shares = $22M/day is plenty liquid but fails "Over 500K
    # shares"). Liquidity is judged by the in-code 20-day dollar-volume gate
    # ($10M) instead, which is price-neutral.
    desired: list[tuple[str, str]] = [
        ("Price", "Over $1"),
        ("Market Cap.", "Small (over $300mln)"),
        # ETF pass pulls funds; the stock pass keeps excluding them.
        ("Industry", "Exchange Traded Fund" if etf_pass else "Stocks only (ex-Funds)"),
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
    # Safety: abort the ETF pass if the ETF industry filter was rejected, so we
    # never return regular stocks mislabeled as is_etf=True.
    if etf_pass and applied.get("Industry") != "Exchange Traded Fund":
        return []

    df = fos.screener_view(verbose=0)
    if df is None or df.empty:
        return []

    tickers = _clean_tickers([str(r.get("Ticker") or "") for _, r in df.iterrows()])
    include_reit = bool(uni.get("include_reit", False))

    rows: list[dict] = []
    for (_, r), ticker in zip(df.iterrows(), tickers):
        company = r.get("Company")
        industry = r.get("Industry")
        if etf_pass:
            if _is_leveraged(company, ticker):
                continue
            text = f"{company or ''} {industry or ''}".lower()
            if any(w in text for w in _ETF_EXCLUDE_WORDS):
                continue
            is_reit = False
        else:
            if _looks_like_fund(company, industry):
                continue
            is_reit = _looks_like_reit(company, industry)
            if is_reit and not include_reit:
                continue
        rows.append({
            "ticker": ticker,
            "company": company,
            "sector": (r.get("Sector") or "Unknown") or "Unknown",
            "industry": industry if industry and str(industry) != "nan" else None,
            "market_cap": _to_float(r.get("Market Cap")),
            "price": _to_float(r.get("Price")),
            "country": r.get("Country"),
            "is_reit": is_reit,
            "is_etf": bool(etf_pass),
        })
    return rows


def get_candidates(cfg: dict) -> list[dict]:
    if _demo():
        uni = cfg["universe"]
        rows = list(DEMO_UNIVERSE)
        if not uni.get("include_reit", False):
            rows = [r for r in rows if not r.get("is_reit")]
        return rows

    def producer():
        try:
            return _fetch_finviz(cfg)
        except Exception:
            return []

    rows = cache.get_or_set("flat_universe", UNIVERSE_TTL, producer,
                            cache_when=lambda r: bool(r))

    # ETF pass (leveraged/inverse excluded), merged + tagged is_etf.
    if (cfg.get("universe") or {}).get("include_etf"):
        def etf_producer():
            try:
                return _fetch_finviz(cfg, etf_pass=True)
            except Exception:
                return []
        etf_rows = cache.get_or_set("flat_universe_etf", UNIVERSE_TTL, etf_producer,
                                    cache_when=lambda r: bool(r))
        seen = {r["ticker"] for r in rows}
        rows = list(rows) + [r for r in etf_rows if r["ticker"] not in seen]

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

    # Even market-cap sampling so the list isn't all mega-cap. Stocks and ETFs
    # get SEPARATE budgets so adding ETFs doesn't push stocks out of the cap.
    def _sample(lst: list, n: int) -> list:
        lst.sort(key=lambda r: r.get("market_cap") or 0, reverse=True)
        if 0 < n < len(lst):
            step = len(lst) / n
            return [lst[int(i * step)] for i in range(n)]
        return lst

    cap = int(uni.get("max_candidates", 1500))
    if os.environ.get("SUH_DH_FLAT_LIMIT"):
        cap = int(os.environ["SUH_DH_FLAT_LIMIT"])
    etf_cap = int(uni.get("max_etf_candidates", 700))
    stocks = [r for r in filtered if not r.get("is_etf")]
    etfs = [r for r in filtered if r.get("is_etf")]
    return _sample(stocks, cap) + _sample(etfs, etf_cap)
