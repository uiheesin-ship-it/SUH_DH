"""OHLCV loading for the base screener (adjusted daily bars, ~2 years).

Reuses the same resilient pattern as app/charts.py: yfinance first (with a short
retry to ride out cloud-IP throttling), Stooq CSV as a key-free fallback so a
scan is never blank just because Yahoo blocked this server. Benchmark/ETF series
are cached per process so we fetch SPY/QQQ/sector ETFs once per scan.

All series are returned as adjusted OHLCV (auto_adjust=True) so moving averages,
ATR and returns are split/dividend-consistent. A demo mode (SUH_DH_DEMO=1)
returns deterministic synthetic bars so the build and tests run fully offline.
"""

from __future__ import annotations

import math
import os
import time

from .. import cache

BARS_TTL = float(os.environ.get("SUH_DH_BASE_BARS_TTL", "1800"))
DEFAULT_PERIOD = os.environ.get("SUH_DH_BASE_PERIOD", "2y")


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _empty(ticker: str) -> dict:
    return {"ticker": ticker, "dates": [], "open": [], "high": [],
            "low": [], "close": [], "volume": []}


def _fetch_yahoo(ticker: str, period: str) -> dict:
    import yfinance as yf

    hist = None
    for attempt in range(3):
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        except Exception:
            hist = None
        if hist is not None and not hist.empty:
            break
        time.sleep(0.7 * (attempt + 1))
    if hist is None or hist.empty:
        return _empty(ticker)
    hist = hist.dropna(subset=["Close"])
    return {
        "ticker": ticker,
        "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
        "open": [round(float(x), 4) for x in hist["Open"]],
        "high": [round(float(x), 4) for x in hist["High"]],
        "low": [round(float(x), 4) for x in hist["Low"]],
        "close": [round(float(x), 4) for x in hist["Close"]],
        "volume": [int(x) for x in hist["Volume"].fillna(0)],
    }


def _fetch_stooq(ticker: str, period: str) -> dict:
    import csv
    import io
    import urllib.request

    sym = ticker.lower().replace(".", "-")
    url = f"https://stooq.com/q/d/l/?s={sym}.us&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        return _empty(ticker)

    dates, o, h, l, c, v = [], [], [], [], [], []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            close = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
        dates.append(row["Date"])
        o.append(round(float(row.get("Open") or close), 4))
        h.append(round(float(row.get("High") or close), 4))
        l.append(round(float(row.get("Low") or close), 4))
        c.append(round(close, 4))
        try:
            v.append(int(float(row.get("Volume") or 0)))
        except (ValueError, TypeError):
            v.append(0)
    if not c:
        return _empty(ticker)
    # ~2 years of trading days.
    keep = 520
    if len(dates) > keep:
        dates, o, h, l, c, v = (x[-keep:] for x in (dates, o, h, l, c, v))
    return {"ticker": ticker, "dates": dates, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _demo_bars(ticker: str, period: str = DEFAULT_PERIOD) -> dict:
    """Deterministic synthetic bars: prior uptrend -> a tightening VCP base.

    Purely a function of the ticker string (no RNG that would break resume), so
    the offline build/tests are reproducible.
    """
    seed = sum(ord(ch) for ch in ticker)
    n = 420
    base_price = 20 + (seed % 80)
    o, h, l, c, v = [], [], [], [], []
    price = base_price
    dates = []
    # Build a fake but chronological date axis (weekdays only-ish is not needed
    # for the math; the frontend uses /api/chart for real dates).
    for i in range(n):
        dates.append(f"D{i:04d}")
        if i < 250:                     # prior uptrend
            drift = 0.004
            wob = 0.02 * math.sin((i + seed) / 7.0)
        else:                           # tightening base
            k = (i - 250) / (n - 250)
            drift = 0.0
            wob = 0.05 * (1 - k) * math.sin((i + seed) / 5.0)
        price = max(1.0, price * (1 + drift + wob))
        hi = price * (1 + abs(wob) * 0.6 + 0.005)
        lo = price * (1 - abs(wob) * 0.6 - 0.005)
        op = (hi + lo) / 2
        vol = 2_000_000 * (1.4 - 0.6 * (i / n))     # volume fades over time
        if i > 250:
            vol *= 0.7
        o.append(round(op, 4)); h.append(round(hi, 4)); l.append(round(lo, 4))
        c.append(round(price, 4)); v.append(int(vol))
    return {"ticker": ticker, "dates": dates, "open": o, "high": h, "low": l, "close": c, "volume": v}


def fetch_bars(ticker: str, period: str = DEFAULT_PERIOD, use_cache: bool = True) -> dict:
    """Adjusted daily OHLCV for one ticker (cached, with fallback source)."""
    ticker = ticker.upper().strip()

    def producer():
        if _demo():
            return _demo_bars(ticker, period)
        data = _fetch_yahoo(ticker, period)
        if data["close"]:
            return data
        return _fetch_stooq(ticker, period)

    if not use_cache:
        return producer()
    # Only cache non-empty results so a transient block is retried next time.
    return cache.get_or_set(
        f"basebars:{ticker}:{period}", BARS_TTL, producer,
        cache_when=lambda d: bool(d and d.get("close")),
    )


_bench_cache: dict[str, dict] = {}


def fetch_benchmarks(tickers: list[str], period: str = DEFAULT_PERIOD) -> dict[str, dict]:
    """Fetch a set of benchmark/ETF series once, memoized for the whole scan."""
    out: dict[str, dict] = {}
    for t in tickers:
        t = t.upper().strip()
        if not t:
            continue
        if t not in _bench_cache:
            bars = fetch_bars(t, period)
            if bars and bars.get("close"):
                _bench_cache[t] = bars
        if t in _bench_cache:
            out[t] = _bench_cache[t]
        if not _demo():
            time.sleep(0.25)   # be gentle with the source
    return out


def clear_benchmark_cache() -> None:
    _bench_cache.clear()
