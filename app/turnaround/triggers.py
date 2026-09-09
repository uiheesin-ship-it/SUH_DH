"""First-turn triggers — the events that mark a bottom base changing direction.

These are scanned across a recent window, not just today, and each carries the
bar index where it fired so the UI can show freshness. Worth 10 points total,
which is deliberately small: a trigger on a base that has already run is not a
buy, so the extension test in edge.py still governs. The combination this
screener is built around is "a trigger fired AND the name is not extended yet".

An earnings gap is included even though the fundamentals themselves are kept out
of the score. The reasoning the user set out: once results have visibly turned,
the chart is usually gone — but a gap up out of a bottom base on the day of the
print is the first move, not the last, and it is the one fundamental event early
enough to be tradeable.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from ..base.inbase import _pocket_pivot
from ..base import metrics as bmetrics

# How far back to scan for a trigger. Anything older than this is stale for our
# purposes; ``fresh_days`` (config) marks the subset shown as "fresh".
_SCAN_DAYS = 15


def _finite(a) -> np.ndarray:
    return np.asarray(a, dtype=float)


def power_bar(closes, highs, lows, volume, cfg: dict) -> int | None:
    """Bar index of the most recent demand bar: heavy volume, big up close, and
    closing near the high of its own range (so a big reversal-down day whose
    volume happens to be huge does not qualify)."""
    t = cfg["triggers"]
    vol_mult = float(t["power_bar_vol_mult"])
    min_ret = float(t["power_bar_min_ret"])
    loc_min = float(t["power_bar_close_loc"])

    c = _finite(closes); h = _finite(highs); l = _finite(lows); v = _finite(volume)
    n = min(c.size, h.size, l.size, v.size)
    if n < 60:
        return None
    found = None
    for i in range(max(50, n - _SCAN_DAYS), n):
        if i < 51:
            continue
        prev = c[i - 1]
        if not (math.isfinite(prev) and prev > 0):
            continue
        ret = c[i] / prev - 1.0
        if not math.isfinite(ret) or ret < min_ret:
            continue
        vol50 = v[i - 50:i]
        vol50 = vol50[np.isfinite(vol50)]
        if vol50.size == 0 or vol50.mean() <= 0:
            continue
        if v[i] < vol50.mean() * vol_mult:
            continue
        rng = h[i] - l[i]
        loc = (c[i] - l[i]) / rng if rng > 0 else 1.0
        if loc < loc_min:
            continue
        found = i
    return found


def reclaim_200(closes, cfg: dict) -> int | None:
    """Bar index of the first cross back above a 200-day the stock had been
    under for ``reclaim_below_days``. The "first" qualifier is what makes this a
    turn signal rather than a trend-following one."""
    t = cfg["triggers"]
    below_days = int(t["reclaim_below_days"])
    sma200 = bmetrics.sma_series(closes, 200)
    n = len(closes)
    if n < 200 + below_days:
        return None
    found = None
    for i in range(max(200, n - _SCAN_DAYS), n):
        ma_now, ma_prev = sma200[i], sma200[i - 1]
        if ma_now is None or ma_prev is None:
            continue
        if not (closes[i] > ma_now and closes[i - 1] <= ma_prev):
            continue
        # ... and it must have been genuinely below, not oscillating across.
        lo = max(0, i - below_days)
        prior = [closes[j] for j in range(lo, i) if sma200[j] is not None]
        prior_ma = [sma200[j] for j in range(lo, i) if sma200[j] is not None]
        if not prior:
            continue
        below_frac = sum(1 for p, m in zip(prior, prior_ma) if p < m) / len(prior)
        if below_frac >= 0.9:
            found = i
    return found


def rs_new_high(closes, bench_closes, base_start_idx: int) -> bool:
    """RS line at its highest point of the base window — the stock is starting
    to outperform, which usually leads price out of a bottom base."""
    if not bench_closes:
        return False
    rl = bmetrics.rs_line(closes, bench_closes)
    if not rl:
        return False
    offset = len(closes) - len(rl)
    start = max(0, base_start_idx - offset)
    seg = [v for v in rl[start:] if v is not None]
    if len(seg) < 10:
        return False
    return seg[-1] >= max(seg) * 0.999


def earnings_gap(closes, volume, dates, earnings_dates, cfg: dict) -> int | None:
    """Bar index of a big, high-volume up move on (or right after) a reporting
    date. ``earnings_dates`` is a list of YYYY-MM-DD strings; when it is empty
    this returns None rather than guessing."""
    if not earnings_dates or not dates:
        return None
    t = cfg["triggers"]
    min_move = float(t["earnings_gap_min"])
    vol_mult = float(t["earnings_gap_vol_mult"])
    window = int(t["earnings_window_days"])

    # Bars are trading days; a report can land on a weekend or a holiday, so
    # bisect to the first session on or after the date rather than requiring an
    # exact match (which would silently drop those reports).
    day_list = [str(d)[:10] for d in dates]
    c = _finite(closes); v = _finite(volume)
    found = None
    for ed in earnings_dates:
        key = str(ed)[:10]
        base_i = bisect.bisect_left(day_list, key)
        if base_i >= len(day_list):
            continue
        for i in range(base_i, min(base_i + window, len(closes))):
            if i < 51 or i >= c.size or i >= v.size:
                continue
            prev = c[i - 1]
            if not (math.isfinite(prev) and prev > 0):
                continue
            if c[i] / prev - 1.0 < min_move:
                continue
            vol50 = v[i - 50:i]
            vol50 = vol50[np.isfinite(vol50)]
            if vol50.size == 0 or vol50.mean() <= 0:
                continue
            if v[i] >= vol50.mean() * vol_mult:
                found = i if found is None else max(found, i)
    return found


def compute(closes, highs, lows, volume, dates, window: dict, cfg: dict,
            bench_closes=None, earnings_dates=None) -> dict:
    t = cfg["triggers"]
    n = len(closes)
    fresh_days = int(t["fresh_days"])

    hits: list[tuple[str, int]] = []
    pb = power_bar(closes, highs, lows, volume, cfg)
    if pb is not None:
        hits.append(("power_bar", pb))
    rc = reclaim_200(closes, cfg)
    if rc is not None:
        hits.append(("reclaim_200", rc))
    eg = earnings_gap(closes, volume, dates, earnings_dates or [], cfg)
    if eg is not None:
        hits.append(("earnings_gap", eg))
    if _pocket_pivot(list(closes), list(volume), int(t["pocket_pivot_lookback"])):
        hits.append(("pocket_pivot", n - 1))
    if rs_new_high(closes, bench_closes, int(window["base_start_idx"])):
        hits.append(("rs_new_high", n - 1))

    names = [h[0] for h in hits]
    newest = max((h[1] for h in hits), default=None)
    age = (n - 1 - newest) if newest is not None else None
    fresh = bool(age is not None and age <= fresh_days)

    # Score: one fresh trigger is most of the credit, a second adds the rest.
    # Stale triggers still count for a little — the turn happened, just earlier.
    weight = float(cfg["score"]["trigger_weight"])
    if not hits:
        pts = 0.0
    elif fresh:
        pts = weight * min(1.0, 0.7 + 0.3 * (len(hits) - 1))
    else:
        pts = weight * 0.35

    return {
        "triggers": names,
        "trigger_count": len(hits),
        "trigger_newest_age": age,
        "trigger_fresh": fresh,
        "trigger_date": (dates[newest] if newest is not None and newest < len(dates)
                         else None),
        "trigger_score": round(pts, 2),
    }
