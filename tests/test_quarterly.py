"""티커 하나 → 실적 표 + forward PER 조립 검증.

EDGAR·야후를 전부 가짜로 끼워 넣고 **조립 규칙**만 본다. 특히 세 가지:

  컨센을 못 받아도 확정 구간은 그려진다(차트의 대부분이 그 구간이다).
  실선과 점선이 **따로** 나온다 — 한 배열에 담으면 경계가 그림에서 사라진다.
  실적발표일과 재무정보 기준일이 **둘 다** 나온다.
"""

from __future__ import annotations

import pytest

from app import cache, quarterly


def fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def _facts():
    """2022-03 ~ 2026-06, 분기 EPS 1.0 / 순이익 100 / 매출 1000."""
    eps, ni, rev, ann = [], [], [], []
    for y in range(2022, 2027):
        for i, (s, e) in enumerate([("01-01", "03-31"), ("04-01", "06-30"),
                                    ("07-01", "09-30"), ("10-01", "12-31")]):
            if y == 2026 and i > 1:
                continue
            filed = f"{y + (i == 3)}-{['04-25','07-25','10-25','01-25'][i]}"
            if i == 3:
                continue                   # Q4 는 10-K 에서 역산된다
            eps.append(fact(f"{y}-{s}", f"{y}-{e}", 1.0, filed))
            ni.append(fact(f"{y}-{s}", f"{y}-{e}", 100.0, filed))
            rev.append(fact(f"{y}-{s}", f"{y}-{e}", 1000.0, filed))
        if y < 2026:
            ann.append(fact(f"{y}-01-01", f"{y}-12-31", 400.0, f"{y + 1}-02-20", "10-K"))
            eps.append(fact(f"{y}-01-01", f"{y}-12-31", 4.0, f"{y + 1}-02-20", "10-K"))
            rev.append(fact(f"{y}-01-01", f"{y}-12-31", 4000.0, f"{y + 1}-02-20", "10-K"))
    return {"facts": {"us-gaap": {
        "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
        "NetIncomeLoss": {"units": {"USD": ni + ann}},
        "Revenues": {"units": {"USD": rev}},
    }}}


PRICES = {"dates": [], "close": []}
for _y in range(2022, 2027):
    for _m in range(1, 13):
        if _y == 2026 and _m > 9:
            continue
        PRICES["dates"].append(f"{_y}-{_m:02d}-15")
        PRICES["close"].append(100.0)


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()
    yield
    cache.clear()


def wire(monkeypatch, *, con=None, price=True):
    monkeypatch.setattr(quarterly.secdata, "fetch",
                        lambda t: ("0000000001", {"name": "Test Co", "sic": "S",
                                                  "fiscal_year_end": "1231"}, _facts()))
    monkeypatch.setattr(quarterly.charts, "get_chart",
                        lambda t, r: dict(PRICES) if price else {"dates": [], "close": []})
    if con is None:
        def boom(_t):
            raise TimeoutError("yahoo down")
        monkeypatch.setattr(quarterly.consensus, "fetch", boom)
    else:
        monkeypatch.setattr(quarterly.consensus, "fetch", lambda t: con)


FULL_CON = {"eps": {"0q": {"avg": 1.5}, "+1q": {"avg": 1.6},
                    "0y": {"avg": 6.0}, "+1y": {"avg": 8.0}},
            "announcements": [{"date": "2026-04-22"}, {"date": "2026-07-22"}],
            "sources": ["야후 earnings_estimate", "야후 get_earnings_dates"],
            "shares": 1000.0, "market_cap": 100000.0}


def test_it_still_draws_the_confirmed_part_when_consensus_is_missing(monkeypatch):
    """야후가 죽어도 확정 구간은 나와야 한다 — 차트의 대부분이 거기다."""
    wire(monkeypatch, con=None)
    r = quarterly.build("TEST")
    per = r["per"]
    assert any(v is not None for v in per["per_confirmed"])
    assert all(v is None for v in per["per_estimated"])
    assert any("컨센" in n for n in r["notes"])


def test_the_solid_and_dashed_lines_are_separate_arrays(monkeypatch):
    wire(monkeypatch, con=FULL_CON)
    per = quarterly.build("TEST")["per"]
    assert len(per["per_confirmed"]) == len(per["dates"]) == len(per["per_estimated"])
    assert any(v is not None for v in per["per_confirmed"])
    assert any(v is not None for v in per["per_estimated"])


def test_the_two_lines_meet_so_the_chart_does_not_break(monkeypatch):
    """경계 한 점은 양쪽에 다 들어가야 선이 이어진다."""
    wire(monkeypatch, con=FULL_CON)
    per = quarterly.build("TEST")["per"]
    both = [i for i in range(len(per["dates"]))
            if per["per_confirmed"][i] is not None and per["per_estimated"][i] is not None]
    assert both, "실선과 점선이 만나는 점이 없다 — 차트가 끊긴다"


def test_both_dates_are_reported_for_every_step(monkeypatch):
    """차트에 실적발표일과 재무정보 기준일을 **둘 다** 찍어야 한다."""
    wire(monkeypatch, con=FULL_CON)
    marks = quarterly.build("TEST")["per"]["marks"]
    assert marks
    for m in marks:
        assert m["announced"] and m["basis_end"]
        assert m["announced"] > m["basis_end"], "발표가 기준일보다 빠를 수는 없다"


def test_the_yahoo_announcement_date_wins_over_the_edgar_filing(monkeypatch):
    wire(monkeypatch, con=FULL_CON)
    qs = quarterly.build("TEST")["per"]["quarters"]
    by_end = {q["end"]: q for q in qs}
    assert by_end["2026-03-31"]["announced"] == "2026-04-22"
    assert by_end["2026-03-31"]["source"] == "실적발표일(야후)"
    assert by_end["2025-03-31"]["source"] == "EDGAR 제출일"


def test_the_metrics_table_still_comes_out(monkeypatch):
    wire(monkeypatch, con=FULL_CON)
    m = quarterly.build("TEST")["metrics"]
    assert m["매출"]["count"] == 18   # 4년×4분기 + 2 (Q4 는 연간에서 역산)
    assert m["순이익"]["quarters"][-1]["end"] == "2026-06-30"


def test_no_price_means_no_per_but_the_table_survives(monkeypatch):
    """주가를 못 받아도 실적 표는 나와야 한다."""
    wire(monkeypatch, con=FULL_CON, price=False)
    r = quarterly.build("TEST")
    assert r["metrics"]["매출"]["count"] == 18
    assert r["per"]["dates"] == []
