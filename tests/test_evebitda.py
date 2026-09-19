"""EV/EBITDA 조립 검증 — 네트워크 없이 합성 facts 로.

재무상태표 쪽에서 조용히 틀리는 길이 셋 있다. 그 셋을 못 박는다.

  전환사채를 장기차입금에 **또** 더하지 않는다(대개 이미 그 안에 있다).
  ``…AndCapitalLeaseObligations`` 를 쓴 회사에 금융리스를 **또** 더하지 않는다.
  ``StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest``
  (자본 총계)를 비지배지분으로 **쓰지 않는다** — 쓰면 EV 가 자본만큼 부푼다.
"""

from __future__ import annotations

import pytest

from app import evebitda

ENDS = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31",
        "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31",
        "2026-03-31", "2026-06-30"]


def inst(tag, val, unit="USD", ends=None):
    return {tag: {"units": {unit: [{"end": e, "val": val, "filed": e}
                                   for e in (ends or ENDS)]}}}


def dur(tag, val, unit="USD"):
    """분기 기간 사실 — 각 분기 3개월."""
    rows = []
    for e in ENDS:
        y, m = int(e[:4]), int(e[5:7])
        s = f"{y}-{m - 2:02d}-01"
        rows.append({"start": s, "end": e, "val": val, "filed": e, "form": "10-Q"})
    return {tag: {"units": {unit: rows}}}


def facts(**extra):
    base = {}
    base.update(dur("OperatingIncomeLoss", 800.0))
    base.update(dur("DepreciationDepletionAndAmortization", 200.0))
    base.update(dur("Revenues", 5000.0))
    base.update(inst("CommonStockSharesOutstanding", 1_000.0, "shares"))
    base.update(inst("CashAndCashEquivalentsAtCarryingValue", 300.0))
    for k, v in extra.items():
        base.update(v)
    return {"facts": {"us-gaap": base}}


# --- 이중계상 ----------------------------------------------------------------
def test_합계가_더_크면_전환사채는_그_안에_있다():
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0),
              b=inst("ConvertibleNotesPayable", 400.0))
    c = evebitda.components(evebitda.balance_sheet(f), "2026-06-30")
    assert c["debt"] == 1000.0            # 1400 이면 전환사채를 두 번 센 것
    assert c["tags"]["장기차입금(비유동)"] == "LongTermDebtNoncurrent"


def test_합계가_더_작으면_전환사채는_별개다():
    """실측(SMCI 2026-06-30): 장·단기 합계 4.06B 과 전환사채 4.66B 이 따로 잡힌다.

    둘을 더해야 야후 totalDebt(리스 포함 9.26B)와 정확히 맞는다. 합계가 부분보다
    작을 수는 없으니, 작다는 건 그 안에 안 들어 있다는 뜻이다.
    """
    f = facts(a=inst("DebtLongtermAndShorttermCombinedAmount", 4056.0),
              b=inst("ConvertibleLongTermNotesPayable", 4664.0),
              c=inst("OperatingLeaseLiabilityNoncurrent", 499.0),
              d=inst("OperatingLeaseLiabilityCurrent", 41.0))
    c = evebitda.components(evebitda.balance_sheet(f), "2026-06-30")
    assert c["debt"] == pytest.approx(4056 + 4664 + 499 + 41)


def test_리스_합계와_유동_비유동이_같이_오면_합계는_버린다():
    f = facts(a=inst("OperatingLeaseLiability", 540.0),
              b=inst("OperatingLeaseLiabilityNoncurrent", 499.0),
              c=inst("OperatingLeaseLiabilityCurrent", 41.0))
    c = evebitda.components(evebitda.balance_sheet(f), "2026-06-30")
    assert c["debt"] == pytest.approx(540.0)       # 1080 이면 두 배로 센 것


def test_리스를_안_나눠_올리면_합계를_쓴다():
    f = facts(a=inst("OperatingLeaseLiability", 540.0))
    c = evebitda.components(evebitda.balance_sheet(f), "2026-06-30")
    assert c["debt"] == pytest.approx(540.0)


def test_차입금_수단을_갈아탄_구간도_0_이_되지_않는다():
    """실측(SMCI): 옛날엔 은행 차입, 지금은 전환사채. 회사 전체에서 태그를 하나만
    고르면 최근 구간이 통째로 0 이 되어 EV 가 41% 작게 나왔다."""
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0, ends=ENDS[:4]),
              b=inst("ConvertibleNotesPayable", 9000.0, ends=ENDS[4:]))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2024-06-30")["debt"] == 1000.0
    assert evebitda.components(bs, "2026-06-30")["debt"] == 9000.0


def test_장기차입금_태그가_없으면_전환사채를_쓴다():
    f = facts(b=inst("ConvertibleNotesPayable", 400.0))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2026-06-30")["debt"] == 400.0


def test_리스포함_태그면_금융리스를_또_더하지_않는다():
    f = facts(a=inst("LongTermDebtAndCapitalLeaseObligations", 1000.0),
              b=inst("FinanceLeaseLiabilityNoncurrent", 250.0))
    c = evebitda.components(evebitda.balance_sheet(f), "2026-06-30")
    assert c["debt"] == 1000.0
    assert "금융리스부채(비유동)" not in c["parts"]
    assert "금융리스부채(비유동)" not in c["absent"]      # 빠진 게 아니라 이미 들어 있다


def test_운용리스는_따로_더한다():
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0),
              b=inst("OperatingLeaseLiabilityNoncurrent", 250.0))
    assert evebitda.components(evebitda.balance_sheet(f), "2026-06-30")["debt"] == 1250.0


def test_자본총계_태그를_비지배지분으로_쓰지_않는다():
    f = facts(a=inst("StockholdersEquityIncludingPortionAttributableToNoncontrolling"
                     "Interest", 50_000.0))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2026-06-30")["other"] == 0.0


def test_비지배지분과_우선주는_더한다():
    f = facts(a=inst("MinorityInterest", 100.0), b=inst("PreferredStockValue", 30.0))
    assert evebitda.components(evebitda.balance_sheet(f), "2026-06-30")["other"] == 130.0


# --- as-of ------------------------------------------------------------------
def test_한_분기보다_멀면_끌어오지_않는다():
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0, ends=["2024-03-31"]))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2024-03-31")["debt"] == 1000.0
    assert evebitda.components(bs, "2026-06-30")["debt"] == 0.0     # 조용한 이월 금지


def test_주식수는_옛_태그에서_멈추지_않고_표지로_메운다():
    """실측: WMT 는 CommonStockSharesOutstanding 이 2012년까지 4분기뿐이다.

    버킷 규칙(첫 태그 하나만)을 그대로 쓰면 그 4분기를 잡고 멈춰서 최근 시총이
    안 만들어지고 EV/EBITDA 가 통째로 사라진다.
    """
    f = facts()
    f["facts"]["us-gaap"].update(
        inst("CommonStockSharesOutstanding", 900.0, "shares", ends=["2024-03-31"]))
    f["facts"]["dei"] = inst("EntityCommonStockSharesOutstanding", 1_100.0, "shares")
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2024-03-31")["shares"] == 900.0    # 옛 태그가 이긴다
    assert evebitda.components(bs, "2026-06-30")["shares"] == 1_100.0  # 빈 자리는 표지로


def test_자기주식_포함_태그보다_표지를_먼저_쓴다():
    """JPM 은 발행 41.0억 주 vs 유통 27.0억 주 — 1.5배 차이가 난다."""
    f = facts()
    del f["facts"]["us-gaap"]["CommonStockSharesOutstanding"]
    f["facts"]["us-gaap"].update(inst("CommonStockSharesIssued", 4_100.0, "shares"))
    f["facts"]["dei"] = inst("EntityCommonStockSharesOutstanding", 2_700.0, "shares")
    assert evebitda.components(evebitda.balance_sheet(f), "2026-06-30")["shares"] == 2_700.0


def test_그_날짜에만_없는_버킷은_따로_알려_준다():
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0),
              b=inst("OperatingLeaseLiabilityNoncurrent", 250.0, ends=["2024-03-31"]))
    c = evebitda.components(evebitda.balance_sheet(f), "2026-06-30")
    assert c["debt"] == 1000.0
    assert "운용리스부채(비유동)" in c["absent"]      # 전 기간 없는 것과 구별


def test_다음_분기_재무상태표를_끌어오지_않는다():
    """분기말 뒤로 한 분기를 열면 **아직 몰랐던** 재무상태표가 새어 든다."""
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0, ends=["2025-06-30"]))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2025-06-30")["debt"] == 1000.0
    assert evebitda.components(bs, "2025-03-31")["debt"] == 0.0   # 91일 뒤 = 미래


def test_표지_주식수는_제출일_기준이라_며칠_뒤까지_받는다():
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0, ends=["2025-04-20"]))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2025-03-31")["debt"] == 1000.0   # 20일 뒤 = 같은 보고서


def test_듀얼클래스면_가중평균_희석주식수로_물러선다():
    """실측(MSTR): Class A/B 로 나눠 올리면 시점 태그가 통째로 비어 EV 를 못 만든다."""
    f = facts()
    del f["facts"]["us-gaap"]["CommonStockSharesOutstanding"]
    f["facts"]["us-gaap"].update(dur("WeightedAverageNumberOfDilutedSharesOutstanding",
                                     1_500.0, "shares"))
    bs = evebitda.balance_sheet(f)
    assert evebitda.components(bs, "2026-06-30")["shares"] == 1_500.0
    assert evebitda.SHARE_FALLBACK_LABEL in bs["tags"]["발행주식수"]


def test_주식수가_없으면_EV_를_만들지_않는다():
    f = {"facts": {"us-gaap": dict(dur("OperatingIncomeLoss", 800.0))}}
    assert evebitda.components(evebitda.balance_sheet(f), "2026-06-30") is None


# --- 마진 --------------------------------------------------------------------
def test_마진은_중앙값이라_한_분기_이상치에_안_끌린다():
    eb = {"2025-03-31": 100.0, "2025-06-30": 100.0, "2025-09-30": 900.0}
    rev = {e: 1000.0 for e in eb}
    m, why = evebitda.margin(eb, rev)
    assert m == pytest.approx(0.10)       # 평균이면 0.367
    assert why["quarters"] == 3


def test_매출이_0이하인_분기는_버린다():
    assert evebitda.margin({"2025-03-31": 100.0}, {"2025-03-31": 0.0})[0] is None


# --- 조립 --------------------------------------------------------------------
DATES = [f"{y}-{m:02d}-15" for y in (2024, 2025, 2026) for m in range(1, 13)
         if not (y == 2026 and m > 9)]
CLOSE = [10.0] * len(DATES)


def _con():
    return {"announcements": [{"date": e[:8] + "25" if e[5:7] != "12" else
                               f"{int(e[:4]) + 1}-01-25",
                               "reported_eps": None} for e in ENDS],
            "revenue": {"0q": {"avg": 5000.0}, "+1q": {"avg": 5000.0},
                        "0y": {"avg": 20000.0}, "+1y": {"avg": 20000.0}}}


FY_ENDS = ["2024-12-31", "2025-12-31", "2026-12-31", "2027-12-31"]


def test_확정_구간과_가정_구간이_따로_나온다():
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0))
    out = evebitda.build(f, _con(), FY_ENDS, DATES, CLOSE)
    assert "error" not in out, out.get("error")
    assert out["metric"] == "ev"
    # EV = 10 × 1000주 + (1000 − 300) = 10,700 ; 향후 4분기 EBITDA = 4,000
    solid = [v for v in out["per_confirmed"] if v is not None]
    assert solid and solid[0] == pytest.approx(10700 / 4000, rel=1e-3)
    assert any(v is not None for v in out["per_estimated"])
    assert out["margin"] == pytest.approx(0.2)       # (800+200)/5000
    assert "마진" in out["estimate_note"]


def test_적자_마진이면_추정_구간을_그리지_않는다():
    """실측(MSTR): 마진 중앙값이 −3081%. 그걸 매출 컨센에 곱하면 음수를 지어낸다."""
    f = facts(a=inst("LongTermDebtNoncurrent", 1000.0))
    f["facts"]["us-gaap"].update(dur("OperatingIncomeLoss", -5000.0))
    out = evebitda.build(f, _con(), FY_ENDS, DATES, CLOSE)
    assert not any(v is not None for v in out["per_estimated"])
    assert "적자" in out["estimate_note"]


def test_EBITDA_가_짧으면_이유를_말한다():
    f = {"facts": {"us-gaap": dict(inst("CommonStockSharesOutstanding", 1000.0, "shares"))}}
    out = evebitda.build(f, _con(), FY_ENDS, DATES, CLOSE)
    assert "EBITDA" in out["error"]
