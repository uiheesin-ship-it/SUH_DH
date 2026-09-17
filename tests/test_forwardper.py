"""12M forward PER — 실적발표일 기준으로 계단을 밟는지 검증.

네트워크 없이 돈다. 여기서 못 박으려는 건 세 가지다.

  계단은 **발표일**에 밟는다. 기준일(분기말)에 밟으면 아직 공개되지 않은
  실적으로 그 사이 주가를 나누게 된다 — 미래 정보가 과거 차트에 샌다.
  확정 실적만으로 만든 구간과 컨센이 섞인 구간이 **구분**된다(실선/점선).
  야후가 주는 분기 컨센은 0q·+1q 둘뿐이라, 나머지는 연간 추정에서 이미 아는
  분기를 빼고 남은 분기에 나눈다(실측 8/8종목).
"""

from __future__ import annotations

from datetime import date

from app import forwardper as F


def q(end, val, filed, announced=None):
    r = {"end": end, "val": val, "first_filed": filed, "last_filed": filed}
    if announced:
        r["announced"] = announced
    return r


# 2024~2026, 분기마다 EPS 1.0 씩 (합 4.0)
QUARTERS = [q(f"{y}-{m}", 1.0, f"{fy}-{fm}")
            for y, m, fy, fm in [
                (2024, "03-31", 2024, "04-25"), (2024, "06-30", 2024, "07-25"),
                (2024, "09-30", 2024, "10-25"), (2024, "12-31", 2025, "01-25"),
                (2025, "03-31", 2025, "04-25"), (2025, "06-30", 2025, "07-25"),
                (2025, "09-30", 2025, "10-25"), (2025, "12-31", 2026, "01-25"),
            ]]


# ---------------------------------------------------------------- 발표일 붙이기
def test_the_announcement_date_comes_from_yahoo_when_available():
    """보도자료 날짜가 EDGAR 제출일보다 낫다 — 제출은 며칠 늦다."""
    out = F.match_announcements(QUARTERS[:2], ["2024-04-24", "2024-07-23"])
    assert [r["announced"] for r in out] == ["2024-04-24", "2024-07-23"]
    assert out[0]["announced_source"] == "실적발표일(야후)"


def test_it_falls_back_to_the_edgar_filing_date():
    out = F.match_announcements(QUARTERS[:2], [])
    assert [r["announced"] for r in out] == ["2024-04-25", "2024-07-25"]
    assert out[0]["announced_source"] == "EDGAR 제출일"


def test_an_announcement_is_never_used_for_two_quarters():
    """한 번 쓴 발표일을 다시 쓰면 계단이 무너진다."""
    out = F.match_announcements(QUARTERS[:3], ["2024-04-24"])
    assert out[0]["announced"] == "2024-04-24"
    assert out[1]["announced"] == "2024-07-25"          # EDGAR 로 물러선다
    assert out[2]["announced"] == "2024-10-25"


def test_a_date_too_far_from_the_quarter_end_is_not_its_announcement():
    out = F.match_announcements([q("2024-03-31", 1.0, "")], ["2024-12-01"])
    assert out[0]["announced"] is None


# ------------------------------------------------------------------ 창 만들기
def test_the_window_opens_on_the_announcement_not_the_quarter_end():
    """2024-03-31 분기는 4월 25일에 발표된다 — 창은 그날 열린다."""
    qs = F.match_announcements(QUARTERS, [])
    w = F.forward_windows(qs, {})
    assert w[0]["from"] == "2024-04-25"
    assert w[0]["basis_end"] == "2024-03-31"
    # 앞으로 4분기 = 2024-06-30 … 2025-03-31
    assert [r["end"] for r in w[0]["quarters"]] == [
        "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]
    assert w[0]["eps"] == 4.0
    assert w[0]["confirmed"] is True


def test_a_window_closes_when_the_next_quarter_is_announced():
    qs = F.match_announcements(QUARTERS, [])
    w = F.forward_windows(qs, {})
    assert w[0]["to"] == "2024-07-25"
    assert w[-1]["to"] == "2025-04-25"    # 뒤 분기가 더 있으면 닫힌다


def test_windows_without_four_forward_quarters_are_dropped():
    """추정으로도 못 채우면 값을 지어내지 않는다."""
    qs = F.match_announcements(QUARTERS, [])
    w = F.forward_windows(qs, {})
    assert len(w) == len(QUARTERS) - 4    # 마지막 4개 분기는 창을 못 연다


# --------------------------------------------------------------- 컨센 채우기
def test_the_two_quarterly_estimates_are_used_as_is():
    ends = F.project_ends("2025-12-31", 4)
    assert ends[:2] == ["2026-03-31", "2026-06-30"]
    filled = F.fill_estimates(ends, {"0q": 1.2, "+1q": 1.3}, [], {})
    assert filled["2026-03-31"]["val"] == 1.2
    assert filled["2026-06-30"]["val"] == 1.3


def test_the_annual_estimate_is_spread_over_what_is_left_not_over_four():
    """연간 추정에는 이미 발표된 분기가 들어 있다 — 그걸 빼야 남은 기대치다.

    연간 6.0 인데 이미 3분기가 1.0+1.0+1.0 으로 확정됐으면 남은 한 분기의
    기대치는 3.0 이다. 6.0÷4 = 1.5 로 하면 계절성 큰 회사가 크게 틀어진다.
    """
    known = {"2026-03-31": 1.0, "2026-06-30": 1.0, "2026-09-30": 1.0}
    ends = F.project_ends("2026-09-30", 4)        # 2026-12-31 …
    filled = F.fill_estimates(ends, {"0y": 6.0}, ["2026-12-31", "2027-12-31"], known)
    assert filled["2026-12-31"]["val"] == 3.0
    assert "0y" in filled["2026-12-31"]["source"]


def test_the_next_year_estimate_covers_the_year_after():
    known = {"2026-09-30": 1.0}
    ends = F.project_ends("2026-09-30", 6)
    filled = F.fill_estimates(ends, {"0y": 5.0, "+1y": 8.0},
                              ["2026-12-31", "2027-12-31"], known)
    assert filled["2026-12-31"]["val"] == 4.0            # 5.0 − 1.0
    for e in ["2027-03-31", "2027-06-30", "2027-09-30", "2027-12-31"]:
        assert filled[e]["val"] == 2.0                   # 8.0 ÷ 4


def test_the_current_year_is_the_one_holding_the_first_unreported_quarter():
    """4분기를 막 발표했다면 0y 는 이미 다음 회계연도다."""
    ends = F.project_ends("2026-12-31", 4)
    filled = F.fill_estimates(ends, {"0y": 8.0}, ["2026-12-31", "2027-12-31"], {})
    assert filled["2027-03-31"]["val"] == 2.0


# ------------------------------------------------------------- 확정 vs 추정
def test_a_window_touching_an_estimate_is_not_confirmed():
    """한 분기라도 추정이 섞이면 점선이다."""
    qs = F.match_announcements(QUARTERS, [])
    est = {e: {"val": 1.5, "source": "컨센 0q"}
           for e in F.project_ends("2025-12-31", 4)}
    w = F.forward_windows(qs, est)
    last = w[-1]
    assert last["basis_end"] == "2025-12-31"
    assert last["confirmed"] is False
    assert last["estimated"] == 4
    assert last["eps"] == 6.0
    assert last["to"] is None             # 가장 최근 창은 오늘까지 이어진다
    # 그 앞 창은 아직 확정이다
    assert w[-5]["confirmed"] is True


# ----------------------------------------------------------------- PER 계열
def test_the_per_steps_on_the_announcement_date():
    qs = F.match_announcements(QUARTERS, [])
    w = F.forward_windows(qs, {})
    dates = ["2024-04-24", "2024-04-25", "2024-07-24", "2024-07-25"]
    out = F.per_series(dates, [100.0] * 4, w)
    assert out[0]["per"] is None          # 첫 발표 전 — 계산할 근거가 없다
    assert out[1]["per"] == 25.0          # 100 ÷ 4.0
    assert out[2]["per"] == 25.0
    assert out[3]["per"] == 25.0          # 다음 창도 합이 4.0


def test_a_loss_making_forward_window_has_no_per():
    """적자 구간의 PER 은 음수로 나온다 — 그리면 차트도 독해도 망가진다."""
    qs = F.match_announcements([q("2024-03-31", 1.0, "2024-04-25"),
                                q("2024-06-30", -1.0, "2024-07-25"),
                                q("2024-09-30", -1.0, "2024-10-25"),
                                q("2024-12-31", -1.0, "2025-01-25"),
                                q("2025-03-31", -1.0, "2025-04-25")], [])
    w = F.forward_windows(qs, {})
    assert w[0]["eps"] == -4.0
    out = F.per_series(["2024-05-01"], [100.0], w)
    assert out[0]["per"] is None


def test_add_months_does_not_overflow_a_short_month():
    assert F.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert F.add_months(date(2026, 12, 31), 3) == date(2027, 3, 31)
    assert F.add_months(date(2026, 3, 31), -12) == date(2025, 3, 31)
    # 분기말은 분기말로 — 9/30 + 3개월은 12/30 이 아니라 12/31 이다
    assert F.add_months(date(2026, 9, 30), 3) == date(2026, 12, 31)
    assert F.add_months(date(2026, 2, 28), 1) == date(2026, 3, 31)
