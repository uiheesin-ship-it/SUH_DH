"""Trough-anchored base-window search for the turnaround (bottom base) screener.

Why not reuse ``app.base.detect.detect_base``: that one anchors the base to the
LAST bar and grows the window until depth would exceed ``max_depth``. Depth is
monotonically non-decreasing in window length, so the widest passing window is
unique and cheap to find — but only a *cliff* stops the growth. A stock that
slid down gently (no cliff) keeps growing until it hits ``max_length_days``, and
the resulting window swallows the decline. That matters far more here than for
the base screener, whose uptrend pre-filter means such names never reach it.

So instead: sweep candidate lengths and validate each against its OWN low —
the low has to sit in the front of the window (``low_early_frac``), or the stock
is still making lows rather than basing. Each surviving window is scored
downstream (quality + right edge) and the best-scoring one wins; a gently
declining stock's over-long window fails ``min_recovery`` (its right side is a
low shelf, not a recovered right edge) while the correct shorter window passes,
so the sweep self-corrects.

The 252-day trough (``find_trough``) is tracked separately and is NOT required
to fall inside the window. It cannot be: a stock that bottomed, bounced 25%, and
then built a 50-day base above the low has a perfectly good base that does not
contain the bottom, and demanding otherwise would reject every "first base off
the low". The trough's job here is to be the origin for the quality metrics —
those read from ``max(trough, base_start)`` forward, so the decline can never
leak into them regardless of which of the two comes later.

Look-ahead safety: everything here reads closed bars only, and every window ends
at the last bar (we only ever look for a base that is live *right now*).
"""

from __future__ import annotations

import math

import numpy as np

from ..flat import metrics as fmetrics
from .config import PERIODS


def _finite_min(a) -> float | None:
    arr = np.asarray(a, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(arr.min()) if arr.size else None


def _finite_max(a) -> float | None:
    arr = np.asarray(a, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(arr.max()) if arr.size else None


def find_trough(lows, cfg: dict) -> int | None:
    """Absolute index of the bar where the bottom was FORMED.

    Not ``argmin``: on a double bottom ($10.00 then $9.98) argmin returns the
    right-hand low, which is not when the bottom was made and would push the
    measured low far to the right of the base. We take the FIRST bar within
    ``tolerance`` of the running low instead, so a double bottom anchors on its
    left foot and a one-tick undercut doesn't move the anchor.
    """
    tcfg = cfg["trough"]
    lookback = int(tcfg["lookback"])
    tol = float(tcfg["tolerance"])

    a = np.asarray(lows, dtype=float)
    n = a.size
    if n == 0:
        return None
    start = max(0, n - lookback)
    win = a[start:]
    lo_min = _finite_min(win)
    if lo_min is None or lo_min <= 0:
        return None
    cutoff = lo_min * (1.0 + tol)
    for i in range(win.size):
        v = win[i]
        if np.isfinite(v) and v <= cutoff:
            return start + i
    return None


def _window_low_idx(lows, start: int, tol: float) -> int | None:
    """Index of the window's low, using the same first-touch-within-tolerance
    rule as ``find_trough`` so a double bottom anchors on its left foot."""
    seg = np.asarray(lows[start:], dtype=float)
    lo = _finite_min(seg)
    if lo is None or lo <= 0:
        return None
    cutoff = lo * (1.0 + tol)
    for i in range(seg.size):
        if np.isfinite(seg[i]) and seg[i] <= cutoff:
            return start + i
    return None


def evaluate_window(closes, highs, lows, L: int, trough_idx: int,
                    cfg: dict) -> dict | None:
    """Validate one candidate base length. Returns geometry, or None if invalid.

    The window is ``closes[n-L:]`` — it always ends today. Rejections, in order
    of how much they cost to check:

    1. the window's own low sits too far right (``low_early_frac``) — the stock
       is still making lows, which is a decline, not a base
    2. depth outside [min_depth, max_depth]
    3. right side hasn't recovered into the band (``min_recovery``) — this is
       what rejects an over-long window that swallowed a gentle decline: its
       right side is a low shelf sitting near the window's floor.

    ``trough_idx`` is carried through for the quality origin but is deliberately
    not required to be inside the window — see the module docstring.
    """
    b = cfg["base"]
    n = len(closes)
    if L < int(b["min_length_days"]) or L > int(b["max_length_days"]) or L > n:
        return None

    start = n - L
    low_idx = _window_low_idx(lows, start, float(cfg["trough"]["tolerance"]))
    if low_idx is None:
        return None
    low_pos = (low_idx - start) / float(L)
    if low_pos > float(b["low_early_frac"]):
        return None

    win_high = _finite_max(highs[start:])
    win_low = _finite_min(lows[start:])
    if win_high is None or win_low is None or win_high <= 0 or win_low <= 0:
        return None
    depth = (win_high - win_low) / win_high
    if depth < float(b["min_depth"]) or depth > float(b["max_depth"]):
        return None

    span = win_high - win_low
    last = closes[-1]
    if span <= 0 or last is None or not math.isfinite(last):
        return None
    recovery = (last - win_low) / span
    if recovery < float(b["min_recovery"]):
        return None

    win_closes = list(closes[start:])
    # A base goes sideways. A window sliced out of a vertical advance passes
    # every test above — its low is at the left, its "recovery" is 1.0, its
    # depth is modest — so the regression drift has to rule it out explicitly.
    drift = fmetrics.base_drift(win_closes)
    if drift is not None and drift > float(b["max_drift"]):
        return None

    med = fmetrics.median(win_closes)
    q10 = fmetrics.quantile(win_closes, 0.10)
    q90 = fmetrics.quantile(win_closes, 0.90)
    daily_vol = fmetrics.mean_abs_daily_return(win_closes)
    min_vol = float(cfg.get("min_base_daily_vol") or 0)
    too_dead = bool(min_vol and daily_vol is not None and daily_vol < min_vol)

    # Diagnostic only (NOT a gate): how hard the first third of the window
    # declines. A steep value on an otherwise valid window means the left edge
    # is the descending side of a cup — legitimate, and the reason this is not
    # a rejection rule. Surfaced so a chart-reader can sanity-check the window.
    third = max(3, L // 3)
    front_drift = fmetrics.base_drift(win_closes[:third])

    return {
        "base_days": int(L),
        "base_start_idx": int(start),
        # Origin for every quality metric: whichever of the 252-day trough and
        # the window start comes later, so the decline is outside the
        # measurement no matter which shape the base has.
        "trough_idx": int(max(trough_idx, start)),
        "global_trough_idx": int(trough_idx),
        "base_low_idx": int(low_idx),
        "low_offset": int(low_idx - start),
        "low_position": round(low_pos, 4),
        "base_high": round(win_high, 4),
        "base_low": round(win_low, 4),
        "base_depth": round(depth, 4),
        "base_recovery": round(recovery, 4),
        "base_median": round(med, 4) if med is not None else None,
        "base_low_q10": round(q10, 4) if q10 is not None else None,
        "base_high_q90": round(q90, 4) if q90 is not None else None,
        "base_drift": round(drift, 4) if drift is not None else None,
        "base_daily_vol": round(daily_vol, 5) if daily_vol is not None else None,
        "too_dead": too_dead,
        "front_third_drift": round(front_drift, 4) if front_drift is not None else None,
    }


def select_windows(closes, highs, lows, cfg: dict) -> list[dict]:
    """Every valid base window for this ticker, shortest first.

    Returns [] when there is no trough anchor or no length is consistent with
    it. The caller scores each window and keeps the best; ordering here is only
    for deterministic tie-breaking.
    """
    trough_idx = find_trough(lows, cfg)
    if trough_idx is None:
        return []
    out = []
    for L in PERIODS:
        w = evaluate_window(closes, highs, lows, L, trough_idx, cfg)
        if w is not None and not w["too_dead"]:
            out.append(w)
    return out
