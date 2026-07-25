"""Offline tests for the base-screener pure logic (no network)."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.base import detect, metrics, rs, scoring
from app.base.config import load as load_config

CFG = load_config()


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_sma_and_series():
    vals = [1, 2, 3, 4, 5]
    assert metrics.sma(vals, 5) == 3.0
    assert metrics.sma(vals, 6) is None
    series = metrics.sma_series(vals, 3)
    assert series[0] is None and series[1] is None
    assert series[2] == 2.0 and series[4] == 4.0


def test_value_n_days_ago():
    series = [None, 1.0, 2.0, 3.0, 4.0]
    assert metrics.value_n_days_ago(series, 0) == 4.0
    assert metrics.value_n_days_ago(series, 2) == 2.0
    assert metrics.value_n_days_ago(series, 10) is None


def test_pct_return():
    closes = [100, 110, 121]
    assert round(metrics.pct_return(closes, 2), 4) == 0.21
    assert metrics.pct_return(closes, 5) is None


def test_atr_series_positive():
    n = 30
    high = [10 + i * 0.1 + 0.5 for i in range(n)]
    low = [10 + i * 0.1 - 0.5 for i in range(n)]
    close = [10 + i * 0.1 for i in range(n)]
    atr = metrics.atr_series(high, low, close, 10)
    assert atr[-1] is not None and atr[-1] > 0
    assert atr[8] is None  # not enough bars yet


def test_52w_high_low():
    highs = list(range(1, 300))   # 1..299
    lows = list(range(1, 300))
    assert metrics.high_52w(highs) == 299.0
    # low over the last 252 samples of [1..299] -> min is 299-252+1 = 48
    assert metrics.low_52w(lows) == 48.0


def test_rs_line_and_near_high():
    stock = [1, 2, 3, 4, 5]
    bench = [1, 1, 1, 1, 1]
    line = metrics.rs_line(stock, bench)
    assert line[-1] == 5.0
    assert metrics.near_rolling_high(line, 252, 0.98) is True
    # falling RS line is not near its high
    line2 = [5, 4, 3, 2, 1.0]
    assert metrics.near_rolling_high(line2, 252, 0.98) is False


def test_trend_template_all_pass():
    out = metrics.trend_template(
        price=100, sma50=95, sma150=90, sma200=85, sma200_20d_ago=84,
        high52=110, low52=60, rs_percentile=90)
    assert out["trend_template_pass"] is True
    assert out["pass_count"] == 10


def test_trend_template_handles_none():
    out = metrics.trend_template(
        price=100, sma50=None, sma150=90, sma200=85, sma200_20d_ago=None,
        high52=110, low52=60, rs_percentile=None)
    # No crash; failing conditions simply count as False.
    assert out["trend_template_pass"] is False
    assert 0 <= out["pass_count"] < 10


# --------------------------------------------------------------------------- #
# base detection
# --------------------------------------------------------------------------- #
def _tightening_series(n=140):
    """Uptrend then a tightening base ending flat — a constructive setup."""
    high, low, close, dates = [], [], [], []
    price = 50.0
    for i in range(n):
        dates.append(f"D{i:03d}")
        if i < 90:
            price *= 1.004
            amp = 0.02
        else:
            k = (i - 90) / (n - 90)
            amp = 0.03 * (1 - k)          # contracting range
        hi = price * (1 + amp)
        lo = price * (1 - amp)
        high.append(hi); low.append(lo); close.append(price)
    return high, low, close, dates


def test_detect_base_depth_and_grade():
    high, low, close, dates = _tightening_series()
    base = detect.detect_base(high, low, close, dates, CFG)
    assert base["base_detected"] is True
    assert 0.05 <= base["base_depth"] <= 0.35
    assert base["base_depth_grade"] in ("excellent", "good", "caution")
    assert CFG["base"]["min_length_days"] <= base["base_length_days"] <= CFG["base"]["max_length_days"]


def test_detect_base_short_history():
    base = detect.detect_base([1, 2], [1, 2], [1, 2], ["a", "b"], CFG)
    assert base["base_detected"] is False


def test_vcp_contraction_detected():
    high, low, close, dates = _tightening_series()
    base = detect.detect_base(high, low, close, dates, CFG)
    vcp = detect.vcp_structure(high, low, base, CFG)
    # Ranges should be monotonically contracting in a tightening base.
    assert vcp["vcp_range_1"] >= vcp["vcp_range_3"]
    assert vcp["vcp_score"] > 0


def test_pivot_status_ready_when_near_high():
    high, low, close, dates = _tightening_series()
    base = detect.detect_base(high, low, close, dates, CFG)
    price = base["base_high"] * 0.98   # 2% below pivot
    piv = detect.pivot_analysis(price, base, high, close, [1] * len(close), 1.0, CFG)
    assert piv["pivot_status"] in ("ready", "watch")
    assert piv["distance_to_pivot"] >= 0


def test_volume_dry_up_flags():
    n = 120
    close = [50 + math.sin(i / 5) for i in range(n)]
    # Volume fades toward the end (dry-up).
    volume = [2_000_000 * (1.5 - i / n) for i in range(n)]
    base = detect.detect_base([c * 1.02 for c in close], [c * 0.98 for c in close], close,
                              [f"D{i}" for i in range(n)], CFG)
    vd = detect.volume_dry_up(close, volume, base, CFG)
    assert vd["avg_volume_50d"] is not None
    assert vd["volume_dry_up_ratio"] is not None
    assert vd["volume_dry_up_pass"] is True


# --------------------------------------------------------------------------- #
# RS percentile + scoring
# --------------------------------------------------------------------------- #
def test_assign_rs_percentiles():
    records = [
        {"ret_3m": 0.5, "ret_6m": 0.5, "ret_12m": 0.5},
        {"ret_3m": 0.1, "ret_6m": 0.1, "ret_12m": 0.1},
        {"ret_3m": -0.2, "ret_6m": -0.2, "ret_12m": -0.2},
    ]
    rs.assign_rs(records, CFG)
    assert records[0]["rs_percentile"] == 100.0
    assert records[2]["rs_percentile"] == 0.0
    assert records[1]["rs_composite"] is not None


def test_scoring_total_and_grade():
    rec = {
        "trend": {"pass_count": 10, "total": 10},
        "rs_percentile": 95,
        "rs_line_spy_near_high": True, "rs_line_qqq_near_high": True,
        "rs_vs_spy_3m": 0.1, "rs_vs_qqq_3m": 0.1,
        "sma50_position_pass": True,
        "base": {"base_detected": True, "base_depth_grade": "excellent",
                 "base_length_days": 40, "higher_low": True},
        "pivot": {"distance_to_pivot": 0.02, "pivot_status": "ready", "pivot_price": 100,
                  "breakout_signal": False},
        "vcp": {"vcp_score": 0.9, "vcp_pattern_pass": True},
        "volatility": {"volatility_contraction_grade": "excellent",
                       "volatility_contraction_pass": True, "recent_atr_compression_pass": True},
        "volume": {"volume_dry_up_excellent": True, "volume_dry_up_pass": True,
                   "base_volume_fade_pass": True, "high_volume_down_days_20d": 0,
                   "accumulation_distribution_score": 0.5},
        "sector_detail": {"sector_action_score": 1.0},
        "current_price": 98,
    }
    scoring.compute_scores(rec, CFG)
    assert rec["total_score"] >= 85
    assert rec["setup_grade"] == "Prime"
    # ready alert requires near pivot + dry-up + contraction + rs line near high
    assert rec["alert_type"] in ("ready", "breakout")


def test_scoring_missing_fields_no_crash():
    rec = {"current_price": 10}
    scoring.compute_scores(rec, CFG)  # must not raise
    assert rec["total_score"] >= 0
    assert rec["setup_grade"] in ("Prime", "High", "Watch", "Low")


# --------------------------------------------------------------------------- #
# In-Base health score + base-type tag
# --------------------------------------------------------------------------- #
from app.base import inbase


def test_short_term_metrics():
    close = [100.0] * 30 + [110.0]        # +10% today vs 1 ago region
    high = [c * 1.01 for c in close]
    low = [c * 0.99 for c in close]
    base = {"base_high": 111.0, "base_low": 99.0}
    m = inbase.short_term_metrics(close, high, low, base)
    assert m["ret_5d"] is not None and m["ret_10d"] is not None
    assert 0 <= m["base_position"] <= 1.2
    assert m["recent_range_10"] is not None


def test_inbase_penalizes_extended():
    ext = {
        "current_price": 130, "sma50": 100, "sma150": 95, "sma200": 90,
        "sma200_20d_ago": 89, "sma50_position_pass": False,
        "ret_5d": 0.18, "ret_10d": 0.30, "base_position": 0.98,
        "pivot": {"pivot_status": "extended"},
        "vcp": {"vcp_score": 0.2}, "volatility": {}, "volume": {},
        "base": {"base_detected": True, "base_depth": 0.12, "base_length_days": 30,
                 "base_depth_grade": "excellent", "higher_low": True},
    }
    inbase.compute(ext, CFG)
    assert ext["extended"] is True
    assert ext["inbase_score"] < 50           # strongly penalized
    assert ext["extension_flags"]             # reasons listed


def test_inbase_rewards_quiet_base():
    quiet = {
        "current_price": 101, "sma50": 100, "sma150": 96, "sma200": 92,
        "sma200_20d_ago": 90, "sma50_position_pass": True,
        "ret_5d": 0.005, "ret_10d": -0.01, "base_position": 0.5,
        "recent_range_10": 0.06,
        "pivot": {"pivot_status": "watch"},
        "vcp": {"vcp_score": 0.8},
        "volatility": {"volatility_contraction_grade": "excellent",
                       "volatility_contraction_pass": True, "recent_atr_compression_pass": True},
        "volume": {"volume_dry_up_excellent": True, "volume_dry_up_pass": True,
                   "high_volume_down_days_20d": 0, "accumulation_distribution_score": 0.4},
        "base": {"base_detected": True, "base_depth": 0.12, "base_length_days": 40,
                 "base_depth_grade": "excellent", "higher_low": True},
    }
    inbase.compute(quiet, CFG)
    assert quiet["extended"] is False
    assert quiet["inbase_score"] >= 70


def test_base_type_tags():
    def bt(depth, length, rr, hl):
        rec = {"recent_range_10": rr,
               "base": {"base_detected": True, "base_depth": depth,
                        "base_length_days": length, "higher_low": hl}}
        inbase.compute({**rec, "current_price": 100, "pivot": {}, "vcp": {},
                        "volatility": {}, "volume": {}}, CFG)
        return inbase._base_type({**rec}, CFG["base_type"])
    assert bt(0.25, 60, 0.05, True) == "abc"      # deep + higher-low
    assert bt(0.10, 30, 0.06, False) == "tight"   # short + very tight + shallow
    assert bt(0.14, 60, 0.12, False) == "flat"    # long + shallow

    # deep correction but price still near the lows (not rebounded) -> not abc
    assert inbase._base_type(
        {"recent_range_10": 0.10, "base_position": 0.2,
         "base": {"base_detected": True, "base_depth": 0.25,
                  "base_length_days": 60, "higher_low": True}},
        CFG["base_type"]) == "base"
    # deep + rebounded to upper half + higher-low -> abc
    assert inbase._base_type(
        {"recent_range_10": 0.10, "base_position": 0.7,
         "base": {"base_detected": True, "base_depth": 0.25,
                  "base_length_days": 60, "higher_low": True}},
        CFG["base_type"]) == "abc"
