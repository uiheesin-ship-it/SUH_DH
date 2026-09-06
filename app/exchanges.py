"""US ticker → exchange (NASDAQ / NYSE / AMEX) map, for TradingView-format export.

TradingView watchlist imports want ``EXCHANGE:SYMBOL`` (e.g. ``NASDAQ:AAPL``).
The base/flat screeners only know the bare symbol, so we build a symbol→exchange
lookup from FinanceDataReader's US listings once (cached), write it to
data/us_exchanges.json at build time, and the frontend uses it to prefix the
exported tickers.

Defensive: any FDR failure yields fewer/no entries (export then falls back to
bare symbols) rather than aborting a build.
"""

from __future__ import annotations

import os

from . import cache

EXCH_TTL = float(os.environ.get("SUH_DH_EXCH_TTL", "86400"))  # 1 day

# FDR market → TradingView exchange prefix. NASDAQ first so it wins ties.
_MARKETS = (("NASDAQ", "NASDAQ"), ("NYSE", "NYSE"), ("AMEX", "AMEX"))


def _norm(sym: str) -> str:
    """Canonical key: uppercase, class-share separator as '-' (Finviz style)."""
    return str(sym).upper().replace(".", "-").strip()


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _build() -> dict:
    if _demo():
        return {"AAPL": "NASDAQ", "TSLA": "NASDAQ", "NVDA": "NASDAQ",
                "BRK-B": "NYSE", "JPM": "NYSE", "MTCH": "NASDAQ"}
    import FinanceDataReader as fdr

    out: dict[str, str] = {}
    for market, prefix in _MARKETS:
        try:
            df = fdr.StockListing(market)
        except Exception as e:
            print(f"  exchanges: {market} listing failed: {e}")
            continue
        col = next((c for c in ("Symbol", "Code", "Ticker") if c in getattr(df, "columns", [])), None)
        if not col:
            continue
        for sym in df[col]:
            if sym is None:
                continue
            key = _norm(sym)
            if key and key not in out:   # first market (NASDAQ) wins
                out[key] = prefix
    return out


def us_exchange_map() -> dict:
    """{normalized_symbol: 'NASDAQ'|'NYSE'|'AMEX'} — cached, empty on failure."""
    return cache.get_or_set("us_exchanges", EXCH_TTL, _build,
                            cache_when=lambda m: bool(m))
