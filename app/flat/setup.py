"""Moving-average / trend "Setup" analysis for the Flat Base Screener.

This is a SEPARATE dimension from the Flatness Score. The Flatness Score only
answers "how tight is this base right now"; it deliberately ignores moving
averages, trend and position (spec §1). But a tight base is only actionable
when it sits in the right *context*: a platform riding rising moving averages
near the highs (a continuation base — e.g. AMD / 에코프로 / NTRA), or a bottoming
base reclaiming its moving averages as they turn up (a turnaround base —
e.g. IBIT). A flat-but-trendless base floating mid-range with tangled/flat MAs
(e.g. ARQT) is the shape we want to push down.

`compute_setup` grades that context into a 0-100 Setup Score plus a handful of
display fields (SMA values, slopes, distance from the 52-week high/low, an
archetype label). None of this ever feeds the Flatness Score — it is surfaced
as its own column, a filter, and a secondary "composite" ranking so the user
can keep or drop trendless bases at will.
"""

from __future__ import annotations

import numpy as np


def _sma_series(closes: np.ndarray, window: int) -> np.ndarray:
    """Simple moving average as an array aligned to `closes` (NaN until warm)."""
    n = closes.size
    out = np.full(n, np.nan, dtype=float)
    if n < window:
        return out
    csum = np.cumsum(np.insert(closes, 0, 0.0))
    out[window - 1:] = (csum[window:] - csum[:-window]) / window
    return out


def _slope(series: np.ndarray, lookback: int) -> float | None:
    """Percent change of a (SMA) series over `lookback` bars, ending at the last
    finite value. Positive = rising."""
    finite = np.isfinite(series)
    if not finite.any():
        return None
    last = np.max(np.nonzero(finite))
    ref = last - lookback
    if ref < 0 or not np.isfinite(series[ref]) or series[ref] <= 0:
        return None
    return float(series[last] / series[ref] - 1.0)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _position_type(c, base_start_idx, base_low, base_high, sma200, sl200,
                   sl50, s200, pcfg: dict) -> dict:
    """Classify the base by its position vs the 200-day MA (see caller comment).
    Returns {position_type: "조정"|"바닥"|"평평", above_200_frac, prior_run_up,
    base_correction}."""
    out = {"position_type": "평평", "above_200_frac": None,
           "prior_run_up": None, "base_correction": None}
    n = c.size - base_start_idx
    if n < 10 or not (0 <= base_start_idx < c.size):
        return out
    base_c = c[base_start_idx:]
    base_median = float(np.median(base_c))
    base_s200 = s200[base_start_idx:s200.size]
    m = min(base_c.size, base_s200.size)
    if m <= 0:
        return out
    ok = np.isfinite(base_s200[:m])
    if not ok.any():
        return out                       # no 200-day over the base -> can't place it
    bc, bs = base_c[:m][ok], base_s200[:m][ok]
    below = int((bc < bs).sum())
    above_frac = round(1.0 - below / bc.size, 3)
    out["above_200_frac"] = above_frac

    # Prior explosive advance (trough -> peak) in the window before the base.
    win = int(pcfg.get("run_up_window", 252))
    pre = c[max(0, base_start_idx - win):base_start_idx]
    run_up = None
    pre_high = None
    if pre.size >= int(pcfg.get("min_pre_window", 60)):
        hi_idx = int(np.argmax(pre))
        pre_high = float(pre[hi_idx])
        trough = float(np.min(pre[:hi_idx + 1])) if hi_idx > 0 else float(pre[0])
        if trough > 0:
            run_up = round(pre_high / trough - 1.0, 4)
    out["prior_run_up"] = run_up

    # Correction from that pre-base high down into the base.
    correction = round((pre_high - base_median) / pre_high, 4) if pre_high and pre_high > 0 else None
    out["base_correction"] = correction

    # Correction floor scales with base length (short bases need less).
    cm = pcfg.get("correction_min", {}) or {}
    if n <= 40:
        corr_min = float(cm.get("short", 0.15))
    elif n <= 80:
        corr_min = float(cm.get("mid", 0.20))
    else:
        corr_min = float(cm.get("long", 0.25))

    tol_days = int(pcfg.get("dip_tolerance_days", 3))
    mostly_above = below <= max(tol_days, int(round(n * 0.1))) and above_frac >= float(pcfg.get("above_frac_min", 0.6))
    mostly_below = above_frac <= float(pcfg.get("below_frac_max", 0.4))

    is_type1 = bool(mostly_above and (sl200 or 0) > 0
                    and run_up is not None and run_up >= float(pcfg.get("run_up_min", 0.40))
                    and correction is not None and correction >= corr_min)

    # Bottom (type 2): mostly below the 200-day, and NOT making fresh lows late in
    # the base. A falling knife is never a flat base to begin with (flatness
    # excludes it); the flat base itself IS the deceleration. The one thing left
    # to screen out is a stair-step-DOWN (each leg lower) — so require the back of
    # the base to hold the front's low rather than undercut it.
    seg = max(3, n // 3)
    early_low = float(np.min(base_c[:seg]))
    recent_low = float(np.min(base_c[-seg:]))
    eps = float(pcfg.get("new_low_tolerance", 0.03))
    no_new_lows = bool(early_low > 0 and recent_low >= early_low * (1.0 - eps))
    is_type2 = bool(mostly_below and no_new_lows)

    out["position_type"] = "조정" if is_type1 else ("바닥" if is_type2 else "평평")
    return out


def compute_setup(closes, base_start_idx: int, base_low: float | None,
                  base_high: float | None, current_close: float,
                  current_position: float | None, cfg: dict) -> dict:
    """Grade the trend / moving-average context around a flat base.

    Returns a dict of display fields plus `setup_score` (0-100), `setup_pass`
    (bool). The base's CATEGORY is `position_type` (조정 / 바닥 / 평평); this
    setup score is a direction-agnostic QUALITY grade within that category.
    """
    scfg = cfg.get("setup", {}) or {}
    c = np.asarray(closes, dtype=float)
    c = c[np.isfinite(c)]
    blank = {
        "sma50": None, "sma150": None, "sma200": None,
        "sma50_slope": None, "sma150_slope": None, "sma200_slope": None,
        "above_sma50": None, "above_sma150": None, "above_sma200": None,
        "ma_aligned": None, "reclaimed_sma200": None, "reclaimed_sma150": None,
        "dist_52w_high": None, "dist_52w_low": None,
        "above_base": None, "extended": False,
        "position_type": "평평", "position_above_200_frac": None,
        "prior_run_up": None, "base_correction": None,
        "setup_score": None, "setup_pass": False,
    }
    if c.size < 60 or not current_close:
        return blank

    s50 = _sma_series(c, 50)
    s150 = _sma_series(c, 150)
    s200 = _sma_series(c, 200)

    def _last(a):
        f = np.isfinite(a)
        return float(a[np.max(np.nonzero(f))]) if f.any() else None

    sma50, sma150, sma200 = _last(s50), _last(s150), _last(s200)
    sl50 = _slope(s50, int(scfg.get("slope_lookback_fast", 20)))
    sl150 = _slope(s150, int(scfg.get("slope_lookback_slow", 40)))
    sl200 = _slope(s200, int(scfg.get("slope_lookback_slow", 40)))

    above50 = sma50 is not None and current_close >= sma50
    above150 = sma150 is not None and current_close >= sma150
    above200 = sma200 is not None and current_close >= sma200
    aligned = bool(sma50 and sma150 and sma200 and sma50 > sma150 > sma200)

    # 52-week (≈252 trading day) position — display + soft continuation bonus.
    win52 = c[-252:] if c.size >= 252 else c
    hi52 = float(np.max(win52)) if win52.size else None
    lo52 = float(np.min(win52)) if win52.size else None
    dist_high = (current_close / hi52 - 1.0) if hi52 else None      # <=0, near 0 = at highs
    dist_low = (current_close / lo52 - 1.0) if lo52 and lo52 > 0 else None  # >=0

    # Reclaim (turnaround): price was clearly BELOW a long MA (150 or 200) at/
    # around the base and is now above it — a Stage 1→2 transition (IBIT). A
    # bottoming base often reclaims the flattened 150-day before the 200-day, so
    # accept a reclaim of EITHER long average.
    reclaim_gap = float(scfg.get("reclaim_min_gap", 0.05))

    def _reclaimed(ma_series, ma_last, above_now):
        if ma_last is None or not above_now or not (0 <= base_start_idx < len(closes)):
            return False
        idx = min(base_start_idx, ma_series.size - 1)
        lookback_start = max(0, idx - 20)
        seg_c = c[lookback_start:] if lookback_start < c.size else c[-1:]
        seg_s = ma_series[lookback_start:ma_series.size]
        m = min(seg_c.size, seg_s.size)
        if m <= 0:
            return False
        sc2, ss2 = seg_c[:m], seg_s[:m]
        ok = np.isfinite(ss2) & (ss2 > 0)
        if not ok.any():
            return False
        return bool((sc2[ok] / ss2[ok] - 1.0).min() <= -reclaim_gap)

    reclaimed = _reclaimed(s200, sma200, above200)
    reclaimed_150 = _reclaimed(s150, sma150, above150)
    reclaimed_any = reclaimed or reclaimed_150

    # Base-position type (조정 / 바닥 / 평평) — THE category (vs the 200-day MA).
    # Computed up-front so the setup-quality gating below can key off it instead
    # of a separate archetype: a 바닥 (bottom) base rises off its lows, so it gets
    # a looser "extended" gate than a 조정 (pullback), which is late the moment it
    # leaves the base top.
    pcfg = cfg.get("position", {}) or {}
    ptype = _position_type(c, base_start_idx, base_low, base_high, sma200, sl200,
                           sl50, s200, pcfg)
    position_type = ptype["position_type"]
    is_bottom = position_type == "바닥"

    # ---- component scores (0..1) — a direction-agnostic QUALITY score ---------
    # 1) Trend: rising 50 & 150 day averages.
    fast_full = float(scfg.get("slope_fast_full", 0.06))   # 6% / 20d = full credit
    slow_full = float(scfg.get("slope_slow_full", 0.08))   # 8% / 40d = full credit
    t50 = _clamp01((sl50 or 0.0) / fast_full)
    t150 = _clamp01((sl150 or 0.0) / slow_full)
    trend = 0.5 * t50 + 0.5 * t150

    # 2) Structure: bullish stack, or a clean reclaim.
    align = (0.34 * (1 if above50 else 0) + 0.33 * (1 if (sma50 and sma150 and sma50 > sma150) else 0)
             + 0.33 * (1 if (sma150 and sma200 and sma150 > sma200) else 0))
    structure = max(align, 0.72 if reclaimed_any else 0.0)

    # 3) MA support: a key MA (50 or 150) runs THROUGH the base band — the base
    #    "rides" the average. Full credit when the MA sits between the base low
    #    and high; partial when the base is modestly extended above the MA; zero
    #    when detached far above (over-extended) or the MA is above the base
    #    (price broken below it). Measured as the MA's position in the band:
    #    rel = (ma - base_low)/(base_high - base_low): 0 = at low, 1 = at high.
    def _support(ma):
        if ma is None or base_low is None or base_high is None or ma <= 0:
            return 0.0
        band = base_high - base_low
        if band <= 0:
            return 0.0
        rel = (ma - base_low) / band
        ext = float(scfg.get("support_extend_bands", 1.5))  # MA up to 1.5 bands below base low still "supports"
        if -ext <= rel <= 1.0:
            return 1.0
        if rel > 1.0:                                        # price under the MA
            return _clamp01((1.3 - rel) / 0.3)
        return _clamp01((rel + ext + 1.0) / 1.0)            # far below -> fades out
    support = max(_support(sma50), _support(sma150))

    # 4) Readiness: we want a base that is COILED at the top and about to break —
    #    NOT one that has already broken out and extended (that move is over, too
    #    late to act). So reward being high in the base band, but fade the credit
    #    as the price runs above the base top. `above_base` = how far the current
    #    price sits above the base top (Q90).
    pos = current_position if current_position is not None else 0.5
    coil = _clamp01((pos - 0.35) / 0.6)          # upper-base coiling: 0 at pos<=.35, 1 at >=.95
    above_base = (current_close / base_high - 1.0) if base_high else None
    # readiness -> 0 once this far above the base top; a 바닥 base rises off its
    # lows, so it fades more slowly than a 조정 pullback near its highs.
    ext_zero = float(scfg.get("extension_zero_turn", 0.20)) if is_bottom \
        else float(scfg.get("extension_zero", 0.08))
    if above_base is None or above_base <= 0.01:
        ext_factor = 1.0
    else:
        ext_factor = _clamp01((ext_zero - above_base) / ext_zero)
    readiness = coil * ext_factor

    # 5) Near-highs bonus (continuation quality); folded into trend/structure.
    near_high = _clamp01(1.0 + (dist_high or -1.0) / float(scfg.get("near_high_span", 0.25)))

    w = scfg.get("weights", {}) or {}
    w_trend = float(w.get("trend", 0.30))
    w_struct = float(w.get("structure", 0.22))
    w_support = float(w.get("support", 0.22))
    w_ready = float(w.get("readiness", w.get("breakout", 0.18)))
    w_high = float(w.get("near_high", 0.08))
    raw = (w_trend * trend + w_struct * structure + w_support * support
           + w_ready * readiness + w_high * near_high)
    setup_score = round(100.0 * raw, 1)

    # Extended = the price has already run above the base top by more than the
    # allowed tolerance. That breakout is done — we do NOT want it to score high
    # or pass the filter (the whole point is to catch the base BEFORE it goes).
    # 조정 near its highs is "late" almost immediately (tight gate); a 바닥 base
    # rises off its bottom, so it gets a looser gate before it counts as extended.
    max_ext = float(scfg.get("max_extension", 0.03))
    max_ext_turn = float(scfg.get("max_extension_turn", 0.12))
    limit = max_ext_turn if is_bottom else max_ext
    extended = bool(above_base is not None and above_base > limit)

    # 셋업 통과 = a real setup type (조정 또는 바닥) that has NOT yet broken out.
    # No score floor: a freshly-corrected 조정 base is away from its highs with
    # disrupted MAs, so it scores low — but it's exactly what we want to catch.
    # The setup_score only RANKS quality within a type; passing is about type +
    # not-extended. (min_setup_score kept in config for optional callers.)
    setup_pass = bool(position_type in ("조정", "바닥") and not extended)

    return {
        "position_type": position_type,
        "position_above_200_frac": ptype["above_200_frac"],
        "prior_run_up": ptype["prior_run_up"],
        "base_correction": ptype["base_correction"],
        "above_base": round(above_base, 4) if above_base is not None else None,
        "extended": extended,
        "sma50": round(sma50, 4) if sma50 is not None else None,
        "sma150": round(sma150, 4) if sma150 is not None else None,
        "sma200": round(sma200, 4) if sma200 is not None else None,
        "sma50_slope": round(sl50, 4) if sl50 is not None else None,
        "sma150_slope": round(sl150, 4) if sl150 is not None else None,
        "sma200_slope": round(sl200, 4) if sl200 is not None else None,
        "above_sma50": above50, "above_sma150": above150, "above_sma200": above200,
        "ma_aligned": aligned, "reclaimed_sma200": reclaimed,
        "reclaimed_sma150": reclaimed_150,
        "dist_52w_high": round(dist_high, 4) if dist_high is not None else None,
        "dist_52w_low": round(dist_low, 4) if dist_low is not None else None,
        "setup_score": setup_score, "setup_pass": setup_pass,
    }
