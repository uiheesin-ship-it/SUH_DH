"""Offline unit tests for the Turnaround (bottom base) Screener.

No network: every series is constructed by hand so the expected geometry is
known, and the demo fixtures cover the four cases the screener has to tell
apart end to end. Run with:  python -m pytest tests/test_turnaround.py -q
"""

import math

from app.turnaround import bases, edge, quality, scoring, screen
from app.turnaround.config import load


CFG = load()


def _bars(closes, vol=None):
    """Wrap a close series into high/low/volume with a small, constant range."""
    highs = [c * 1.012 for c in closes]
    lows = [c * 0.988 for c in closes]
    volume = vol if vol is not None else [1_000_000] * len(closes)
    return closes, highs, lows, volume


def _jitter(i, amp=0.008):
    """Deterministic day-to-day wiggle so a hand-built series clears the
    dead/deal-pinned gate (min_base_daily_vol) the way a real stock would."""
    return 1 + amp * math.sin(i * 2.399)


# ---------------- trough anchoring ----------------

def test_find_trough_takes_the_left_foot_of_a_double_bottom():
    # Two lows within the 3% tolerance: 10.00 at index 300, 9.98 at index 380.
    # argmin would return 380 — which is not when the bottom was formed, and
    # would push the measured low to the right of every candidate window.
    closes = [30.0 - 20.0 * (i / 300.0) if i <= 300 else 12.0 for i in range(420)]
    closes[300] = 10.0
    closes[380] = 9.98
    c, h, l, v = _bars(closes)
    idx = bases.find_trough(l, CFG)
    # Anchored on the left foot, not the marginally-lower right one. The exact
    # bar is a few earlier than 300 because the approach into the low is smooth
    # and the tolerance is what decides "close enough to the bottom".
    assert idx < 350
    assert abs(idx - 300) <= 10


def test_find_trough_ignores_a_one_tick_undercut():
    closes = [20.0] * 420
    closes[200] = 10.0
    closes[400] = 9.9        # 1% lower — inside tolerance, so not a new anchor
    c, h, l, v = _bars(closes)
    assert bases.find_trough(l, CFG) == 200


# ---------------- low_early_frac ----------------

def _window_low_case(low_at_offset, length=60):
    """A `length`-day window whose low sits `low_at_offset` bars from its start."""
    n = 400
    closes = [20.0] * n
    start = n - length
    closes[start + low_at_offset] = 16.0
    return _bars(closes)


def test_window_with_low_in_the_front_is_valid():
    # 60-day window, low at bar 12 -> 12/60 = 0.20 <= 0.70
    c, h, l, v = _window_low_case(12)
    w = bases.evaluate_window(c, h, l, 60, 300, CFG)
    assert w is not None
    assert w["low_position"] == 0.2


def test_window_with_low_in_the_last_third_is_rejected():
    # 60-day window, low at bar 52 -> 52/60 = 0.867 > 0.70. Same depth, same
    # length, same range as the passing case — only the low's position differs.
    c, h, l, v = _window_low_case(52)
    assert bases.evaluate_window(c, h, l, 60, 300, CFG) is None


# ---------------- the decline-swallow case ----------------

def _gentle_decline_then_base():
    """The shape that breaks a grow-until-max_depth base detector.

    120 bars of gentle slide from $13.00 to $10.20, then 50 bars of real base
    between $10.00 and $11.50, now at $11.30. Depth over the whole 170 bars is
    only ~30%, so nothing stops a width-based detector from swallowing the
    decline — and once it does, the decline's wide early range makes the base
    look like textbook contraction.
    """
    closes = []
    for i in range(250):                       # pre-history, flat and higher
        closes.append(13.5 * _jitter(i))
    for i in range(120):                       # the gentle decline
        closes.append((13.0 - 2.8 * (i / 119.0)) * _jitter(i))
    for i in range(50):                        # the actual base
        closes.append((10.6 + 0.55 * math.sin(i / 4.0)) * _jitter(i))
    closes[-1] = 11.30
    return _bars(closes)


def test_over_long_window_that_swallows_the_decline_is_rejected():
    c, h, l, v = _gentle_decline_then_base()
    trough = bases.find_trough(l, CFG)
    # The 120-day window reaches back into the slide; its right side is a low
    # shelf near the window floor, so min_recovery rejects it.
    wide = bases.evaluate_window(c, h, l, 120, trough, CFG)
    assert wide is None or wide["base_recovery"] >= CFG["base"]["min_recovery"]


def test_the_sweep_lands_on_the_real_base_not_the_decline():
    c, h, l, v = _gentle_decline_then_base()
    windows = bases.select_windows(c, h, l, CFG)
    assert windows, "the real 50-day base should be found"
    # Every surviving window must have recovered into the upper half of its own
    # range — that is what distinguishes a base from a shelf under a decline.
    for w in windows:
        assert w["base_recovery"] >= CFG["base"]["min_recovery"]
    # And the best-scoring one should be short enough to exclude the slide.
    best = max(windows, key=lambda w: edge.compute(c, h, l, w, CFG)["edge_score"])
    assert best["base_days"] <= 60


def test_quality_is_measured_from_the_trough_not_the_window_start():
    """The load-bearing defence: contraction must not be able to read the
    decline even when the window start precedes the trough."""
    c, h, l, v = _gentle_decline_then_base()
    trough = bases.find_trough(l, CFG)
    # Force a window that deliberately starts inside the decline.
    forced = {"base_start_idx": len(c) - 150, "trough_idx": trough}
    q = quality.compute(c, h, l, v, forced, CFG)
    # post_trough_days is the segment actually measured; it must be the base,
    # not the 150-bar window.
    assert q["post_trough_days"] < 150
    assert q["post_trough_days"] == len(c) - trough


# ---------------- the cup, which a slope test would kill ----------------

def test_cup_shaped_base_is_accepted():
    """A rounding bottom descends steeply on its left side. Rejecting windows on
    a steep front-third slope would throw away every cup and saucer, which is
    why min_recovery does that job instead."""
    closes = [40.0 * _jitter(i) for i in range(250)]
    for i in range(100):                       # left side of the cup, down
        closes.append((40.0 - 16.0 * (i / 99.0)) * _jitter(i))
    for i in range(70):                        # right side, back up
        closes.append((24.0 + 12.0 * ((i / 69.0) ** 1.4)) * _jitter(i))
    c, h, l, v = _bars(closes)
    windows = bases.select_windows(c, h, l, CFG)
    assert windows, "a cup with its low mid-window must produce a valid base"
    assert any(w["low_position"] > 0.3 for w in windows), \
        "the cup's low should sit mid-window, not at its left edge"


# ---------------- extension: two independent tests ----------------

def test_slice_of_a_vertical_advance_is_not_a_base():
    """Low at the left, price at the high, modest depth — passes every other
    check, so the drift cap has to be the thing that rejects it."""
    closes = [10.0 * (1.012 ** i) * _jitter(i) for i in range(420)]   # relentless ramp
    c, h, l, v = _bars(closes)
    trough = bases.find_trough(l, CFG)
    for L in (20, 25, 30, 40):
        w = bases.evaluate_window(c, h, l, L, trough, CFG)
        assert w is None, f"a {L}-day slice of a vertical advance was accepted"


def test_price_far_above_the_50_day_is_extended_whatever_window_is_drawn():
    closes = [20.0 * _jitter(i) for i in range(370)]
    for i in range(50):
        closes.append(20.0 * (1 + 0.60 * (i / 49.0)) * _jitter(i))
    c, h, l, v = _bars(closes)
    from app.base import metrics as bm
    sma50 = bm.sma(c, 50)
    window = {"base_start_idx": len(c) - 30, "base_high": max(h[-30:]),
              "base_low_q10": min(c[-30:]), "base_high_q90": max(c[-30:])}
    e = edge.compute(c, h, l, window, CFG, sma50)
    assert e["extended_vs_sma50"] is True
    assert e["extended"] is True


def test_ledge_pivot_is_nearer_than_the_base_high_on_a_deep_base():
    """A deep bottom base's own high can be 25% overhead; without the ledge the
    'ready' state would never fire."""
    closes = [20.0 * _jitter(i) for i in range(300)]
    closes += [26.0 * _jitter(i) for i in range(20)]      # old, higher shelf
    closes += [21.0 * _jitter(i) for i in range(60)]      # back down
    closes += [22.0 * _jitter(i) for i in range(20)]      # recent ledge
    c, h, l, v = _bars(closes)
    window = {"base_start_idx": len(c) - 120, "base_high": max(h[-120:]),
              "base_low_q10": 20.0, "base_high_q90": 23.0}
    e = edge.compute(c, h, l, window, CFG, sma50=21.5)
    assert e["pivot_kind"] == "ledge"
    assert e["pivot_price"] < window["base_high"]


# ---------------- bottom gate ----------------

def test_drawdown_uses_the_multi_year_peak_not_the_52_week_high():
    """A base that has run for over a year pushes the pre-decline peak out of a
    252-day window. Measured on the 52-week high the drawdown collapses toward
    zero and the gate would reject exactly the long, well-formed bottom bases
    this screener wants."""
    closes = [100.0 * _jitter(i) for i in range(120)]      # the old peak
    closes += [(100.0 - 55.0 * (i / 99.0)) * _jitter(i) for i in range(100)]
    closes += [46.0 * _jitter(i) for i in range(300)]      # 300 days of basing
    c, h, l, v = _bars(closes)
    ok, m = screen.bottom_gate(c, h, l, CFG)
    assert m["off_52w_high"] < 0.10, "52-week high has been swallowed by the base"
    assert m["off_peak_high"] > 0.30
    assert ok is True


def test_fresh_52_week_low_is_rejected():
    closes = [(30.0 - 22.0 * (i / 419.0)) * _jitter(i) for i in range(420)]
    c, h, l, v = _bars(closes)
    ok, m = screen.bottom_gate(c, h, l, CFG)
    assert m["fresh_52w_low"] is True
    assert ok is False


def test_already_doubled_off_the_low_is_rejected():
    closes = [60.0 * _jitter(i) for i in range(200)]
    closes += [20.0 * _jitter(i) for i in range(120)]
    closes += [44.0 * _jitter(i) for i in range(100)]      # +120% off the low
    c, h, l, v = _bars(closes)
    ok, m = screen.bottom_gate(c, h, l, CFG)
    assert m["off_52w_low"] > CFG["bottom"]["max_off_52w_low"]
    assert ok is False


# ---------------- scoring ----------------

def test_total_is_the_sum_of_the_four_axes():
    t = scoring.total({"quality_score": 30.0}, {"edge_score": 24.0},
                      {"setup_score": 15.0}, {"trigger_score": 7.0})
    assert t == 76.0


def test_grades_follow_the_configured_cuts():
    assert scoring.grade(85, CFG) == "prime"
    assert scoring.grade(70, CFG) == "high"
    assert scoring.grade(60, CFG) == "watch"
    assert scoring.grade(40, CFG) == "weak"


def test_stage_labels_track_the_pivot_and_trigger_state():
    assert scoring.stage({"extended": True, "pivot_status": "ready"},
                         {"trigger_fresh": True}) == "지나감"
    assert scoring.stage({"extended": False, "pivot_status": "watch"},
                         {"trigger_fresh": True}) == "전환신호"
    assert scoring.stage({"extended": False, "pivot_status": "ready"},
                         {"trigger_fresh": False}) == "오른쪽끝"
    assert scoring.stage({"extended": False, "pivot_status": "early"},
                         {"trigger_fresh": False}) == "이른편"


def test_missing_axis_scores_neutral_not_zero():
    """Short history must not be punished as if it were a bad base."""
    closes = [20.0 * _jitter(i) for i in range(40)]
    c, h, l, v = _bars(closes)
    window = {"base_start_idx": 0, "trough_idx": 35}
    q = quality.compute(c, h, l, v, window, CFG)
    # Every axis is un-measurable on a 5-bar post-trough segment; the total must
    # be half marks (20 of 40), not zero.
    assert q["quality_score"] == 20.0


# ---------------- end to end, on the demo fixtures ----------------

def test_demo_scan_keeps_the_bases_and_drops_the_knife_and_the_runaway(monkeypatch):
    monkeypatch.setenv("SUH_DH_DEMO", "1")
    from app.turnaround import screen as screen_mod
    payload = screen_mod.run_scan(CFG)
    found = {s["ticker"] for s in payload["stocks"]}
    assert "KNIFE" not in found, "a stock still making 52-week lows must not appear"
    assert "GONEC" not in found, "a stock that already ran must not appear"
    assert found, "the basing fixtures should survive"
    for s in payload["stocks"]:
        assert 0 <= s["turnaround_score"] <= 100
        assert s["stage"] != "지나감"
        assert s["extended"] is False


# ---------------- support axis ----------------

def test_undercut_fires_when_the_base_makes_a_late_new_low():
    """Measured against the segment's own minimum this could only ever read
    zero; it has to compare the last third against the earlier bars."""
    holding = [10.0 + 0.4 * math.sin(i / 3.0) for i in range(60)]
    breaking = holding[:40] + [9.0 - 0.02 * i for i in range(20)]
    assert quality.support(holding)["undercut"] == 0.0
    assert quality.support(breaking)["undercut"] > 0.05


def test_higher_low_reads_a_rising_floor():
    rising = [10.0 + 0.03 * i + 0.3 * math.sin(i / 3.0) for i in range(60)]
    assert quality.support(rising)["higher_low"] > 0.03


def test_support_scores_lower_for_a_base_that_breaks_its_lows():
    holding, hh, hl, hv = _bars([10.0 + 0.4 * math.sin(i / 3.0) for i in range(60)])
    broken = [10.0 + 0.4 * math.sin(i / 3.0) for i in range(40)] + \
             [9.0 - 0.02 * i for i in range(20)]
    bc, bh, bl, bv = _bars(broken)
    w = {"base_start_idx": 0, "trough_idx": 0}
    q_hold = quality.compute(holding, hh, hl, hv, w, CFG)
    q_break = quality.compute(bc, bh, bl, bv, w, CFG)
    assert q_hold["q_support_score"] > q_break["q_support_score"]
