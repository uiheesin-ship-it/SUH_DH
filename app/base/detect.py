"""Base / VCP / volume-dry-up / pivot detection — quantified approximations.

These are NOT a substitute for reading a chart. Each function turns a stretch of
OHLCV into a handful of numbers a trader would eyeball (depth, contraction,
dry-up, distance to pivot). All thresholds come from config; all functions
tolerate short/NaN history by returning neutral results instead of raising.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def _finite(a) -> np.ndarray:
    arr = np.asarray(a, dtype=float)
    return arr


def _safe_max(a) -> float | None:
    arr = _finite(a)
    arr = arr[np.isfinite(arr)]
    return float(arr.max()) if arr.size else None


def _safe_min(a) -> float | None:
    arr = _finite(a)
    arr = arr[np.isfinite(arr)]
    return float(arr.min()) if arr.size else None


def _avg(a) -> float | None:
    arr = _finite(a)
    arr = arr[np.isfinite(arr)]
    return float(arr.mean()) if arr.size else None


# --------------------------------------------------------------------------- #
# Base detection
# --------------------------------------------------------------------------- #
def detect_base(high, low, close, dates: Sequence[str], cfg: dict) -> dict:
    """Find the current consolidation ("base") ending at the last bar.

    Since widening the window can only widen the high-low range, base depth is
    monotonically non-decreasing in window length. So the *longest* window whose
    depth stays within ``max_depth`` is the natural right boundary of the base;
    we clamp it to [min_length, max_length]. A window that is still too shallow
    (< min_depth) is reported but flagged ``base_detected=False``.
    """
    b = cfg["base"]
    min_len = int(b["min_length_days"])
    max_len = int(b["max_length_days"])
    min_depth = float(b["min_depth"])
    max_depth = float(b["max_depth"])

    n = len(close)
    empty = {
        "base_detected": False, "base_start_date": None, "base_end_date": None,
        "base_length_days": None, "base_high": None, "base_low": None,
        "base_depth": None, "base_depth_grade": "none", "higher_low": None,
    }
    if n < min_len:
        return empty

    upper = min(max_len, n)
    # Grow the window until adding another day would exceed max_depth.
    chosen = min_len
    for L in range(min_len, upper + 1):
        hi = _safe_max(high[-L:])
        lo = _safe_min(low[-L:])
        if hi is None or lo is None or hi <= 0:
            break
        depth = (hi - lo) / hi
        if depth <= max_depth:
            chosen = L
        else:
            break

    L = chosen
    hi = _safe_max(high[-L:])
    lo = _safe_min(low[-L:])
    if hi is None or lo is None or hi <= 0:
        return empty
    depth = (hi - lo) / hi

    grade = _depth_grade(depth, min_depth, max_depth)
    detected = min_depth <= depth <= max_depth and L >= min_len

    # Higher-low structure: is the low of the recent half above the low of the
    # earlier half? A gentle proxy for a constructive (rising-lows) base.
    half = L // 2
    early_low = _safe_min(low[-L:-half]) if half else None
    late_low = _safe_min(low[-half:]) if half else None
    higher_low = (
        bool(late_low > early_low) if (early_low is not None and late_low is not None) else None
    )

    start_idx = n - L
    return {
        "base_detected": bool(detected),
        "base_start_date": dates[start_idx] if 0 <= start_idx < len(dates) else None,
        "base_end_date": dates[-1] if dates else None,
        "base_length_days": int(L),
        "base_high": round(hi, 4),
        "base_low": round(lo, 4),
        "base_depth": round(depth, 4),
        "base_depth_grade": grade,
        "higher_low": higher_low,
    }


def _depth_grade(depth: float, min_depth: float, max_depth: float) -> str:
    if depth < min_depth:
        return "too_shallow"
    if depth <= 0.20:
        return "excellent"
    if depth <= 0.30:
        return "good"
    if depth <= max_depth:
        return "caution"
    return "too_deep"


# --------------------------------------------------------------------------- #
# Pivot / breakout readiness
# --------------------------------------------------------------------------- #
def pivot_analysis(price: float, base: dict, high, close, volume, vol50: float | None,
                   cfg: dict) -> dict:
    """Pivot price, distance and status; plus a breakout signal for today."""
    b = cfg["base"]
    ready = float(b["pivot_ready_threshold"])
    watch = float(b["pivot_watch_threshold"])
    ext = float(b["breakout_extended_threshold"])

    base_high = base.get("base_high")
    # Secondary "tight area" pivot: the recent 10-day high (a handle/ledge).
    recent_high_10 = _safe_max(high[-10:]) if len(high) >= 1 else None
    pivot = base_high
    if pivot is None:
        return {
            "pivot_price": None, "distance_to_pivot": None, "pivot_status": "none",
            "recent_high_10d": recent_high_10, "breakout_signal": False,
            "breakout_volume_ratio": None,
        }

    distance = (pivot - price) / pivot if pivot else None

    if price > pivot * (1 + ext):
        status = "extended"
    elif price > pivot:
        status = "broken_out"
    elif distance is not None and distance <= ready:
        status = "ready"
    elif distance is not None and distance <= watch:
        status = "watch"
    else:
        status = "early"

    today_vol = float(volume[-1]) if len(volume) and math.isfinite(volume[-1]) else None
    vol_ratio = (today_vol / vol50) if (today_vol and vol50) else None
    thr = float(cfg["volume"]["high_volume_down_day_threshold"])
    breakout_signal = bool(
        price > pivot and vol_ratio is not None and vol_ratio >= thr
        and len(close) and close[-1] > pivot
    )

    return {
        "pivot_price": round(pivot, 4),
        "distance_to_pivot": round(distance, 4) if distance is not None else None,
        "pivot_status": status,
        "recent_high_10d": round(recent_high_10, 4) if recent_high_10 else None,
        "breakout_signal": breakout_signal,
        "breakout_volume_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
    }


# --------------------------------------------------------------------------- #
# VCP structure (3-stage range contraction)
# --------------------------------------------------------------------------- #
def vcp_structure(high, low, base: dict, cfg: dict) -> dict:
    """Split the base into thirds and measure whether the range contracts."""
    v = cfg["volatility"]
    pass_ratio = float(v["vcp_pass_ratio"])
    exc_ratio = float(v["vcp_excellent_ratio"])
    L = base.get("base_length_days")
    out = {
        "vcp_range_1": None, "vcp_range_2": None, "vcp_range_3": None,
        "vcp_pattern_pass": False, "vcp_score": 0.0,
    }
    if not L or L < 6:
        return out
    seg = L // 3
    if seg < 2:
        return out
    h = list(high[-L:])
    l = list(low[-L:])

    def rng(hs, ls):
        hi = _safe_max(hs)
        lo = _safe_min(ls)
        if hi is None or lo is None or hi <= 0:
            return None
        return (hi - lo) / hi

    r1 = rng(h[:seg], l[:seg])
    r2 = rng(h[seg:2 * seg], l[seg:2 * seg])
    r3 = rng(h[2 * seg:], l[2 * seg:])
    out["vcp_range_1"] = round(r1, 4) if r1 is not None else None
    out["vcp_range_2"] = round(r2, 4) if r2 is not None else None
    out["vcp_range_3"] = round(r3, 4) if r3 is not None else None
    if r1 is None or r2 is None or r3 is None or r1 <= 0:
        return out

    monotonic = r1 > r2 > r3
    ratio_31 = r3 / r1
    out["vcp_pattern_pass"] = bool(monotonic and ratio_31 <= pass_ratio)

    # Score 0..1: reward monotonic contraction and a tight final leg.
    score = 0.0
    if monotonic:
        score += 0.4
    if ratio_31 <= exc_ratio:
        score += 0.6
    elif ratio_31 <= pass_ratio:
        score += 0.35
    elif ratio_31 <= 1.0:
        score += 0.15 * (1 - (ratio_31 - pass_ratio) / (1 - pass_ratio))
    out["vcp_score"] = round(min(1.0, score), 3)
    return out


# --------------------------------------------------------------------------- #
# ATR / range contraction across the base
# --------------------------------------------------------------------------- #
def volatility_contraction(atr_series_vals, daily_range_pct, base: dict, cfg: dict,
                           atr10: float | None, atr50: float | None,
                           recent_range10: float | None, recent_range50: float | None) -> dict:
    v = cfg["volatility"]
    atr_thr = float(v["atr_contraction_threshold"])
    atr_exc = float(v["atr_contraction_excellent"])
    rng_thr = float(v["range_contraction_threshold"])
    comp = float(v["recent_atr_compression"])

    L = base.get("base_length_days")
    atr_ratio = None
    rng_ratio = None
    if L and L >= 6:
        third = L // 3
        if third >= 2:
            atr_tail = [x for x in atr_series_vals[-L:] if x is not None]
            if len(atr_tail) >= 2 * third:
                early_atr = _avg(atr_tail[:third])
                late_atr = _avg(atr_tail[-third:])
                if early_atr and early_atr > 0 and late_atr is not None:
                    atr_ratio = late_atr / early_atr
            dr = list(daily_range_pct[-L:])
            early_r = _avg(dr[:third])
            late_r = _avg(dr[-third:])
            if early_r and early_r > 0 and late_r is not None:
                rng_ratio = late_r / early_r

    recent_atr_pass = (
        bool(atr10 is not None and atr50 not in (None, 0) and atr10 < atr50 * comp)
    )
    recent_range_pass = (
        bool(recent_range10 is not None and recent_range50 not in (None, 0)
             and recent_range10 < recent_range50 * comp)
    )

    atr_pass = atr_ratio is not None and atr_ratio <= atr_thr
    rng_pass = rng_ratio is not None and rng_ratio <= rng_thr
    passed = bool(atr_pass or rng_pass or (recent_atr_pass and recent_range_pass))

    if atr_ratio is not None and atr_ratio <= atr_exc:
        grade = "excellent"
    elif passed:
        grade = "good"
    else:
        grade = "weak"

    return {
        "atr_10": round(atr10, 4) if atr10 is not None else None,
        "atr_50": round(atr50, 4) if atr50 is not None else None,
        "atr_contraction_ratio": round(atr_ratio, 3) if atr_ratio is not None else None,
        "range_contraction_ratio": round(rng_ratio, 3) if rng_ratio is not None else None,
        "recent_atr_compression_pass": recent_atr_pass,
        "volatility_contraction_pass": passed,
        "volatility_contraction_grade": grade,
    }


# --------------------------------------------------------------------------- #
# Volume dry-up
# --------------------------------------------------------------------------- #
def volume_dry_up(close, volume, base: dict, cfg: dict) -> dict:
    vc = cfg["volume"]
    thr10 = float(vc["dry_up_10d_vs_50d"])
    thr5 = float(vc["dry_up_5d_vs_50d"])
    hv_move = float(vc["high_volume_down_day_move"])
    hv_mult = float(vc["high_volume_down_day_threshold"])

    vol = np.asarray(volume, dtype=float)
    v5 = _avg(vol[-5:])
    v10 = _avg(vol[-10:])
    v50 = _avg(vol[-50:])

    dry_ratio = (v10 / v50) if (v10 is not None and v50) else None
    dry_pass = bool(dry_ratio is not None and dry_ratio < thr10)
    dry_excellent = bool(v5 is not None and v50 and (v5 / v50) < thr5)

    # Base second half vs first half volume.
    L = base.get("base_length_days")
    base_half_pass = None
    if L and L >= 4:
        half = L // 2
        first = _avg(vol[-L:-half]) if half else None
        second = _avg(vol[-half:]) if half else None
        if first and second is not None:
            base_half_pass = bool(second < first * 0.80)

    # High-volume down days in the last 20 sessions.
    c = np.asarray(close, dtype=float)
    hv_down = 0
    if len(c) >= 21 and v50:
        rets = c[1:] / c[:-1] - 1.0
        last20_ret = rets[-20:]
        last20_vol = vol[-20:]
        for r, vv in zip(last20_ret, last20_vol):
            if math.isfinite(r) and math.isfinite(vv) and r <= hv_move and vv >= v50 * hv_mult:
                hv_down += 1

    # Accumulation/distribution proxy over last 50 days: up-vol vs down-vol.
    ad_score = None
    if len(c) >= 51:
        rets = c[1:] / c[:-1] - 1.0
        r = rets[-50:]
        vv = vol[-50:]
        up = float(vv[r > 0].sum()) if vv[r > 0].size else 0.0
        dn = float(vv[r < 0].sum()) if vv[r < 0].size else 0.0
        tot = up + dn
        if tot > 0:
            ad_score = round((up - dn) / tot, 3)

    return {
        "avg_volume_5d": round(v5, 1) if v5 is not None else None,
        "avg_volume_10d": round(v10, 1) if v10 is not None else None,
        "avg_volume_50d": round(v50, 1) if v50 is not None else None,
        "volume_dry_up_ratio": round(dry_ratio, 3) if dry_ratio is not None else None,
        "volume_dry_up_pass": dry_pass,
        "volume_dry_up_excellent": dry_excellent,
        "base_volume_fade_pass": base_half_pass,
        "high_volume_down_days_20d": hv_down,
        "accumulation_distribution_score": ad_score,
    }
