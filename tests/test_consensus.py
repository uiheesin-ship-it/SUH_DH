"""야후 컨센·발표일 정규화 — 조각 하나가 깨져도 나머지는 살아야 한다.

yfinance 를 가짜로 끼워 넣는다. 실측(tools/consensus_probe.py, 2026-09-17)에서
확인한 모양 그대로 만든다: earnings_estimate 는 0q·+1q·0y·+1y 네 행,
get_earnings_dates 는 타임존 붙은 Timestamp 인덱스 + EPS Estimate/Reported EPS.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app import cache, consensus


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()
    yield
    cache.clear()


EST = pd.DataFrame(
    {"avg": [1.03, 1.04, 4.34, 5.33], "low": [0.8, 0.85, 3.5, 3.53],
     "high": [1.08, 1.22, 5.13, 7.26], "numberOfAnalysts": [17, 17, 18, 17]},
    index=["0q", "+1q", "0y", "+1y"])

DATES = pd.DataFrame(
    {"EPS Estimate": [0.39, 0.62, 0.96, 1.04],
     "Reported EPS": [0.35, 0.84, 1.70, float("nan")]},
    index=pd.to_datetime(["2025-11-04", "2026-05-05", "2026-08-11", "2026-11-03"]
                         ).tz_localize("America/New_York"))


class FakeTicker:
    def __init__(self, *, est=EST, dates=DATES, info=None, boom=()):
        self._est, self._dates = est, dates
        self._info = info if info is not None else {"sharesOutstanding": 6.4e8,
                                                    "currentPrice": 36.85,
                                                    "marketCap": 2.38e10}
        self._boom = set(boom)

    def _maybe(self, name, value):
        if name in self._boom:
            raise RuntimeError(f"{name} down")
        return value

    @property
    def earnings_estimate(self):
        return self._maybe("earnings_estimate", self._est)

    @property
    def revenue_estimate(self):
        return self._maybe("revenue_estimate", self._est)

    @property
    def info(self):
        return self._maybe("info", self._info)

    def get_earnings_dates(self, limit=40):
        return self._maybe("get_earnings_dates", self._dates)


def wire(monkeypatch, tk):
    import types
    monkeypatch.setitem(__import__("sys").modules, "yfinance",
                        types.SimpleNamespace(Ticker=lambda t: tk))


# --------------------------------------------------- 발표일이 실제로 나오는가
def test_the_announcement_dates_come_out_as_plain_dates(monkeypatch):
    """Timestamp.date 는 **메서드**다.

    date 객체를 그대로 자르려 들면 TypeError 가 나고, 그 예외가 컨센 전체를
    날린다 — 실측에서 6종목 모두 발표일도 컨센도 통째로 비었다.
    """
    wire(monkeypatch, FakeTicker())
    c = consensus.fetch("SMCI")
    assert [a["date"] for a in c["announcements"]] == [
        "2025-11-04", "2026-05-05", "2026-08-11", "2026-11-03"]
    assert all(isinstance(a["date"], str) for a in c["announcements"])


def test_an_unreported_quarter_keeps_its_estimate(monkeypatch):
    wire(monkeypatch, FakeTicker())
    last = consensus.fetch("SMCI")["announcements"][-1]
    assert last["reported_eps"] is None and last["eps_estimate"] == 1.04


def test_the_four_estimate_rows_are_picked_up(monkeypatch):
    wire(monkeypatch, FakeTicker())
    c = consensus.fetch("SMCI")
    assert set(c["eps"]) == {"0q", "+1q", "0y", "+1y"}
    assert consensus.eps_estimates(c)["0y"] == 4.34
    assert c["eps"]["0q"]["analysts"] == 17


# -------------------------------------------- 조각이 깨져도 나머지는 살아야
def test_a_broken_estimate_table_does_not_kill_the_announcements(monkeypatch):
    wire(monkeypatch, FakeTicker(boom=["earnings_estimate"]))
    c = consensus.fetch("SMCI")
    assert c["eps"] == {} and len(c["announcements"]) == 4


def test_broken_announcements_do_not_kill_the_estimates(monkeypatch):
    wire(monkeypatch, FakeTicker(boom=["get_earnings_dates"]))
    c = consensus.fetch("SMCI")
    assert c["announcements"] == [] and c["eps"]["0q"]["avg"] == 1.03


def test_a_broken_info_call_does_not_kill_anything(monkeypatch):
    wire(monkeypatch, FakeTicker(boom=["info"]))
    c = consensus.fetch("SMCI")
    assert c["shares"] is None and c["eps"] and c["announcements"]


def test_an_empty_response_is_not_cached(monkeypatch):
    """빈 응답을 캐시에 박아 두면 한 시간 동안 계속 빈 채로 나온다."""
    wire(monkeypatch, FakeTicker(est=pd.DataFrame(), dates=pd.DataFrame()))
    assert consensus.fetch("ZZZZ")["eps"] == {}
    wire(monkeypatch, FakeTicker())
    assert consensus.fetch("ZZZZ")["eps"] != {}
