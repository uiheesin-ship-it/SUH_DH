"""Right edge of the base — the 30-point axis, and the point of this screener.

A healthy bottom base is only actionable at its right edge: price up in the top
of the band, range tightening, resistance within reach. Three readings, blended:

    distance   how far to the level that has to break
    position   where the last close sits inside the base band
    tighten    is the recent range narrower than the base's own average

Two pivots, on purpose. A bottom base is deep by nature, so its own high can sit
20-30% overhead and "ready" would never fire on it. The level that actually gets
challenged first is the recent shelf — a cup's handle, a ledge under resistance.
So the *status* pivot is whichever of (base high, recent ledge) is nearer, while
the *extension* test that throws a name out stays anchored on the base high.
Anchoring exclusion on the ledge instead would eject a stock the moment it
cleared a 15-day high, which is precisely the first turn we are here to catch.
"""

from __future__ import annotations

import math

import numpy as np

# The ledge must be a level that already formed: taking the high through
# yesterday would let a single up-day define its own resistance.
_LEDGE_SETTLE_DAYS = 2


def _ramp(x: float | None, full: float, zero: float) -> float | None:
    if x is None or not math.isfinite(x) or full == zero:
        return None
    return float(min(1.0, max(0.0, (x - zero) / (full - zero))))


def _avg(a) -> float | None:
    arr = np.asarray(a, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(arr.mean()) if arr.size else None


def _range_pct(highs, lows, closes) -> np.ndarray:
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(h.size, l.size, c.size)
    if n == 0:
        return np.array([], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(c[:n] > 0, (h[:n] - l[:n]) / c[:n], np.nan)


def ledge_high(highs, cfg: dict) -> float | None:
    """Highest high of the recent shelf, ending ``_LEDGE_SETTLE_DAYS`` ago."""
    look = int(cfg["edge"]["ledge_lookback"])
    a = np.asarray(highs, dtype=float)
    if a.size < look + _LEDGE_SETTLE_DAYS:
        return None
    seg = a[-(look + _LEDGE_SETTLE_DAYS):-_LEDGE_SETTLE_DAYS]
    seg = seg[np.isfinite(seg)]
    return float(seg.max()) if seg.size else None


def compute(closes, highs, lows, window: dict, cfg: dict,
            sma50: float | None = None) -> dict:
    e = cfg["edge"]
    w = e["weights"]
    price = closes[-1]
    base_high = window.get("base_high")
    start = int(window["base_start_idx"])

    ledge = ledge_high(highs, cfg)
    # min(): the nearer level is the one that gets tested first. ledge is always
    # <= base_high (it is measured inside the window), so this picks the ledge
    # whenever one has formed, and falls back to the base high when it hasn't.
    if ledge is not None and base_high is not None:
        eff_pivot = min(base_high, ledge)
        pivot_kind = "ledge" if ledge < base_high else "base_high"
    else:
        eff_pivot = base_high
        pivot_kind = "base_high"

    distance = None
    if eff_pivot and eff_pivot > 0 and price:
        distance = (eff_pivot - price) / eff_pivot
    ext_vs_base = None
    if base_high and base_high > 0 and price:
        ext_vs_base = (price - base_high) / base_high

    max_ext = float(e["max_extension"])
    # Two independent ways to be past the entry. The first is relative to this
    # window; the second is not, which matters because a window drawn inside a
    # sustained advance has a nearby "base high" of its own and would otherwise
    # look like a right edge. Distance from the 50-day is shape-independent.
    stretch = (price / sma50) if (sma50 and sma50 > 0 and price) else None
    over_ma = bool(stretch is not None and stretch > float(e["max_sma50_stretch"]))
    extended = bool(ext_vs_base is not None and ext_vs_base > max_ext) or over_ma

    if extended:
        status = "extended"
    elif ext_vs_base is not None and ext_vs_base > 0:
        status = "broken_out"
    elif distance is None:
        status = "unknown"
    elif distance <= float(e["ready_threshold"]):
        # Covers price just above the ledge but still under the base high — the
        # spot this screener exists to find.
        status = "ready"
    elif distance <= float(e["watch_threshold"]):
        status = "watch"
    else:
        status = "early"

    # --- distance credit ------------------------------------------------
    if ext_vs_base is not None and ext_vs_base > 0:
        # Above the base high: credit decays with how far it has run.
        s_dist = _ramp(ext_vs_base, 0.0, float(e["extension_zero"]))
    elif distance is not None and distance < 0:
        # Through the ledge, still under the base high — full credit.
        s_dist = 1.0
    else:
        s_dist = _ramp(distance, 0.0, float(e["watch_threshold"]))

    # --- position inside the base band ----------------------------------
    q10 = window.get("base_low_q10")
    q90 = window.get("base_high_q90")
    position = None
    if q10 is not None and q90 is not None and q90 > q10:
        position = (price - q10) / (q90 - q10)
    s_pos = _ramp(position, float(e["position_full"]), float(e["min_position"]))

    # --- recent tightening vs the base's own average ---------------------
    base_rng = _range_pct(highs[start:], lows[start:], closes[start:])
    recent_rng = _range_pct(highs[-10:], lows[-10:], closes[-10:])
    base_avg = _avg(base_rng)
    recent_avg = _avg(recent_rng)
    tighten = (recent_avg / base_avg) if (base_avg and base_avg > 0
                                          and recent_avg is not None) else None
    s_tight = _ramp(tighten, float(e["tighten_full"]), float(e["tighten_zero"]))

    def _n(score):  # missing component -> neutral, never a silent zero
        return 0.5 if score is None else score

    weight = float(cfg["score"]["edge_weight"])
    pts = weight * (
        float(w["distance"]) * _n(s_dist)
        + float(w["position"]) * _n(s_pos)
        + float(w["tighten"]) * _n(s_tight)
    )

    return {
        "pivot_price": round(eff_pivot, 4) if eff_pivot else None,
        "pivot_kind": pivot_kind,
        "ledge_high": round(ledge, 4) if ledge is not None else None,
        "distance_to_pivot": round(distance, 4) if distance is not None else None,
        "extension_vs_base": round(ext_vs_base, 4) if ext_vs_base is not None else None,
        "pivot_status": status,
        "extended": extended,
        "sma50_stretch": round(stretch, 3) if stretch is not None else None,
        "extended_vs_sma50": over_ma,
        "base_position": round(position, 4) if position is not None else None,
        "tighten_ratio": round(tighten, 3) if tighten is not None else None,
        "edge_distance_score": round(weight * float(w["distance"]) * _n(s_dist), 2),
        "edge_position_score": round(weight * float(w["position"]) * _n(s_pos), 2),
        "edge_tighten_score": round(weight * float(w["tighten"]) * _n(s_tight), 2),
        "edge_score": round(pts, 2),
    }
