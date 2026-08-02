"""Pure flatness math for the Flat Base Screener.

Every function here is a pure function of a price series so they can be unit
tested fully offline. All are defended against NaN / inf / divide-by-zero and
never raise on degenerate input — they return None or a safe 0/1 instead, so one
odd ticker can never abort a scan.

Prices are expected to be *adjusted* closes (split/dividend consistent) — the
same auto_adjust=True bars used everywhere else in the project — so a dividend
step does not masquerade as base drift.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def _arr(x: Sequence[float]) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[np.isfinite(a)]


def quantile(values: Sequence[float], q: float) -> float | None:
    a = _arr(values)
    if a.size == 0:
        return None
    return float(np.quantile(a, q))


def median(values: Sequence[float]) -> float | None:
    a = _arr(values)
    return float(np.median(a)) if a.size else None


def close_band(closes: Sequence[float]) -> float | None:
    """(Q90 - Q10) / median(close). Uses close quantiles (not raw high/low) so a
    single-day wick can't inflate the band. Smaller => tighter/flatter."""
    a = _arr(closes)
    if a.size < 2:
        return None
    med = float(np.median(a))
    if not med or med <= 0:
        return None
    q10 = float(np.quantile(a, 0.10))
    q90 = float(np.quantile(a, 0.90))
    band = (q90 - q10) / med
    return float(band) if math.isfinite(band) else None


def raw_high_low_range(high: Sequence[float], low: Sequence[float],
                       closes: Sequence[float]) -> float | None:
    """(max(high) - min(low)) / median(close). Shown for context; NOT a Flatness
    Score input (wicks make it noisier than the close band)."""
    h = _arr(high)
    l = _arr(low)
    med = median(closes)
    if h.size == 0 or l.size == 0 or not med or med <= 0:
        return None
    rng = (float(h.max()) - float(l.min())) / med
    return float(rng) if math.isfinite(rng) else None


def regression_slope(closes: Sequence[float]) -> float | None:
    """Ordinary-least-squares slope of log(close) vs day index (0..n-1).

    We use OLS (pure numpy, no scipy) rather than Theil-Sen; the per-day outlier
    control (outlier_ratio) already guards against one wild bar dominating, and
    the base windows are short. Slope is in log-price per day."""
    a = np.asarray(closes, dtype=float)
    mask = np.isfinite(a) & (a > 0)
    a = a[mask]
    n = a.size
    if n < 3:
        return None
    y = np.log(a)
    x = np.arange(n, dtype=float)
    xm = x.mean()
    denom = float(((x - xm) ** 2).sum())
    if denom <= 0:
        return None
    slope = float(((x - xm) * (y - y.mean())).sum() / denom)
    return slope if math.isfinite(slope) else None


def base_drift(closes: Sequence[float]) -> float | None:
    """exp(slope * (base_days - 1)) - 1 — the fractional move of the regression
    trend line from the first to the last day of the base. |drift| small =>
    horizontal. Sign shows a gently rising (+) or falling (-) base."""
    a = np.asarray(closes, dtype=float)
    n = int(np.isfinite(a).sum())
    slope = regression_slope(closes)
    if slope is None or n < 2:
        return None
    drift = math.exp(slope * (n - 1)) - 1.0
    return float(drift) if math.isfinite(drift) else None


def containment_ratio(closes: Sequence[float], pct: float = 0.075) -> float | None:
    """Fraction of closes within median*(1-pct) .. median*(1+pct). Higher =>
    price stays glued to the base centre."""
    a = _arr(closes)
    if a.size == 0:
        return None
    med = float(np.median(a))
    if not med or med <= 0:
        return None
    lo = med * (1.0 - pct)
    hi = med * (1.0 + pct)
    inside = int(np.count_nonzero((a >= lo) & (a <= hi)))
    return float(inside) / float(a.size)


def center_shift(closes: Sequence[float]) -> float | None:
    """abs(second_half_median / first_half_median - 1). A tight band can still be
    drifting; this catches a base whose centre keeps marching up or down."""
    a = _arr(closes)
    n = a.size
    if n < 4:
        return None
    half = n // 2
    first = a[:half]
    second = a[n - half:]
    m1 = float(np.median(first))
    m2 = float(np.median(second))
    if not m1 or m1 <= 0:
        return None
    shift = abs(m2 / m1 - 1.0)
    return float(shift) if math.isfinite(shift) else None


def daily_returns(closes: Sequence[float]) -> np.ndarray:
    a = np.asarray(closes, dtype=float)
    if a.size < 2:
        return np.array([], dtype=float)
    prev = a[:-1]
    cur = a[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev != 0, cur / prev - 1.0, np.nan)
    return r[np.isfinite(r)]


def outlier_days(closes: Sequence[float], thresh: float = 0.08) -> int:
    """Count of days whose |close-to-close return| >= thresh (default 8%)."""
    r = daily_returns(closes)
    if r.size == 0:
        return 0
    return int(np.count_nonzero(np.abs(r) >= thresh))


def outlier_ratio(closes: Sequence[float], thresh: float = 0.08) -> float | None:
    """outlier_days / number-of-return-observations. A day or two of jumps is
    tolerated; repeated big moves are not a flat base."""
    r = daily_returns(closes)
    if r.size == 0:
        return None
    return float(np.count_nonzero(np.abs(r) >= thresh)) / float(r.size)


def current_position(current_close: float, closes: Sequence[float]) -> float | None:
    """(current - Q10) / (Q90 - Q10): where price sits inside the base band,
    ~0 at the floor, ~1 at the ceiling. Guarded against a near-zero band."""
    a = _arr(closes)
    if a.size < 2 or current_close is None or not math.isfinite(current_close):
        return None
    q10 = float(np.quantile(a, 0.10))
    q90 = float(np.quantile(a, 0.90))
    span = q90 - q10
    med = float(np.median(a))
    # Guard: a degenerate band (essentially a flat line) has no meaningful
    # position — treat as mid-band rather than dividing by ~0.
    if span <= 0 or (med and span / med < 1e-4):
        return 0.5
    pos = (current_close - q10) / span
    return float(pos) if math.isfinite(pos) else None


def max_abs_rolling_return(closes: Sequence[float], lookback: int) -> float | None:
    """max over the series of abs(close / close.shift(lookback) - 1)."""
    a = np.asarray(closes, dtype=float)
    if a.size <= lookback:
        return None
    cur = a[lookback:]
    prev = a[:-lookback]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev > 0, cur / prev - 1.0, np.nan)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return None
    return float(np.max(np.abs(r)))
