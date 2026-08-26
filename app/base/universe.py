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
import time

from .. import cache

# Retry the Finviz universe fetch: Finviz occasionally 403s / throttles bursty
# datacenter callers and can return a partial or empty page, which would
# silently shrink the candidate universe (names go missing for no visible
# reason). A few backoff retries make the universe far more complete/stable.
_UNIVERSE_RETRIES = int(os.environ.get("SUH_DH_BASE_UNIVERSE_RETRIES", "3"))

UNIVERSE_TTL = float(os.environ.get("SUH_DH_BASE_UNIVERSE_TTL", "900"))

import re

# Words in an industry/company name that mark a non-common-stock we exclude even
# if a data source misclassifies it.
_EXCLUDE_WORDS = ("etf", "etn", "exchange traded", "closed-end", "closed end",
                  "preferred", "warrant", " unit", "trust - ")
# On the ETF pass we WANT ETFs, so "etf"/"exchange traded" are allowed — but we
# still drop ETNs, closed-end funds, preferreds, warrants and units (not clean
# ETFs). Leveraged/inverse products are dropped separately by _is_leveraged.
_ETF_EXCLUDE_WORDS = ("etn", "closed-end", "closed end", "preferred", "warrant", " unit")
# Leveraged / inverse ETFs (2x/3x/-1x, Ultra, Direxion Bull/Bear, ProShares
# Short, inverse): daily-rebalanced derivatives whose long-term chart decays, so
# a "base" on them is meaningless. Matched on the fund name.
_LEVERAGED_WORDS = ("leveraged", "ultrapro", "ultra", "inverse", " bull", " bear",
                    "-1x", "-2x", "-3x")
_LEVERAGED_MULT = re.compile(r"(?<![a-z0-9])\d(?:\.\d+)?x(?![a-z])")  # 2x, 3x, 1.5x
# "Short" means INVERSE for an equity/index fund (ProShares Short QQQ) but
# short-DURATION for fixed income (iShares Short Treasury Bond) — only the former
# is a leveraged/inverse product we exclude.
_FIXED_INCOME_WORDS = ("bond", "treasury", "duration", "term", "maturity",
                       "municipal", "govt", "government", "credit", "corporate", "yield")


def _is_leveraged(company: str | None, ticker: str | None = None) -> bool:
    text = f" {(company or '').lower()} "
    if any(w in text for w in _LEVERAGED_WORDS):
        return True
    if _LEVERAGED_MULT.search(text):
        return True
    if " short " in text and not any(w in text for w in _FIXED_INCOME_WORDS):
        return True   # inverse equity/index fund (not a short-duration bond fund)
    return False

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


def _fetch_finviz(cfg: dict, ipo_pass: bool = False, etf_pass: bool = False) -> list[dict]:
    from finvizfinance.screener.overview import Overview

    from ..screener import _clean_tickers, _prime_finviz

    _prime_finviz()  # modern headers + cookie/proxy, same as the highs screener

    uni = cfg["universe"]
    fos = Overview()

    # Build the richest filter set we can; drop any option the installed
    # finvizfinance rejects (ValueError) and retry, so a version mismatch on one
    # option string never aborts the whole scan.
    # NOTE: no share-count "Average Volume" filter here on purpose. Finviz's
    # volume filter counts SHARES, which unfairly excludes higher-priced names
    # (e.g. a $110 stock trading 200K shares = $22M/day is plenty liquid but
    # fails "Over 500K shares"). Liquidity is judged instead by the in-code
    # 20-day average DOLLAR-volume gate ($10M) in screen.py, which is the correct
    # measure and doesn't penalize price. This is why strong high-priced names
    # used to be missing from the base list.
    desired: list[tuple[str, str]] = [
        ("Price", "Over $1"),
        ("Market Cap.", "Small (over $300mln)"),
        # ETF pass swaps the "Stocks only" industry for the ETF industry so we
        # deliberately pull funds; the stock passes keep excluding them.
        ("Industry", "Exchange Traded Fund" if etf_pass else "Stocks only (ex-Funds)"),
    ]
    if etf_pass:
        # ETFs held to the same healthy-uptrend bar as stocks (above 50/200-day).
        if uni.get("finviz_price_above_sma200"):
            desired.append(("200-Day Simple Moving Average", "Price above SMA200"))
        if uni.get("finviz_price_above_sma50"):
            desired.append(("50-Day Simple Moving Average", "Price above SMA50"))
    elif ipo_pass:
        # Recent-IPO pass: DON'T require SMA200 (young stocks don't have one) —
        # that filter is exactly what shut IPOs out. Keep "above SMA50" so we
        # still catch uptrending post-IPO bases, and restrict to recent listings.
        ipo_date = str((cfg.get("ipo") or {}).get("finviz_ipo_date", "In the last year"))
        desired.append(("IPO Date", ipo_date))
        desired.append(("50-Day Simple Moving Average", "Price above SMA50"))
    else:
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
    # Safety: if the ETF industry filter didn't apply (option string rejected by
    # this finvizfinance version), abort the ETF pass rather than returning
    # regular stocks that would be mislabeled is_etf=True.
    if etf_pass and applied.get("Industry") != "Exchange Traded Fund":
        return []
    # Always keep the "New High"-agnostic base screen; no signal filter so we
    # can catch pre-breakout bases (price need not be at a new high yet).
    # Retry on failure/empty so a transient Finviz hiccup doesn't silently
    # shrink the universe.
    df = None
    for attempt in range(max(1, _UNIVERSE_RETRIES)):
        try:
            df = fos.screener_view(verbose=0)
        except Exception:
            df = None
        if df is not None and not df.empty:
            break
        if attempt < _UNIVERSE_RETRIES - 1:
            time.sleep(2 * (attempt + 1))   # 2s, 4s, ...
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
        if etf_pass:
            # Keep ETFs, but drop leveraged/inverse and non-ETF fund wrappers.
            if _is_leveraged(company, ticker):
                continue
            text = f"{company or ''} {industry or ''}".lower()
            if any(w in text for w in _ETF_EXCLUDE_WORDS):
                continue
        elif _looks_like_fund(company, industry):
            continue
        rows.append({
            "ticker": ticker,
            "company": company,
            "sector": (r.get("Sector") or "Unknown") or "Unknown",
            "industry": industry if industry and str(industry) != "nan" else None,
            "market_cap": _to_float(r.get("Market Cap")),
            "price": _to_float(r.get("Price")),
            "country": r.get("Country"),
            "from_ipo_pass": bool(ipo_pass),
            "is_etf": bool(etf_pass),
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

    # Second pass: recent IPOs (no SMA200 requirement). Merge, keeping the first
    # occurrence of each ticker so an established name isn't relabeled as IPO.
    if (cfg.get("ipo") or {}).get("enabled"):
        def ipo_producer():
            try:
                return _fetch_finviz(cfg, ipo_pass=True)
            except Exception:
                return []
        ipo_rows = cache.get_or_set("base_universe_ipo", UNIVERSE_TTL, ipo_producer,
                                    cache_when=lambda r: bool(r))
        seen = {r["ticker"] for r in rows}
        extra = [r for r in ipo_rows if r["ticker"] not in seen]
        rows = list(rows) + extra

    # Third pass: ETFs (leveraged/inverse excluded). Merged + tagged is_etf so
    # the UI can show all / ETF-only / ETF-excluded.
    if (cfg.get("universe") or {}).get("include_etf"):
        def etf_producer():
            try:
                return _fetch_finviz(cfg, etf_pass=True)
            except Exception:
                return []
        etf_rows = cache.get_or_set("base_universe_etf", UNIVERSE_TTL, etf_producer,
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
        if mc is not None and mc < min_mcap:
            continue
        if px is not None and px < min_price:
            continue
        if not include_adr and (r.get("country") or "USA") != "USA":
            continue
        filtered.append(r)

    # Do NOT simply keep the biggest N — that drops every mid/small-cap leader,
    # which is exactly where Minervini bases usually form. Sample EVENLY across
    # the whole cap range so large/mid/small stay represented. Stocks and ETFs
    # get SEPARATE budgets so adding ETFs doesn't push stocks out of the cap.
    def _sample(lst: list, n: int) -> list:
        lst.sort(key=lambda r: r.get("market_cap") or 0, reverse=True)
        if 0 < n < len(lst):
            step = len(lst) / n
            return [lst[int(i * step)] for i in range(n)]
        return lst

    cap = int(uni.get("max_candidates", 1500))
    if os.environ.get("SUH_DH_BASE_LIMIT"):
        cap = int(os.environ["SUH_DH_BASE_LIMIT"])
    etf_cap = int(uni.get("max_etf_candidates", 700))
    stocks = [r for r in filtered if not r.get("is_etf")]
    etfs = [r for r in filtered if r.get("is_etf")]
    return _sample(stocks, cap) + _sample(etfs, etf_cap)
