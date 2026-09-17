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
def test_bank_revenue_falls_back_to_net_interest_plus_noninterest():
    """은행은 매출 태그가 없다(실측 JPM 0개). 총수익 = 순이자이익 + 비이자이익.

    이자 쪽은 **순액**이어야 한다. 총이자수익을 더하면 이자비용을 빼지 않아
    매출이 부풀고, 그 태그는 회사가 중간에 버리는 일도 잦다.
    """
    f = facts_of(
        InterestIncomeExpenseNet=[fact("2025-01-01", "2025-03-31", 300, "2025-05-01")],
        NoninterestIncome=[fact("2025-01-01", "2025-03-31", 200, "2025-05-01")],
        NetIncomeLoss=[fact("2025-01-01", "2025-03-31", 120, "2025-05-01")],
    )
    m = F.build_metrics(f)
    assert m["매출"]["quarters"][0]["val"] == 500
    assert "계산값" in m["매출"]["source"]
    # 영업이익은 은행에 개념이 없다 — 억지로 채우지 않는다.
    assert m["영업이익"]["count"] == 0
    assert "없음" in m["영업이익"]["source"]


def test_depreciation_merges_reported_quarters_with_ytd_differences():
    """보고된 분기값과 누적 차분을 **합쳐야** EBITDA 가 안 끊긴다.

    AAPL 은 분기 D&A 태그가 6개뿐이라, 둘 중 하나만 쓰면 영업이익이 20분기인데
    EBITDA 는 9분기에서 멈춘다. 겹치는 자리는 보고값이 이긴다.
    """
    f = facts_of(
        OperatingIncomeLoss=[fact(f"2025-0{q * 3 - 2}-01", e, 200, "2025-12-01")
                             for q, e in enumerate(["2025-03-31", "2025-06-30",
                                                    "2025-09-30"], 1)],
        # 분기 태그는 1분기 것만 있고, 누적은 3분기까지 다 있다.
        DepreciationDepletionAndAmortization=[
            fact("2025-01-01", "2025-03-31", 30, "2025-05-01"),
            fact("2025-01-01", "2025-06-30", 62, "2025-08-01"),
            fact("2025-01-01", "2025-09-30", 95, "2025-11-01"),
        ],
        NetIncomeLoss=[fact("2025-01-01", "2025-03-31", 150, "2025-05-01")],
    )
    m = F.build_metrics(f)
    assert m["EBITDA"]["count"] == 3, "누적 차분을 안 써서 EBITDA 가 끊겼다"
    vals = {q["end"]: q["val"] for q in m["EBITDA"]["quarters"]}
    assert vals["2025-03-31"] == 230            # 200 + 30 (보고값)
    assert round(vals["2025-06-30"]) == 232     # 200 + 32 (차분)
    assert "보고값" in m["EBITDA"]["source"] and "차분" in m["EBITDA"]["source"]


def test_missing_metrics_do_not_raise():
    """태그가 하나도 없어도 빈 시계열을 돌려줄 뿐 터지지 않는다."""
    m = F.build_metrics(facts_of())
    assert all(v["count"] == 0 for v in m.values())


# ------------------------------------------- 태그를 갈아탄 회사 (PLD·CEG 실측)
def test_a_tag_switch_does_not_truncate_the_series():
    """회사가 중간에 태그를 바꾸면 예전 코드는 옛 태그에서 멈춰 버렸다.

    PLD 는 감가상각이 2015년에서 끊겨 EBITDA 최근값이 2015-12-31 로 찍혔고,
    CEG 는 매출이 14분기만 나왔다. 우선순위는 지키되 빈 분기는 메워야 한다.
    """
    f = facts_of(
        Revenues=[                                   # 옛 태그 — 2016년까지만
            fact("2016-01-01", "2016-03-31", 100, "2016-05-01"),
            fact("2016-04-01", "2016-06-30", 110, "2016-08-01"),
        ],
        RevenueFromContractWithCustomerExcludingAssessedTax=[   # 새 태그 — 이후
            fact("2025-01-01", "2025-03-31", 900, "2025-05-01"),
            fact("2025-04-01", "2025-06-30", 950, "2025-08-01"),
        ],
    )
    q = F.collect(f, F.REVENUE_TAGS, *F.QUARTER_DAYS)
    assert sorted(q) == ["2016-03-31", "2016-06-30", "2025-03-31", "2025-06-30"]


def test_the_higher_priority_tag_wins_on_a_shared_quarter():
    """둘 다 값을 낸 분기는 앞 태그가 이긴다 — 메우는 건 빈 자리뿐이다."""
    f = facts_of(
        Revenues=[fact("2025-01-01", "2025-03-31", 100, "2025-05-01")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            fact("2025-01-01", "2025-03-31", 999, "2025-05-01")],
    )
    q = F.collect(f, F.REVENUE_TAGS, *F.QUARTER_DAYS)
    assert q["2025-03-31"]["val"] == 999          # 목록에서 앞선 쪽
    assert q["2025-03-31"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_ytd_differences_never_mix_two_tags():
    """누적 차분은 태그별로 따로 해야 한다 — 섞어 빼면 값이 엉킨다."""
    f = facts_of(
        DepreciationDepletionAndAmortization=[
            fact("2025-01-01", "2025-03-31", 30, "2025-05-01"),
            fact("2025-01-01", "2025-06-30", 65, "2025-08-01"),
        ],
        DepreciationAndAmortization=[
            fact("2025-01-01", "2025-09-30", 5000, "2025-11-01"),   # 다른 계열
        ],
    )
    q = F.quarterly_from_ytd(f, F.DA_TAGS)
    assert q["2025-06-30"]["val"] == 35            # 65 − 30, 5000 과 무관
    assert q["2025-09-30"]["val"] == 5000          # 제 계열의 첫 누적


# ------------------------------------------------ 평균 항목의 Q4 (SMCI 실측)
def _three_quarters(val):
    return {
        "2025-09-30": {"end": "2025-09-30", "start": "2025-07-01", "val": val,
                       "first_val": val, "first_filed": "2024-11-01",
                       "last_filed": "2024-11-01"},
        "2025-12-31": {"end": "2025-12-31", "start": "2025-10-01", "val": val,
                       "first_val": val, "first_filed": "2025-02-01",
                       "last_filed": "2025-02-01"},
        "2026-03-31": {"end": "2026-03-31", "start": "2026-01-01", "val": val,
                       "first_val": val, "first_filed": "2025-05-01",
                       "last_filed": "2025-05-01"},
    }


def test_share_count_q4_is_never_negative():
    """가중평균주식수는 평균이라 연간 − 3분기 로 빼면 −2A 가 나온다."""
    quarters = _three_quarters(676_000_000)
    annual = {"2026-06-30": {"end": "2026-06-30", "start": "2025-07-01",
                             "val": 680_000_000, "first_val": 680_000_000,
                             "first_filed": "2026-08-01", "last_filed": "2026-08-01",
                             "form": "10-K"}}
    naive = F.derive_q4(quarters, annual)["2026-06-30"]["val"]
    assert naive < 0                                   # 예전 동작 — 이래서 터졌다

    out = F.derive_q4(quarters, annual, mode="mean")["2026-06-30"]
    assert out["val"] > 0
    assert out["val"] == 4 * 680_000_000 - 3 * 676_000_000
    assert out["derived"] == "4×연평균−3분기"


def test_build_metrics_gives_a_positive_share_count():
    """조립까지 거쳐도 주식수는 양수여야 한다."""
    f = facts_of(WeightedAverageNumberOfDilutedSharesOutstanding=[
        fact("2025-07-01", "2025-09-30", 676_000_000, "2025-11-01"),
        fact("2025-10-01", "2025-12-31", 676_000_000, "2026-02-01"),
        fact("2026-01-01", "2026-03-31", 676_000_000, "2026-05-01"),
        fact("2025-07-01", "2026-06-30", 680_000_000, "2026-08-01", "10-K"),
    ])
    qs = F.build_metrics(f)["가중평균주식수"]["quarters"]
    assert all(q["val"] > 0 for q in qs)


def test_a_mean_mode_q4_that_goes_nonpositive_is_dropped():
    """근사가 깨지면(음수가 나오면) 값을 지어내지 않고 버린다."""
    quarters = _three_quarters(676_000_000)
    annual = {"2026-06-30": {"end": "2026-06-30", "start": "2025-07-01",
                             "val": 400_000_000, "first_val": 400_000_000,
                             "first_filed": "2026-08-01", "last_filed": "2026-08-01"}}
    assert "2026-06-30" not in F.derive_q4(quarters, annual, mode="mean")


# ------------------------------------------------------------ 끊긴 항목 경고
def test_a_metric_stuck_in_the_past_is_flagged():
    """한 항목만 옛날에서 멈추면 그 값을 '최근'이라 부르면 안 된다."""
    f = facts_of(
        Revenues=[fact("2026-01-01", "2026-03-31", 100, "2026-05-01")],
        NetIncomeLoss=[fact("2015-01-01", "2015-03-31", 9, "2015-05-01")],
    )
    m = F.build_metrics(f)
    assert "warning" not in m["매출"]
    assert m["순이익"]["stale_days"] > 200
    assert "2015-03-31" in m["순이익"]["warning"]


def test_a_bank_total_revenue_tag_beats_the_parts_when_it_reaches_further():
    """조각 합계가 옛날에서 끊기면 총수익 태그를 쓴다 — JPM 이 2014년에서 멈췄다."""
    f = facts_of(
        InterestIncomeExpenseNet=[fact("2014-10-01", "2014-12-31", 300, "2015-02-01")],
        NoninterestIncome=[fact("2014-10-01", "2014-12-31", 200, "2015-02-01")],
        RevenuesNetOfInterestExpense=[
            fact("2026-04-01", "2026-06-30", 4500, "2026-08-01")],
        NetIncomeLoss=[fact("2026-04-01", "2026-06-30", 1200, "2026-08-01")],
    )
    m = F.build_metrics(f)
    assert m["매출"]["quarters"][-1]["end"] == "2026-06-30"
    assert m["매출"]["quarters"][-1]["val"] == 4500
    assert "warning" not in m["매출"]


def test_gross_interest_income_is_never_added_to_noninterest_income():
    """총이자수익 + 비이자수익은 매출이 아니다 — 이자비용이 빠지지 않는다."""
    f = facts_of(
        InterestAndDividendIncomeOperating=[
            fact("2026-04-01", "2026-06-30", 9000, "2026-08-01")],
        NoninterestIncome=[fact("2026-04-01", "2026-06-30", 200, "2026-08-01")],
        NetIncomeLoss=[fact("2026-04-01", "2026-06-30", 120, "2026-08-01")],
    )
    m = F.build_metrics(f)
    assert all(q["val"] != 9200 for q in m["매출"]["quarters"])


def test_a_stale_generic_revenue_tag_loses_to_a_fresh_bank_total():
    """은행은 일반 매출 태그를 옛날에 잠깐 쓰다 버린다 — 거기서 멈추면 안 된다.

    실측: JPM 2014-12-31, WFC 2020-09-30, MS 2018-03-31 에서 끊겨 있었다.
    """
    f = facts_of(
        Revenues=[fact("2018-01-01", "2018-03-31", 5910, "2018-05-01")],
        RevenuesNetOfInterestExpense=[
            fact("2026-01-01", "2026-03-31", 17000, "2026-05-01"),
            fact("2026-04-01", "2026-06-30", 18000, "2026-08-01")],
        NetIncomeLoss=[fact("2026-04-01", "2026-06-30", 5581, "2026-08-01")],
    )
    m = F.build_metrics(f)
    assert m["매출"]["quarters"][-1]["end"] == "2026-06-30"
    assert m["매출"]["source"] == "보고값(총수익)"
    assert "warning" not in m["매출"]
