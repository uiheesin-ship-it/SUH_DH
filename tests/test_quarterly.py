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
    """2022-03 ~ 2026-06, 분기 EPS 1.0 / 순이익 100 / 매출 1000 / 주식수 1억."""
    eps, ni, rev, ann, sh = [], [], [], [], []
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
            sh.append(fact(f"{y}-{s}", f"{y}-{e}", 100_000_000.0, filed))
        if y < 2026:
            ann.append(fact(f"{y}-01-01", f"{y}-12-31", 400.0, f"{y + 1}-02-20", "10-K"))
            eps.append(fact(f"{y}-01-01", f"{y}-12-31", 4.0, f"{y + 1}-02-20", "10-K"))
            rev.append(fact(f"{y}-01-01", f"{y}-12-31", 4000.0, f"{y + 1}-02-20", "10-K"))
    return {"facts": {"us-gaap": {
        "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
        "NetIncomeLoss": {"units": {"USD": ni + ann}},
        "Revenues": {"units": {"USD": rev}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": sh}},
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


# 발표일마다 조정 EPS(Reported EPS)가 같이 온다 — GAAP 1.0 보다 20% 크게.
ANN = [{"date": d, "reported_eps": 1.2} for d in
       [f"{y}-{m}" for y in (2022, 2023, 2024, 2025) for m in
        ("04-25", "07-25", "10-25", "01-25")] + ["2026-04-22", "2026-07-22"]]
FULL_CON = {"eps": {"0q": {"avg": 1.5}, "+1q": {"avg": 1.6},
                    "0y": {"avg": 6.0}, "+1y": {"avg": 8.0}},
            "announcements": ANN,
            "sources": ["야후 earnings_estimate", "야후 get_earnings_dates"],
            "shares": 1000.0, "market_cap": 100000.0}
CON_NO_ADJ = {**FULL_CON,
              "announcements": [{"date": "2026-04-22"}, {"date": "2026-07-22"}]}


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
    by_end = {q["end"]: q for q in quarterly.build("TEST")["per"]["quarters"]}
    assert by_end["2026-03-31"]["announced"] == "2026-04-22"
    assert by_end["2026-03-31"]["source"] == "실적발표일(야후)"


def test_a_quarter_without_a_yahoo_date_falls_back_to_edgar(monkeypatch):
    """발표일이 없는 분기는 EDGAR 제출일로 물러선다 — 기준일보다는 낫다."""
    wire(monkeypatch, con=CON_NO_ADJ)
    by_end = {q["end"]: q for q in quarterly.build("TEST")["per"]["quarters"]}
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


# ------------------------------------------ 컨센 칸이 확정 실적 옆에 붙는가
def test_each_metric_gets_a_forecast_block(monkeypatch):
    wire(monkeypatch, con=FULL_CON)
    m = quarterly.build("TEST")["metrics"]
    for label in ("매출", "영업이익", "순이익", "희석EPS"):
        assert "estimates" in m[label], label
        assert len(m[label]["estimates"]["years"]) == 3, label


def test_operating_income_has_no_consensus_and_says_why(monkeypatch):
    """야후에도 Alpha Vantage 에도 영업이익 컨센이 없다(실측)."""
    wire(monkeypatch, con=FULL_CON)
    e = quarterly.build("TEST")["metrics"]["영업이익"]["estimates"]
    assert e["quarters"] == [] and e["source"] == "없음"
    assert "영업이익" in e["reason"]


def test_revenue_and_eps_consensus_land_on_real_dates(monkeypatch):
    """야후는 0q/+1q 라는 상대 이름만 준다 — 날짜는 EDGAR 쪽에서 만들어 붙인다."""
    wire(monkeypatch, con=FULL_CON)
    e = quarterly.build("TEST")["metrics"]["희석EPS"]["estimates"]
    assert [q["end"] for q in e["quarters"]] == ["2026-09-30", "2026-12-31"]
    assert e["quarters"][0]["val"] == 1.5
    assert e["years"][0]["end"] == "2026-12-31" and e["years"][0]["val"] == 6.0
    assert e["years"][-1]["val"] is None          # 내후년은 안 나온다


def test_net_income_consensus_is_eps_times_shares_and_labelled(monkeypatch):
    """순이익 컨센은 어디에도 없다 — EPS 컨센 × 주식수로 만들고 그렇게 적는다."""
    wire(monkeypatch, con=FULL_CON)
    m = quarterly.build("TEST")["metrics"]
    shares = m["가중평균주식수"]["quarters"][-1]["val"]
    assert shares == 100_000_000
    e = m["순이익"]["estimates"]
    assert e["quarters"][0]["val"] == 1.5 * shares
    assert "주식수" in e["source"]


def test_without_a_share_count_the_net_income_columns_stay_empty(monkeypatch):
    """주식수를 못 구하면 지어내지 않는다."""
    facts = _facts()
    del facts["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]
    monkeypatch.setattr(quarterly.secdata, "fetch",
                        lambda t: ("1", {"name": "T", "sic": "S", "fiscal_year_end": "1231"}, facts))
    monkeypatch.setattr(quarterly.charts, "get_chart", lambda t, r: dict(PRICES))
    monkeypatch.setattr(quarterly.consensus, "fetch", lambda t: FULL_CON)
    e = quarterly.build("TEST")["metrics"]["순이익"]["estimates"]
    assert e["quarters"] == [] and e["source"] == "없음"
    assert "주식수" in e["reason"]


# ------------------------------------------------- EPS 기준 (GAAP vs 조정)
def test_both_bases_are_built_and_adjusted_is_the_default(monkeypatch):
    """조정이 기본 — 컨센과 같은 기준이라 실선→점선 경계에서 선이 안 꺾인다."""
    wire(monkeypatch, con=FULL_CON)
    r = quarterly.build("TEST")
    assert set(r["per_bases"]) == {"gaap", "adjusted"}
    assert r["per_basis"] == "adjusted"
    assert r["per"] is r["per_bases"]["adjusted"]
    assert r["per_bases"]["gaap"]["eps_basis_label"].startswith("GAAP")


def test_the_two_bases_give_different_per(monkeypatch):
    """조정 EPS 가 GAAP 보다 20% 크면 PER 은 그만큼 낮아야 한다."""
    wire(monkeypatch, con=FULL_CON)
    b = quarterly.build("TEST")["per_bases"]
    g = [v for v in b["gaap"]["per_confirmed"] if v]
    a = [v for v in b["adjusted"]["per_confirmed"] if v]
    assert g and a
    assert a[-1] < g[-1], "조정 EPS 가 더 큰데 PER 이 더 낮지 않다"


def test_without_adjusted_history_it_falls_back_to_gaap(monkeypatch):
    """발표일이 두 개뿐이면 조정 계열이 너무 짧다 — GAAP 으로만 그리고 그렇게 말한다."""
    wire(monkeypatch, con=CON_NO_ADJ)
    r = quarterly.build("TEST")
    assert set(r["per_bases"]) == {"gaap"} and r["per_basis"] == "gaap"
    assert any("조정" in n for n in r["notes"])


def test_the_adjusted_series_never_borrows_a_gaap_value(monkeypatch):
    """조정값이 없는 분기를 GAAP 으로 메우면 그게 다시 기준 섞임이다."""
    con = {**FULL_CON, "announcements":
           [{**a, "reported_eps": (None if a["date"].startswith("2023") else 1.2)}
            for a in ANN]}
    wire(monkeypatch, con=con)
    b = quarterly.build("TEST")["per_bases"]
    assert b["adjusted"]["eps_quarters"] < b["gaap"]["eps_quarters"]
