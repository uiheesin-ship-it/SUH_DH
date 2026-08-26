"""Offline unit tests for the Flat Base Screener pure math (spec §4-§11).

No network: every series is constructed by hand so the expected geometry is
known. Run with:  python -m pytest tests/test_flat.py -q
"""

import math

import numpy as np

from app.flat import activity, bases, metrics, scoring, screen, setup, trend_tag
from app.flat.config import load, thresholds_for


CFG = load()


# ---------------- metrics ----------------

def test_close_band_flat_vs_wide():
    flat = [100.0 + 0.5 * math.sin(i) for i in range(60)]      # ±0.5 around 100
    wide = [100.0 + 15.0 * math.sin(i / 3.0) for i in range(60)]
    assert metrics.close_band(flat) < 0.03
    assert metrics.close_band(wide) > 0.15


def test_base_drift_flat_is_near_zero_and_rising_is_positive():
    flat = [100.0 for _ in range(50)]
    assert abs(metrics.base_drift(flat)) < 1e-6
    rising = [100.0 * (1.004 ** i) for i in range(50)]          # ~+22% over window
    d = metrics.base_drift(rising)
    assert d > 0.15
    falling = [100.0 * (0.996 ** i) for i in range(50)]
    assert metrics.base_drift(falling) < -0.10


def test_containment_ratio():
    closes = [100.0] * 90 + [130.0] * 10                        # 10% outside +7.5%
    r = metrics.containment_ratio(closes)
    assert 0.85 <= r <= 0.92


def test_center_shift_detects_marching_center():
    flat = [100.0 + (0.3 if i % 2 else -0.3) for i in range(40)]
    assert metrics.center_shift(flat) < 0.02
    ramp = list(np.linspace(100.0, 130.0, 40))
    assert metrics.center_shift(ramp) > 0.10


def test_outlier_ratio_counts_big_days():
    closes = [100.0] * 20
    closes[10] = closes[9] * 1.20                              # one +20% day
    closes[11] = closes[10]
    r = metrics.outlier_ratio(closes)
    assert r is not None and r > 0.0
    assert metrics.outlier_days(closes) >= 1


def test_current_position_and_divzero_guard():
    closes = [90.0, 95.0, 100.0, 105.0, 110.0] * 4
    p = metrics.current_position(110.0, closes)
    assert 0.7 <= p <= 1.01
    flatline = [50.0] * 30                                     # zero band -> guarded
    assert metrics.current_position(50.0, flatline) == 0.5


def test_metrics_never_raise_on_degenerate():
    for bad in ([], [float("nan")] * 5, [0.0] * 5, [1.0]):
        metrics.close_band(bad)
        metrics.base_drift(bad)
        metrics.containment_ratio(bad)
        metrics.center_shift(bad)
        metrics.outlier_ratio(bad)


# ---------------- scoring ----------------

def test_flatness_score_high_for_flat_low_for_trend():
    th = thresholds_for(60, CFG)
    flat = scoring.flatness_score(0.02, 0.005, 0.98, 0.005, 0.0, th, CFG)
    assert flat["flatness_score"] > 90
    trend = scoring.flatness_score(0.25, 0.15, 0.55, 0.12, 0.10, th, CFG)
    assert trend["flatness_score"] < 30


def test_score_components_sum_to_weights_max():
    th = thresholds_for(40, CFG)
    perfect = scoring.flatness_score(0.0, 0.0, 1.0, 0.0, 0.0, th, CFG)
    assert abs(perfect["flatness_score"] - 100.0) < 0.01


def test_grades():
    assert scoring.flatness_grade(90, CFG) == "Very Flat"
    assert scoring.flatness_grade(78, CFG) == "Flat"
    assert scoring.flatness_grade(66, CFG) == "Moderately Flat"
    assert scoring.flatness_grade(40, CFG) == "Not Flat"


# ---------------- bases ----------------

def _flat_series(n_prior, n_base, base_level=100.0, prior_slope=0.004):
    prior = [base_level / (1 + prior_slope) ** (n_prior - i) for i in range(n_prior)]
    base = [base_level + (0.4 if i % 2 else -0.4) for i in range(n_base)]
    return prior + base


def test_select_bases_finds_flat_window():
    closes = _flat_series(300, 60)
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    qual = bases.select_bases(closes, highs, lows, closes[-1], CFG)
    assert qual, "expected at least one qualifying flat base"
    top = qual[0]
    assert top["base_pass"] is True
    assert top["flatness_score"] > 70
    assert top["base_status"] == "Active Flat Base"


def test_dead_pinned_base_excluded():
    # A merger-arb / deal-pinned base (near-zero daily movement) scores ~perfect
    # on flatness but is dead money — it must NOT qualify as a flat base.
    dead = [100.0 * (1 + 0.001 * math.sin(i)) for i in range(300)]
    h = [c * 1.0005 for c in dead]
    l = [c * 0.9995 for c in dead]
    assert bases.select_bases(dead, h, l, dead[-1], CFG) == []
    assert metrics.mean_abs_daily_return(dead[-60:]) < CFG["min_base_daily_vol"]


def _setup_of(closes, n_base=50):
    c = list(closes)
    start = len(c) - n_base
    base = c[start:]
    lo = float(np.quantile(base, 0.10))
    hi = float(np.quantile(base, 0.90))
    band = hi - lo
    pos = (c[-1] - lo) / band if band > 0 else 0.5
    return setup.compute_setup(c, start, lo, hi, c[-1], pos, CFG)


def test_setup_continuation_passes_and_is_display_only():
    # Strong uptrend + tight base near highs riding rising MAs (AMD/에코프로/NTRA).
    up = [80.0 * (1.006 ** i) for i in range(300)]
    base = [up[-1] * (1 + 0.03 * math.sin(i / 3.0)) for i in range(50)]
    r = _setup_of(up + base)
    assert r["setup_archetype"] == "추세지속"
    assert r["setup_pass"] is True
    assert r["setup_score"] > 55
    # Setup must never leak into the Flatness Score inputs.
    assert "setup_score" not in scoring.flatness_score(
        0.02, 0.005, 0.98, 0.005, 0.0, thresholds_for(60, CFG), CFG)


def test_setup_turnaround_reclaim_passes():
    # Decline -> long bottoming base while the long MAs catch down -> reclaim (IBIT).
    down = [66.0 * (0.9955 ** i) for i in range(150)]
    flat = [34.0 * (1 + 0.06 * math.sin(i / 4.0)) for i in range(110)]
    reclaim = [flat[-1] * (1.012 ** i) for i in range(14)]
    r = _setup_of(down + flat + reclaim)
    assert r["setup_archetype"] == "바닥반전"
    assert r["reclaimed_sma200"] or r["reclaimed_sma150"]
    assert r["setup_pass"] is True


def test_setup_already_broken_out_is_demoted():
    # A base that has ALREADY broken out and extended well above the base top is
    # a finished move — it must NOT score high or pass (we want it BEFORE it goes).
    up = [80.0 * (1.006 ** i) for i in range(300)]
    base = [up[-1] * (1 + 0.03 * math.sin(i / 3.0)) for i in range(44)]
    breakout = [up[-1] * 1.03 * (1.02 ** k) for k in range(1, 7)]   # runs ~+10% above base
    r = _setup_of(up + base + breakout)
    assert r["extended"] is True
    assert r["above_base"] > 0.03
    assert r["setup_pass"] is False
    assert r["setup_archetype"] == "돌파연장"
    # A coiled-at-top base (same trend, price still at the base top) DOES pass.
    coiled = [up[-1] * (1 + 0.03 * math.sin(i / 3.0)) for i in range(46)] + \
             [up[-1] * 1.028, up[-1] * 1.029, up[-1] * 1.028, up[-1] * 1.027]
    rc = _setup_of(up + coiled)
    assert rc["extended"] is False
    assert rc["setup_pass"] is True
    assert rc["setup_score"] > r["setup_score"]


def test_position_type_pullback_bottom_flat():
    # ① 조정: explosive run-up (≥40%) then a ~25% correction, base above a rising 200.
    run = [50.0 * (1.006 ** i) for i in range(200)]
    peak = run[-1]
    corr = [peak * (1 - 0.25 * (i / 15.0)) for i in range(15)]
    base = [corr[-1] * (1 + 0.03 * math.sin(i / 3.0)) for i in range(50)]
    assert _setup_of(run + corr + base)["position_type"] == "조정"

    # ② 바닥: steep decline into a flat bottom that holds (no fresh lows late).
    dn = [80.0 * (0.992 ** i) for i in range(160)]
    base = [dn[-1] * (1 + 0.03 * math.sin(i / 3.0)) for i in range(50)]
    assert _setup_of(dn + base)["position_type"] == "바닥"

    # a stair-step DOWN (fresh lows in the back of the base) is NOT 바닥 (knife guard)
    dn = [80.0 * (0.992 ** i) for i in range(150)]
    step = ([dn[-1] * (1 + 0.02 * math.sin(i / 3.0)) for i in range(25)]
            + [dn[-1] * 0.9 * (1 + 0.02 * math.sin(i / 3.0)) for i in range(25)])
    assert _setup_of(dn + step)["position_type"] != "바닥"

    # ③ 평평: a gentle rise that stalls flat with no real correction (CNOB-like).
    rise = [26.0 * (1.0015 ** i) for i in range(200)]
    base = [rise[-1] * (1 + 0.03 * math.sin(i / 3.0)) for i in range(50)]
    assert _setup_of(rise + base)["position_type"] == "평평"


def test_setup_trendless_base_fails():
    # Up, then a big decline, then a partial recovery that stalls well below the
    # 52-week high with tangled/flat MAs (ARQT) — flat but NOT a setup.
    s1 = [20.0 * (1.01 ** i) for i in range(80)]
    s2 = [s1[-1] * (0.985 ** i) for i in range(90)]
    s3 = [s2[-1] * (1.012 ** i) for i in range(80)]
    base = [s3[-1] * (1 + 0.045 * math.sin(i / 3.0)) for i in range(50)]
    r = _setup_of(s1 + s2 + s3 + base)
    assert r["setup_archetype"] == "약함"
    assert r["setup_pass"] is False


def test_base_status_transitions():
    assert bases.base_status(100, 95, 105, CFG) == "Active Flat Base"
    assert bases.base_status(120, 95, 105, CFG) == "Exited Upward"
    assert bases.base_status(80, 95, 105, CFG) == "Exited Downward"


# ---------------- activity ----------------

def test_historical_activity_pass_for_lively_prior():
    # Prior 252 days swing widely; base is the last 60 flat days.
    prior = [100.0 + 25.0 * math.sin(i / 10.0) for i in range(300)]
    base = [100.0 + (0.3 if i % 2 else -0.3) for i in range(60)]
    closes = prior + base
    cband = metrics.close_band(closes[-60:])
    h = activity.historical_activity(closes, len(closes) - 60, cband, CFG)
    assert h["historical_activity_pass"] is True
    assert h["chronically_low_vol"] is False


def test_chronically_low_vol_flagged_for_dead_stock():
    closes = [100.0 + 0.2 * math.sin(i / 5.0) for i in range(320)]  # barely moves
    cband = metrics.close_band(closes[-60:])
    h = activity.historical_activity(closes, len(closes) - 60, cband, CFG)
    assert h["historical_activity_pass"] is False
    assert h["chronically_low_vol"] is True


def test_activity_uses_only_pre_base_data():
    # Base window is lively but prior is dead -> must still fail (no look-ahead).
    prior = [100.0 + 0.2 * math.sin(i / 5.0) for i in range(300)]
    base = [100.0 * (1.02 ** i) for i in range(40)]
    closes = prior + base
    cband = metrics.close_band(closes[-40:])
    h = activity.historical_activity(closes, len(closes) - 40, cband, CFG)
    assert h["historical_activity_pass"] is False


# ---------------- trend tag ----------------

def test_prior_trend_categories():
    up = [100.0 * (1.006 ** i) for i in range(200)] + [100.0 * (1.006 ** 199)] * 60
    t = trend_tag.prior_trend(up, len(up) - 60, CFG)
    assert t["base_category"] == "Continuation Flat Base"

    down = [200.0 * (0.99 ** i) for i in range(200)] + [200.0 * (0.99 ** 199)] * 60
    t2 = trend_tag.prior_trend(down, len(down) - 60, CFG)
    assert t2["base_category"] == "Turnaround Flat Base"

    flat = [100.0 + 0.5 * math.sin(i) for i in range(260)]
    t3 = trend_tag.prior_trend(flat, len(flat) - 60, CFG)
    assert t3["base_category"] == "Neutral Flat Base"


def test_scan_record_has_display_only_beta():
    # beta is a display-only column (like sector/RS%): present on records, and
    # must never be one of the Flatness Score inputs.
    import os
    os.environ["SUH_DH_DEMO"] = "1"
    res = screen.run_scan(limit=3)
    assert res["stocks"], "demo scan should return records"
    for s in res["stocks"]:
        assert "beta" in s
        assert "rs_percentile" in s


def test_acceptance_neutral_stricter():
    base = {"base_days": 30, "flatness_score": 72, "containment_ratio": 0.9,
            "base_drift": 0.02, "center_shift": 0.02}
    ok_cont, _ = trend_tag.acceptance_check(base, "Continuation Flat Base",
                                            {"historical_activity_pass": True}, CFG)
    assert ok_cont is True   # continuation: 30d & 72 pts is enough
    ok_neu, reasons = trend_tag.acceptance_check(base, "Neutral Flat Base",
                                                 {"historical_activity_pass": True}, CFG)
    assert ok_neu is False   # neutral needs 40d & 80 pts
    assert reasons
