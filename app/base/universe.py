"""Build the candidate universe to deep-analyze.

Default source is the Finviz screener (already a project dependency): one request
returns a few hundred liquid names with sector/industry/market-cap/price, letting
us pre-filter cheaply before pulling 2y of OHLCV per survivor. Finviz filter
option strings vary across finvizfinance versions, so filters are applied
defensively — any filter the installed version rejects is dropped rather than
aborting the scan. A small demo universe keeps the offline build working.
"""

from __future__ import annotations

import os

from .. import cache

UNIVERSE_TTL = float(os.environ.get("SUH_DH_BASE_UNIVERSE_TTL", "900"))

# Words in an industry/company name that mark a non-common-stock we exclude even
# if a data source misclassifies it.
_EXCLUDE_WORDS = ("etf", "etn", "exchange traded", "closed-end", "closed end",
                  "preferred", "warrant", " unit", "trust - ")

# Tiny offline universe for SUH_DH_DEMO=1 (names only; bars are synthetic).
DEMO_UNIVERSE = [
    {"ticker": "DEMOA", "company": "Demo Alpha", "sector": "Technology",
     "industry": "Software - Application", "market_cap": 8.0e9, "price": 55.0, "country": "USA"},
    {"ticker": "DEMOB", "company": "Demo Beta", "sector": "Technology",
     "industry": "Semiconductors", "market_cap": 22.0e9, "price": 88.0, "country": "USA"},
    {"ticker": "DEMOC", "company": "Demo Gamma", "sector": "Healthcare",
     "industry": "Biotechnology", "market_cap": 3.0e9, "price": 41.0, "country": "USA"},
    {"ticker": "DEMOD", "company": "Demo Delta", "sector": "Industrials",
     "industry": "Aerospace & Defense", "market_cap": 6.0e9, "price": 33.0, "country": "USA"},
    {"ticker": "DEMOE", "company": "Demo Epsilon", "sector": "Energy",
     "industry": "Oil & Gas E&P", "market_cap": 5.5e9, "price": 27.0, "country": "USA"},
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


def _fetch_finviz(cfg: dict) -> list[dict]:
    from finvizfinance.screener.overview import Overview

    from ..screener import _clean_tickers, _prime_finviz

    _prime_finviz()  # modern headers + cookie/proxy, same as the highs screener

    uni = cfg["universe"]
    fos = Overview()

    # Build the richest filter set we can; drop any option the installed
    # finvizfinance rejects (ValueError) and retry, so a version mismatch on one
    # option string never aborts the whole scan.
    desired: list[tuple[str, str]] = [
        ("Price", "Over $10"),
        ("Average Volume", "Over 500K"),
        ("Market Cap.", "Small (over $300mln)"),
        ("Industry", "Stocks only (ex-Funds)"),
    ]
    if uni.get("finviz_price_above_sma200"):
        desired.append(("200-Day Simple Moving Average", "Price above SMA200"))
    if uni.get("finviz_price_above_sma50"):
        desired.append(("50-Day Simple Moving Average", "Price above SMA50"))
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
            # This particular filter option isn't recognized — skip it.
            continue
    # Always keep the "New High"-agnostic base screen; no signal filter so we
    # can catch pre-breakout bases (price need not be at a new high yet).
    df = fos.screener_view(verbose=0)
    if df is None or df.empty:
        return []

    # Finviz's 1-letter logo avatar doubles the scraped symbol (SO -> SSO,
    # V -> VV) exactly as in the highs screener; undo it here too, or the scan
    # fetches OHLCV for the wrong security (SSO is a leveraged ETF, not Southern).
    tickers = _clean_tickers([str(r.get("Ticker") or "") for _, r in df.iterrows()])

    rows: list[dict] = []
    for (_, r), ticker in zip(df.iterrows(), tickers):
        company = r.get("Company")
        industry = r.get("Industry")
        if _looks_like_fund(company, industry):
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
    """Return the pre-filtered candidate list (cached briefly)."""
    if _demo():
        return list(DEMO_UNIVERSE)

    def producer():
        try:
            rows = _fetch_finviz(cfg)
        except Exception:
            rows = []
        return rows

    rows = cache.get_or_set("base_universe", UNIVERSE_TTL, producer,
                            cache_when=lambda r: bool(r))

    uni = cfg["universe"]
    include_adr = uni.get("include_adr", True)
    min_mcap = float(cfg["min_market_cap"])
    min_price = float(cfg["min_price"])

    filtered = []
    for r in rows:
        mc = r.get("market_cap")
        px = r.get("price")
        if mc is not None and mc < min_mcap:
            continue
        if px is not None and px < min_price:
            continue
        if not include_adr and (r.get("country") or "USA") != "USA":
            continue
        filtered.append(r)

    # Largest first; cap to the configured budget so OHLCV fetching stays bounded.
    filtered.sort(key=lambda r: r.get("market_cap") or 0, reverse=True)
    cap = int(uni.get("max_candidates", 300))
    if os.environ.get("SUH_DH_BASE_LIMIT"):
        cap = int(os.environ["SUH_DH_BASE_LIMIT"])
    return filtered[:cap]
