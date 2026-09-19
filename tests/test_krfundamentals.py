"""DART 정기보고서 → 분기 계열 검증 — 네트워크 없이 합성 보고서로.

국장에서 조용히 틀리는 길이 셋 있다.

  손익의 thstrm_amount 를 **누적으로 착각**하면 2·3분기가 부풀어 오른다.
  사업보고서의 연간값을 그대로 Q4 로 쓰면 4분기가 한 해치가 된다.
  현금흐름표는 **누적**이라 차분하지 않으면 감가상각이 분기마다 커진다.
"""

from __future__ import annotations

import pytest

from app import krfundamentals as kf

REPRT = ["11013", "11012", "11014", "11011"]


def row(sj, aid, nm, cur, add=None, dt=None):
    return {"sj_div": sj, "account_id": aid, "account_nm": nm,
            "thstrm_amount": cur, "thstrm_add_amount": add, "thstrm_dt": dt}


def reports(year=2025, rev=(100, 120, 130, 500), da=(10, 21, 33, 44)):
    """rev = (1Q, 2Q, 3Q 각 3개월, 연간). da = 현금흐름표 **누적**."""
    ends = [f"{year}.01.01 ~ {year}.03.31", f"{year}.04.01 ~ {year}.06.30",
            f"{year}.07.01 ~ {year}.09.30", f"{year}.01.01 ~ {year}.12.31"]
    out = {}
    ytd = 0
    for i, rc in enumerate(REPRT):
        rows = []
        if rc == "11011":
            rows.append(row("IS", "ifrs-full_Revenue", "매출액", f"{rev[3]:,}",
                            None, ends[i]))
        else:
            ytd += rev[i]
            rows.append(row("IS", "ifrs-full_Revenue", "매출액", f"{rev[i]:,}",
                            f"{ytd:,}", ends[i]))
        rows.append(row("CF", "ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense",
                        "감가상각비 및 상각비", f"{da[i]:,}", None, ends[i]))
        rows.append(row("BS", "ifrs-full_CashAndCashEquivalents", "현금및현금성자산",
                        "1,000", None, ends[i]))
        out[(year, rc)] = rows
    return out


# --- 손익 -------------------------------------------------------------------
def test_손익은_이미_분기값이라_그대로_쓴다():
    s = kf.income_series(reports(), kf.REVENUE)
    assert s["2025-03-31"]["val"] == 100
    assert s["2025-06-30"]["val"] == 120      # 220(누적)이면 누적으로 착각한 것
    assert s["2025-09-30"]["val"] == 130


def test_Q4_는_연간에서_3분기_누적을_뺀다():
    s = kf.income_series(reports(), kf.REVENUE)
    assert s["2025-12-31"]["val"] == 500 - 350
    assert "연간−3분기 누적" in s["2025-12-31"]["source"]


def test_3분기보고서가_없으면_Q4_를_지어내지_않는다():
    r = reports()
    del r[(2025, "11014")]
    s = kf.income_series(r, kf.REVENUE)
    assert "2025-12-31" not in s


def test_괄호_음수와_쉼표를_푼다():
    r = reports()
    r[(2025, "11013")][0]["thstrm_amount"] = "(1,234)"
    assert kf.income_series(r, kf.REVENUE)["2025-03-31"]["val"] == -1234


# --- 현금흐름표 --------------------------------------------------------------
def test_현금흐름표는_누적이라_차분한다():
    s = kf.cash_flow_series(reports(), kf.DA)
    assert s["2025-03-31"]["val"] == 10
    assert s["2025-06-30"]["val"] == 11       # 21(누적)이면 차분을 안 한 것
    assert s["2025-09-30"]["val"] == 12
    assert s["2025-12-31"]["val"] == 11


def test_회계연도가_바뀌면_누적도_다시_시작한다():
    s = kf.cash_flow_series({**reports(2025), **reports(2026)}, kf.DA)
    # 2026 첫 분기는 2025 연말 누적(44)을 빼면 안 된다
    assert s["2026-03-31"]["val"] == 10
    assert s["2025-12-31"]["val"] == 11


# --- 기간 끝 ----------------------------------------------------------------
def test_기간은_thstrm_dt_에서_읽는다():
    rows = [row("IS", "x", "y", "1", None, "2026.01.01 ~ 2026.03.31")]
    assert kf.period_end(rows, 2026, "11013") == "2026-03-31"


def test_thstrm_dt_가_없으면_12월_결산으로_만든다():
    rows = [row("IS", "x", "y", "1")]
    assert kf.period_end(rows, 2026, "11014") == "2026-09-30"


# --- 계정 고르기 -------------------------------------------------------------
def test_같은_이름이_여러_재무제표에_있으면_재무제표로_좁힌다():
    """비지배지분은 BS·CIS·CF 에 다 있다. 좁히지 않으면 엉뚱한 값이 잡힌다."""
    rows = [row("CIS", "ifrs-full_ProfitLossAttributableToNoncontrollingInterests",
                "비지배지분", "999"),
            row("BS", "ifrs-full_NoncontrollingInterests", "비지배지분", "286")]
    got = kf._pick(rows, ["ifrs-full_NoncontrollingInterests"], ["비지배지분"], ("BS",))
    assert got["thstrm_amount"] == "286"


def test_표준_계정코드가_이름보다_먼저다():
    rows = [row("IS", "", "매출액", "111"),
            row("IS", "ifrs-full_Revenue", "수익", "222")]
    assert kf._pick(rows, ["ifrs-full_Revenue"], ["매출액"], ("IS",))["thstrm_amount"] == "222"


# --- 조립 -------------------------------------------------------------------
def test_EBITDA_는_영업이익에_차분한_감가상각을_더한다():
    r = reports()
    for (y, rc), rows in r.items():
        rows.append(row("IS", "dart_OperatingIncomeLoss", "영업이익",
                        "1,000" if rc != "11011" else "4,000",
                        "1,000" if rc == "11013" else
                        ("2,000" if rc == "11012" else
                         ("3,000" if rc == "11014" else None)),
                        rows[0]["thstrm_dt"]))
    m = kf.build_metrics(r)
    q = {x["end"]: x["val"] for x in m["EBITDA"]["quarters"]}
    assert q["2025-06-30"] == 1000 + 11
    assert m["EBITDA"]["adjusted"] is False


def test_감가상각이_없는_회사는_EBITDA_가_빈다():
    r = reports()
    for rows in r.values():
        rows[:] = [x for x in rows if x["sj_div"] != "CF"]
        rows.append(row("IS", "dart_OperatingIncomeLoss", "영업이익", "1,000"))
    assert kf.build_metrics(r)["EBITDA"]["quarters"] == []
