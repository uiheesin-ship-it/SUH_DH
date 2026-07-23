"""Same-day Korean OHLCV via FinanceDataReader (Naver/KRX), Yahoo as fallback.

Yahoo's daily bars for .KS/.KQ lag ~a day from datacenter (build-server) IPs, so
the Korean charts/screens showed data one day behind the build timestamp. FDR is
Naver/KRX-sourced and has the day's EOD promptly after the 15:30 KST close; we
only fall back to Yahoo (lagged) when FDR returns nothing. Bars are cached per
code so a ticker's screener analysis and its chart use the *same* series.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from . import cache
from .indicators import attach_moving_averages

BARS_TTL = float(os.environ.get("SUH_DH_KR_BARS_TTL", "1800"))
# ~2.2 years so 52-week high, SMA200 and the base window all have enough history.
LOOKBACK_DAYS = int(os.environ.get("SUH_DH_KR_LOOKBACK_DAYS", "820"))


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _empty(code: str) -> dict:
    return {"ticker": code, "range": "max", "dates": [], "open": [],
            "high": [], "low": [], "close": [], "volume": []}


def _fetch_fdr(code: str) -> dict:
    import FinanceDataReader as fdr

    start = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    try:
        df = fdr.DataReader(code, start)
    except Exception:
        return _empty(code)
    if df is None or df.empty or "Close" not in df.columns:
        return _empty(code)
    df = df.dropna(subset=["Close"])
    if df.empty:
        return _empty(code)

    def col(name, default_from="Close"):
        return df[name] if name in df.columns else df[default_from]

    return {
        "ticker": code, "range": "max",
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "open": [round(float(x), 4) for x in col("Open")],
        "high": [round(float(x), 4) for x in col("High")],
        "low": [round(float(x), 4) for x in col("Low")],
        "close": [round(float(x), 4) for x in df["Close"]],
        "volume": [int(x) if x == x else 0 for x in col("Volume", "Close").fillna(0)]
        if "Volume" in df.columns else [0] * len(df),
    }


def _fetch_yahoo(code: str, market: str | None) -> dict:
    """Fallback to the proven Yahoo fetcher (lagged, but never blank)."""
    from .base import data as basedata

    if market:
        syms = [f"{code}.{'KQ' if market == 'KOSDAQ' else 'KS'}"]
    else:
        syms = [f"{code}.KS", f"{code}.KQ"]
    for sym in syms:
        bars = basedata.fetch_bars(sym, use_cache=False)
        if bars and bars.get("close"):
            bars["ticker"] = code
            return bars
    return _empty(code)


def fetch_kr_bars(code: str, market: str | None = None) -> dict:
    """Daily OHLCV for a Korean ticker (FDR first, Yahoo fallback), cached by code."""
    code = str(code)
    if code.isdigit():
        code = code.zfill(6)

    def producer():
        if _demo():
            from .base import data as basedata
            return basedata._demo_bars(code)
        data = _fetch_fdr(code)
        return data if data.get("close") else _fetch_yahoo(code, market)

    return cache.get_or_set(f"krbars:{code}", BARS_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("close")))


# KOSPI/KOSDAQ index benchmarks (FDR code, Yahoo fallback symbol).
_INDEX = {"KOSPI": ("KS11", "^KS11"), "KOSDAQ": ("KQ11", "^KQ11")}


def fetch_kr_index(which: str) -> dict:
    """Daily bars for the KOSPI or KOSDAQ index (FDR first, Yahoo fallback)."""
    fdr_code, yahoo_sym = _INDEX[which]

    def producer():
        if _demo():
            from .base import data as basedata
            return basedata._demo_bars(fdr_code)
        data = _fetch_fdr(fdr_code)
        if data.get("close"):
            return data
        from .base import data as basedata
        bars = basedata.fetch_bars(yahoo_sym, use_cache=False)
        return bars if bars and bars.get("close") else _empty(fdr_code)

    return cache.get_or_set(f"kridx:{which}", BARS_TTL, producer,
                            cache_when=lambda d: bool(d and d.get("close")))


def kr_chart(code: str, market: str | None = None) -> dict:
    """Chart payload (OHLCV + ma5/20/50/120) for the KR dashboard pages."""
    chart = dict(fetch_kr_bars(code, market))
    return attach_moving_averages(chart)
