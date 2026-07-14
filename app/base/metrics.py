"""Pure technical-metric helpers for the base screener.

Everything here operates on plain Python lists / numpy arrays so each function
is unit-testable with synthetic series and never touches the network. Inputs are
adjusted OHLCV (see data.py). Functions return None (not raise) when there is
not enough history, so a single short-history ticker never aborts a scan.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

TRADING_DAYS_3M = 63
TRADING_DAYS_6M = 126
TRADING_DAYS_12M = 252
WEEK52 = 252


def _clean(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def sma(values: Sequence[float], window: int) -> float | None:
    """Latest simple moving average over ``window``, or None if too short."""
    if window <= 0 or len(values) < window:
        return None
    seg = np.asarray(values[-window:], dtype=float)
    if not np.all(np.isfinite(seg)):
        return None
    return round(float(seg.mean()), 4)


def sma_series(values: Sequence[float], window: int) -> list[float | None]:
    """Full SMA series aligned to ``values`` (None until the window fills)."""
    n = len(values)
    out: list[float | None] = [None] * n
    if window <= 0 or n < window:
        return out
    arr = np.asarray(values, dtype=float)
    csum = np.cumsum(np.insert(arr, 0, 0.0))
    for i in range(window - 1, n):
        out[i] = round(float((csum[i + 1] - csum[i + 1 - window]) / window), 4)
    return out


def value_n_days_ago(series: Sequence[float | None], n: int) -> float | None:
    """Value ``n`` trading days before the last point (e.g. SMA200 20d ago)."""
    if len(series) <= n:
        return None
    return _clean(series[-1 - n])


def pct_return(closes: Sequence[float], lookback: int) -> float | None:
    """Simple return over ``lookback`` trading days: c[-1]/c[-1-lookback] - 1."""
    if len(closes) <= lookback:
        return None
    now = _clean(closes[-1])
    then = _clean(closes[-1 - lookback])
    if now is None or then is None or then == 0:
        return None
    return now / then - 1.0


def true_range(high: Sequence[float], low: Sequence[float], close: Sequence[float]) -> np.ndarray:
    """Wilder true range series (first element uses high-low)."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    prev_close = np.concatenate(([c[0]], c[:-1])) if len(c) else c
    tr = np.maximum.reduce([h - l, np.abs(h - prev_close), np.abs(l - prev_close)])
    return tr


def atr_series(high, low, close, length: int) -> list[float | None]:
    """Simple (SMA-based) ATR series aligned to input length."""
    if len(close) == 0:
        return []
    tr = true_range(high, low, close)
    n = len(tr)
    out: list[float | None] = [None] * n
    if n < length or length <= 0:
        return out
    csum = np.cumsum(np.insert(tr, 0, 0.0))
    for i in range(length - 1, n):
        out[i] = round(float((csum[i + 1] - csum[i + 1 - length]) / length), 6)
    return out


def atr_last(high, low, close, length: int) -> float | None:
    s = atr_series(high, low, close, length)
    return s[-1] if s and s[-1] is not None else None


def high_52w(highs: Sequence[float], window: int = WEEK52) -> float | None:
    seg = np.asarray(highs[-window:], dtype=float)
    seg = seg[np.isfinite(seg)]
    return round(float(seg.max()), 4) if seg.size else None


def low_52w(lows: Sequence[float], window: int = WEEK52) -> float | None:
    seg = np.asarray(lows[-window:], dtype=float)
    seg = seg[np.isfinite(seg)]
    return round(float(seg.min()), 4) if seg.size else None


def rs_line(stock_close: Sequence[float], bench_close: Sequence[float]) -> list[float | None]:
    """Relative-strength line = stock / benchmark, aligned to the shorter tail.

    The two series are trimmed to a common length from the right (most recent),
    which is what we want since both are daily closes ending "today".
    """
    n = min(len(stock_close), len(bench_close))
    if n == 0:
        return []
    s = np.asarray(stock_close[-n:], dtype=float)
    b = np.asarray(bench_close[-n:], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        rl = np.where(b != 0, s / b, np.nan)
    return [None if not math.isfinite(v) else round(float(v), 8) for v in rl]


def near_rolling_high(series: Sequence[float | None], window: int, ratio: float) -> bool | None:
    """True if the last value is >= rolling max over ``window`` * ``ratio``."""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    tail = vals[-window:] if len(vals) >= window else vals
    last = vals[-1]
    peak = max(tail)
    if peak <= 0:
        return None
    return last >= peak * ratio


# --------------------------------------------------------------------------- #
# Minervini Trend Template
# --------------------------------------------------------------------------- #
def trend_template(
    price: float,
    sma50: float | None,
    sma150: float | None,
    sma200: float | None,
    sma200_20d_ago: float | None,
    high52: float | None,
    low52: float | None,
    rs_percentile: float | None,
    *,
    min_rs_percentile: float = 80,
    min_vs_low: float = 1.30,
    min_vs_high: float = 0.75,
) -> dict:
    """Evaluate the 8+2 Minervini trend-template conditions.

    Any condition whose inputs are NaN/None counts as False (not a crash), per
    the "NaN -> 0점" rule. Returns per-condition booleans, the pass count, and
    the overall boolean (all conditions true).
    """
    def ok(cond) -> bool:
        return bool(cond) if cond is not None else False

    conds = {
        "price_above_sma150": ok(sma150 is not None and price > sma150),
        "price_above_sma200": ok(sma200 is not None and price > sma200),
        "sma150_above_sma200": ok(sma150 is not None and sma200 is not None and sma150 > sma200),
        "sma200_rising": ok(sma200 is not None and sma200_20d_ago is not None and sma200 > sma200_20d_ago),
        "sma50_above_sma150": ok(sma50 is not None and sma150 is not None and sma50 > sma150),
        "sma50_above_sma200": ok(sma50 is not None and sma200 is not None and sma50 > sma200),
        "price_above_sma50": ok(sma50 is not None and price > sma50),
        "above_52w_low": ok(low52 is not None and price >= low52 * min_vs_low),
        "near_52w_high": ok(high52 is not None and price >= high52 * min_vs_high),
        "rs_percentile_ok": ok(rs_percentile is not None and rs_percentile >= min_rs_percentile),
    }
    passed = sum(1 for v in conds.values() if v)
    return {
        "conditions": conds,
        "pass_count": passed,
        "total": len(conds),
        "trend_template_pass": passed == len(conds),
    }
