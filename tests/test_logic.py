"""Offline tests for the pure logic (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.indicators import attach_moving_averages, moving_average
from app.screener import _normalize_change, group_by_sector
from app import demo_data


def test_moving_average_padding_and_value():
    vals = [1, 2, 3, 4, 5]
    ma3 = moving_average(vals, 3)
    assert ma3[0] is None and ma3[1] is None
    assert ma3[2] == 2.0  # (1+2+3)/3
    assert ma3[4] == 4.0  # (3+4+5)/3


def test_attach_moving_averages_keys():
    chart = {"close": list(range(200))}
    out = attach_moving_averages(chart)
    for w in (5, 20, 50, 120):
        assert f"ma{w}" in out
        assert len(out[f"ma{w}"]) == 200
    assert out["ma120"][118] is None
    assert out["ma120"][119] is not None


def test_normalize_change_fraction_and_percent():
    assert _normalize_change(0.0523) == 5.23   # finviz fraction -> percent
    assert _normalize_change(-0.011) == -1.1
    assert _normalize_change(None) is None


def test_group_by_sector_sorted_by_market_cap():
    rows = demo_data.demo_new_highs()
    sectors = group_by_sector(rows)
    # sectors sorted by total market cap desc
    caps = [s["market_cap"] for s in sectors]
    assert caps == sorted(caps, reverse=True)
    # within an industry, stocks sorted by market cap desc
    tech = next(s for s in sectors if s["sector"] == "Technology")
    semis = next(i for i in tech["industries"] if i["industry"] == "Semiconductors")
    mcaps = [s["market_cap"] for s in semis["stocks"]]
    assert mcaps == sorted(mcaps, reverse=True)
    # counts add up
    assert tech["count"] == sum(i["count"] for i in tech["industries"]) + len(tech["stocks"])


def test_demo_chart_has_consistent_lengths():
    d = demo_data.demo_chart("NVDA", "6mo")
    n = len(d["dates"])
    for k in ("open", "high", "low", "close", "volume"):
        assert len(d[k]) == n
    assert n > 100
