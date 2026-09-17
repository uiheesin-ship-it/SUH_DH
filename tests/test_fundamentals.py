"""EDGAR companyfacts → 분기 시계열 변환 검증.

네트워크 없이 돈다 — companyfacts 모양의 합성 데이터를 만들어 넣는다.
샌드박스에서는 SEC 가 막혀 있고, 어차피 검증하려는 건 변환 규칙이다.

실측(tools/fundamentals_probe.py, 2026-09-17)에서 확인한 함정들을 그대로 못 박는다:
  10-Q 는 3개월·9개월 수치를 같이 싣는다 → 기간 길이로 걸러야 한다
  10-K 는 분기를 안 싣는다 → Q4 = 연간 − 3분기
  정정공시가 있다 → 실적 표는 마지막, 과거 시점 계산은 첫 제출본
  감가상각은 분기 태그가 6~10개뿐이다 → 누적 차분
  은행은 매출·영업이익 태그가 아예 없다
"""

from __future__ import annotations

import pytest

from app import fundamentals as F


def fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def facts_of(**tags):
    """{"Revenues": [fact, ...]} → companyfacts 모양."""
    return {"facts": {"us-gaap": {t: {"units": {"USD": rows}}
                                  for t, rows in tags.items()}}}


# ------------------------------------------------------- 기간 길이로 걸러내기
def test_ytd_facts_in_a_10q_are_not_mistaken_for_quarters():
    """10-Q 는 3개월과 9개월 수치를 같이 싣는다 — 9개월짜리를 분기로 세면 안 된다."""
    f = facts_of(Revenues=[
        fact("2025-01-01", "2025-03-31", 100, "2025-05-01"),
        fact("2025-04-01", "2025-06-30", 110, "2025-08-01"),
        fact("2025-01-01", "2025-06-30", 210, "2025-08-01"),     # 누적 6개월
        fact("2025-01-01", "2025-09-30", 330, "2025-11-01"),     # 누적 9개월
        fact("2025-07-01", "2025-09-30", 120, "2025-11-01"),
    ])
    q = F.collect(f, ["Revenues"], *F.QUARTER_DAYS)
    assert sorted(q) == ["2025-03-31", "2025-06-30", "2025-09-30"]
    assert [q[e]["val"] for e in sorted(q)] == [100, 110, 120]


# --------------------------------------------------------------- Q4 역산
def test_q4_is_derived_from_the_annual_filing():
    """10-K 는 4분기를 따로 안 싣는다. 연간에서 세 분기를 빼야 나온다."""
    quarters = {
        "2025-03-31": {"end": "2025-03-31", "start": "2025-01-01", "val": 100,
                       "first_val": 100, "first_filed": "2025-05-01", "last_filed": "2025-05-01"},
        "2025-06-30": {"end": "2025-06-30", "start": "2025-04-01", "val": 110,
                       "first_val": 110, "first_filed": "2025-08-01", "last_filed": "2025-08-01"},
        "2025-09-30": {"end": "2025-09-30", "start": "2025-07-01", "val": 120,
                       "first_val": 120, "first_filed": "2025-11-01", "last_filed": "2025-11-01"},
    }
    annual = {"2025-12-31": {"end": "2025-12-31", "start": "2025-01-01", "val": 500,
                             "first_val": 500, "first_filed": "2026-02-01",
                             "last_filed": "2026-02-01", "form": "10-K"}}
    out = F.derive_q4(quarters, annual)
    assert out["2025-12-31"]["val"] == 500 - (100 + 110 + 120)
    assert out["2025-12-31"]["derived"] == "연간−3분기"
    # 분기가 셋이 아니면 만들지 않는다 — 억지로 만들면 조용히 틀린 값이 된다.
    assert "2025-12-31" not in F.derive_q4({k: quarters[k] for k in list(quarters)[:2]}, annual)


# ----------------------------------------------------------------- 정정공시
def test_restatement_keeps_both_the_first_and_the_latest_value():
    """실적 표는 마지막 값이 맞고, 과거 시점 계산은 첫 제출본이 맞다.

    마지막 것만 쓰면 과거 PER 차트에 **미래 정보가 새어 든다** — 그때 시장은
    정정 전 숫자를 보고 있었다.
    """
    f = facts_of(NetIncomeLoss=[
        fact("2025-01-01", "2025-03-31", 90, "2025-05-01"),
        fact("2025-01-01", "2025-03-31", 75, "2026-06-01", form="10-K/A"),   # 1년 뒤 정정
    ])
    q = F.collect(f, ["NetIncomeLoss"], *F.QUARTER_DAYS)["2025-03-31"]
    assert q["val"] == 75 and q["last_filed"] == "2026-06-01"
    assert q["first_val"] == 90 and q["first_filed"] == "2025-05-01"


# ------------------------------------------------------------ 누적 차분(D&A)
def test_depreciation_is_differenced_out_of_the_cumulative_series():
    """감가상각은 현금흐름표에 누적으로 실린다 — 차분해야 분기값이 된다."""
    f = facts_of(DepreciationDepletionAndAmortization=[
        fact("2025-01-01", "2025-03-31", 30, "2025-05-01"),
        fact("2025-01-01", "2025-06-30", 62, "2025-08-01"),
        fact("2025-01-01", "2025-09-30", 95, "2025-11-01"),
    ])
    q = F.quarterly_from_ytd(f, F.DA_TAGS)
    assert [round(q[e]["val"]) for e in sorted(q)] == [30, 32, 33]
    assert q["2025-06-30"]["derived"] == "누적 차분"


# ------------------------------------------------------------------ 성장률
def test_growth_needs_a_positive_base():
    """적자 구간의 증감률은 부호가 뒤집혀 읽는 사람을 속인다 — 주지 않는다."""
    series = [{"val": v} for v in (-10, -5, 50, 60, 80)]
    out = F.with_growth(series)
    assert out[1]["qoq"] is None, "-10 → -5 를 +50% 성장으로 보여 주면 안 된다"
    assert out[3]["qoq"] == pytest.approx(20.0)      # 50 → 60 은 정상
    # 4분기 전이 -10(적자)이므로 YoY 도 주지 않는다. 흑자 전환을 몇 % 로
    # 표현할 방법은 없다 — 숫자를 안 주는 게 맞다.
    assert out[4]["yoy"] is None
    assert out[4]["qoq"] == pytest.approx(33.33, abs=0.01)   # 60 → 80


def test_growth_yoy_compares_the_same_quarter_a_year_earlier():
    series = [{"val": v} for v in (100, 110, 120, 130, 150)]
    out = F.with_growth(series)
    assert out[4]["yoy"] == pytest.approx(50.0)      # 100 → 150
    assert out[4]["qoq"] == pytest.approx(15.38, abs=0.01)   # 130 → 150
    assert out[0]["yoy"] is None and out[0]["qoq"] is None


# --------------------------------------------------------- EBITDA 라벨링
def test_ebitda_is_labelled_as_computed_not_adjusted():
    """실측: 4종목 전부 고유 EBITDA 태그 0개. 계산값을 보고값처럼 보이면 안 된다."""
    f = facts_of(
        OperatingIncomeLoss=[fact("2025-01-01", "2025-03-31", 200, "2025-05-01")],
        DepreciationDepletionAndAmortization=[
            fact("2025-01-01", "2025-03-31", 50, "2025-05-01")],
        NetIncomeLoss=[fact("2025-01-01", "2025-03-31", 150, "2025-05-01")],
    )
    m = F.build_metrics(f)
    e = m["EBITDA"]
    assert e["quarters"][0]["val"] == 250
    assert e["adjusted"] is False
    assert "계산값" in e["source"]
    assert "Adjusted EBITDA 가 아닙니다" in e["note"]


# --------------------------------------------------------------- 은행 처리
def test_bank_revenue_falls_back_to_interest_plus_noninterest():
    """은행은 매출 태그가 없다(실측 JPM 0개). 이자+비이자로 총수익을 만든다."""
    f = facts_of(
        InterestAndDividendIncomeOperating=[
            fact("2025-01-01", "2025-03-31", 300, "2025-05-01")],
        NoninterestIncome=[fact("2025-01-01", "2025-03-31", 200, "2025-05-01")],
        NetIncomeLoss=[fact("2025-01-01", "2025-03-31", 120, "2025-05-01")],
    )
    m = F.build_metrics(f)
    assert m["매출"]["quarters"][0]["val"] == 500
    assert "계산값" in m["매출"]["source"]
    # 영업이익은 은행에 개념이 없다 — 억지로 채우지 않는다.
    assert m["영업이익"]["count"] == 0
    assert "없음" in m["영업이익"]["source"]


def test_missing_metrics_do_not_raise():
    """태그가 하나도 없어도 빈 시계열을 돌려줄 뿐 터지지 않는다."""
    m = F.build_metrics(facts_of())
    assert all(v["count"] == 0 for v in m.values())
