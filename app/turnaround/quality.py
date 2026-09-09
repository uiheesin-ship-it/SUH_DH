"""Base quality — four axes, measured from the trough forward.

Deliberately pattern-agnostic. Branching on a named pattern ("is this a VCP? is
this a flat base?") finds exactly the patterns you enumerated and silently drops
everything else, which is the opposite of what this screener wants: the base
that has no name is still a base. So we score four properties every constructive
base shares, whatever it looks like:

    contraction  the range narrows as the base matures
    support      lows hold — no undercut of the bottom, rising lows
    dry-up       volume recedes while it builds
    containment  closes cluster around the base's centre

Every axis reads ``closes[trough_idx:]`` (the post-trough segment), never the
whole window. That is the load-bearing decision here: a window whose left edge
reaches back into the decline would make all four axes pass for the wrong reason
— a downtrend's wide early range makes any later quiet stretch look like textbook
contraction, and its heavy selling volume makes any later lull look like dry-up.
Anchoring on the trough means the decline cannot leak into the measurement even
if the window itself is a little too wide.
"""

from __future__ import annotations

import math

import numpy as np

from ..flat import metrics as fmetrics

# Post-trough bars needed before an axis is meaningful; below this the axis
# returns None and scores neutral rather than fabricating a number.
_MIN_SEGMENT = 9


def _ramp(x: float | None, full: float, zero: float) -> float | None:
    """Linear 0..1 credit. ``full`` scores 1.0, ``zero`` scores 0.0; the two may
    be given in either order so a metric can be better-when-low or -when-high."""
    if x is None or not math.isfinite(x):
        return None
    if full == zero:
        return None
    t = (x - zero) / (full - zero)
    return float(min(1.0, max(0.0, t)))


def _avg(a) -> float | None:
    arr = np.asarray(a, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(arr.mean()) if arr.size else None


def _daily_range_pct(highs, lows, closes) -> np.ndarray:
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(h.size, l.size, c.size)
    if n == 0:
        return np.array([], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(c[:n] > 0, (h[:n] - l[:n]) / c[:n], np.nan)
    return r


def contraction(highs, lows, closes, cfg: dict) -> float | None:
    """Late-third average daily range / early-third average. Lower = tightening.

    Thirds of the *post-trough* segment, not of the base window — see module
    docstring. Uses average daily range rather than the high-low envelope so one
    spike bar cannot define a third.
    """
    rng = _daily_range_pct(highs, lows, closes)
    rng = rng[np.isfinite(rng)]
    n = rng.size
    if n < _MIN_SEGMENT:
        return None
    third = n // 3
    if third < 2:
        return None
    early = _avg(rng[:third])
    late = _avg(rng[-third:])
    if early is None or late is None or early <= 0:
        return None
    ratio = late / early
    return float(ratio) if math.isfinite(ratio) else None


def support(lows) -> dict:
    """Do the lows hold as the base builds?

    Two readings on the post-trough segment:
      undercut    how far the LAST third dug below the low of the earlier two
      higher_low  second half's low above the first half's

    ``undercut`` is measured against the earlier part of the segment rather than
    against the segment's own minimum. Measuring against the minimum can only
    ever return zero — the minimum is, by definition, not undercut by anything
    in the same series — which would leave the axis reading a constant.
    """
    a = np.asarray(lows, dtype=float)
    a = a[np.isfinite(a)]
    n = a.size
    out = {"undercut": None, "higher_low": None}
    # Same floor as the other axes: "the lows are holding" read off four bars is
    # noise, and reporting it as a real score while the other three axes go
    # neutral skews the total on short history.
    if n < _MIN_SEGMENT:
        return out

    cut = (n * 2) // 3
    early_low = float(a[:cut].min())
    late_low = float(a[cut:].min())
    if early_low > 0:
        out["undercut"] = float(max(0.0, (early_low - late_low) / early_low))

    half = n // 2
    first_low = float(a[:half].min()) if half else None
    second_low = float(a[n - half:].min()) if half else None
    if first_low and second_low and first_low > 0:
        out["higher_low"] = float(second_low / first_low - 1.0)
    return out


def dry_up(volume, cfg: dict) -> float | None:
    """Recent 10-day average volume / 50-day average. Below 1.0 = drying up."""
    v = np.asarray(volume, dtype=float)
    v = v[np.isfinite(v) & (v >= 0)]
    if v.size < 50:
        return None
    recent = _avg(v[-10:])
    base = _avg(v[-50:])
    if recent is None or base is None or base <= 0:
        return None
    ratio = recent / base
    return float(ratio) if math.isfinite(ratio) else None


def compute(closes, highs, lows, volume, window: dict, cfg: dict) -> dict:
    """Score the four axes for one candidate window. Returns raw metrics plus a
    0..``quality_weight`` total, so screen.py can show both."""
    q = cfg["quality"]
    t = int(window["trough_idx"])

    seg_c = list(closes[t:])
    seg_h = list(highs[t:])
    seg_l = list(lows[t:])

    contr = contraction(seg_h, seg_l, seg_c, cfg)
    sup = support(seg_l)
    dry = dry_up(volume, cfg)
    cont = fmetrics.containment_ratio(seg_c) if len(seg_c) >= _MIN_SEGMENT else None

    s_contr = _ramp(contr, float(q["contraction_full"]), float(q["contraction_zero"]))
    s_dry = _ramp(dry, float(q["dryup_full"]), float(q["dryup_zero"]))
    s_cont = _ramp(cont, float(q["containment_floor"]) + float(q["containment_span"]),
                   float(q["containment_floor"]))

    # Support: a late undercut is the disqualifying half (a base still taking out
    # its own lows is not holding), rising lows are the bonus half.
    und = sup.get("undercut")
    hl = sup.get("higher_low")
    s_und = _ramp(und, 0.0, 0.05) if und is not None else None      # 5% undercut -> 0
    s_hl = _ramp(hl, 0.05, -0.05) if hl is not None else None       # +5% lows -> full
    parts = [p for p in (s_und, s_hl) if p is not None]
    s_sup = (0.65 * s_und + 0.35 * s_hl) if (s_und is not None and s_hl is not None) \
        else (sum(parts) / len(parts) if parts else None)

    def _pts(score: float | None, weight: float) -> float:
        # A missing axis scores neutral (half marks) instead of zero, so a short
        # history is not silently punished as if it were a bad base.
        return float(weight) * (0.5 if score is None else score)

    pts = (
        _pts(s_contr, q["contraction_weight"])
        + _pts(s_sup, q["support_weight"])
        + _pts(s_dry, q["dryup_weight"])
        + _pts(s_cont, q["containment_weight"])
    )

    return {
        "q_contraction_ratio": round(contr, 3) if contr is not None else None,
        "q_undercut": round(und, 4) if und is not None else None,
        "q_higher_low": round(hl, 4) if hl is not None else None,
        "q_dryup_ratio": round(dry, 3) if dry is not None else None,
        "q_containment": round(cont, 3) if cont is not None else None,
        "q_contraction_score": round(_pts(s_contr, q["contraction_weight"]), 2),
        "q_support_score": round(_pts(s_sup, q["support_weight"]), 2),
        "q_dryup_score": round(_pts(s_dry, q["dryup_weight"]), 2),
        "q_containment_score": round(_pts(s_cont, q["containment_weight"]), 2),
        "quality_score": round(pts, 2),
        "post_trough_days": len(seg_c),
    }
