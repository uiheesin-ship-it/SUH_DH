"""국장 조립 검증 — 컨센 지평이 좁을 때 무엇으로 채우나.

네이버는 앞으로 **분기 하나 + 연간 하나**만 준다(실측 2026-09-19). 12개월이면
네 분기가 필요하니 세 단계로 채운다. 그 세 단계가 순서대로 맞는지 본다.
"""

from __future__ import annotations

import pytest

from app import krquarterly as kq

FY_ENDS = ["2023-12-31", "2024-12-31", "2025-12-31", "2026-12-31", "2027-12-31"]


def known(**kw):
    """분기별 확정 EPS. 2024·2025 는 네 분기가 다 있어야 계절성이 잡힌다."""
    out = {}
    for y in (2024, 2025):
        for i, (m, d) in enumerate([("03", "31"), ("06", "30"),
                                    ("09", "30"), ("12", "31")]):
            out[f"{y}-{m}-{d}"] = 100.0 * (i + 1)      # 계절성: 1:2:3:4
    out.update(kw)
    out["2026-03-31"] = 110.0
    out["2026-06-30"] = 220.0
    return out


def con(q=None, y=None):
    return {"quarters": {k: {"consensus": True, "희석EPS": v}
                         for k, v in (q or {}).items()},
            "years": {k: {"consensus": True, "희석EPS": v}
                      for k, v in (y or {}).items()}}


FUTURE = ["2026-09-30", "2026-12-31", "2027-03-31", "2027-06-30"]


def test_분기_컨센이_있으면_그대로_쓴다():
    est, why = kq.estimates(FUTURE, con(q={"202609": 333.0}), FY_ENDS, known())
    assert est["2026-09-30"]["val"] == 333.0
    assert est["2026-09-30"]["source"] == "네이버 분기 컨센"
    assert why["counts"]["분기 컨센"] == 1


def test_올해_잔여는_연간_컨센을_계절성으로_나눈다():
    est, why = kq.estimates(FUTURE, con(q={"202609": 330.0}, y={"202612": 1100.0}),
                            FY_ENDS, known())
    # 확정 110+220 + 분기컨센 330 = 660 → 잔여 440 이 4분기 하나에 전부
    assert est["2026-12-31"]["val"] == pytest.approx(440.0)
    assert "계절성" in est["2026-12-31"]["source"] or "균등" in est["2026-12-31"]["source"]


def test_다음_회계연도는_직전_해_같은_분기에_성장률을_곱한다():
    """네이버에는 내년 컨센이 없다. 안 만들면 가장 최근 1년이 통째로 빈다."""
    est, why = kq.estimates(FUTURE, con(q={"202609": 330.0}, y={"202612": 1100.0}),
                            FY_ENDS, known())
    g = 1100.0 / 1000.0                     # 2025 실적 합 = 100+200+300+400
    assert why["growth"] == pytest.approx(g)
    assert est["2027-03-31"]["val"] == pytest.approx(110.0 * g)
    assert est["2027-06-30"]["val"] == pytest.approx(220.0 * g)
    assert est["2027-03-31"]["assumed"] is True
    assert why["counts"]["직전 해 × 성장률"] == 2


def test_성장률이_지나치면_성장_없음으로_물러선다():
    """실측(삼성전자): 올해 성장률 7.25배. 내년까지 그대로 곱하면 EPS 56만 원이다.

    컨센이 한 번도 말한 적 없는 숫자가 된다. 사이클 정점을 영구 성장률로 바꿔
    쓰는 셈이라, 그럴 땐 성장 없음(1.0)으로 두고 그렇게 적는다.
    """
    est, why = kq.estimates(FUTURE, con(y={"202612": 7000.0}), FY_ENDS, known())
    assert why["raw_growth"] == pytest.approx(7.0)
    assert why["growth"] == 1.0
    assert why["growth_capped"] is True
    assert est["2027-03-31"]["val"] == pytest.approx(110.0)      # 1년 전 그대로
    assert est["2027-03-31"]["source"] == "직전 해 같은 분기 × 성장 없음(가정)"


def test_성장률이_범위_안이면_그대로_쓴다():
    est, why = kq.estimates(FUTURE, con(y={"202612": 1100.0}), FY_ENDS, known())
    assert why["growth_capped"] is False
    assert est["2027-03-31"]["val"] == pytest.approx(110.0 * 1.1)


def test_연간_컨센이_없으면_지어내지_않는다():
    est, _ = kq.estimates(FUTURE, con(q={"202609": 330.0}), FY_ENDS, known())
    assert "2026-12-31" not in est          # 채울 근거가 없다
    assert "2027-03-31" not in est


def test_확정_합이_연간_컨센을_넘으면_비운다():
    est, _ = kq.estimates(FUTURE, con(y={"202612": 100.0}), FY_ENDS, known())
    assert est["2026-09-30"]["val"] is None
    assert "넘었습니다" in est["2026-09-30"]["note"]


def test_기간_키는_네이버_모양으로_맞춘다():
    assert kq._ym("2026-06-30") == "202606"


# ── 손으로 고치는 칸: 국장은 당기순이익으로 고친다 ─────────────────────────────

def net(**kw):
    """분기별 확정 당기순이익. 주식수 1,000주를 가정하면 EPS 와 맞는다."""
    out = {e: {"val": v * 1000.0} for e, v in known().items()}
    out.update({e: {"val": v} for e, v in kw.items()})
    return out


def eps_rows(**kw):
    return [{"end": e, "val": v} for e, v in sorted(known().items())]


def test_환산계수는_EPS를_당기순이익으로_나눈_중앙값이다():
    k, why = kq.eps_per_won(eps_rows(), net())
    assert k == pytest.approx(1 / 1000.0)
    assert why["implied_shares"] == 1000
    assert why["quarters"] == kq.FACTOR_QUARTERS


def test_순이익이_0이거나_부호가_어긋난_분기는_계수에서_뺀다():
    """적자 분기 하나가 비율을 날린다. 중앙값이어도 아예 빼고, 더 뒤까지 본다."""
    n = net(**{"2025-12-31": 0.0, "2025-09-30": -300_000.0})
    k, why = kq.eps_per_won(eps_rows(), n)
    assert k == pytest.approx(1 / 1000.0)
    assert why["quarters"] == kq.FACTOR_QUARTERS          # 빈 자리를 더 과거로 메운다
    # 뒤에 메울 분기가 없으면 그만큼 적은 분기로 잰다 — 지어내지 않는다.
    few = {e: v for e, v in n.items() if e < "2026"}
    k2, why2 = kq.eps_per_won(eps_rows(), few)
    assert why2["quarters"] == 6
    assert k2 == pytest.approx(1 / 1000.0)


def test_잴_분기가_없으면_계수를_지어내지_않는다():
    k, why = kq.eps_per_won(eps_rows(), {})
    assert k is None
    assert why["quarters"] == 0


def test_고치는_칸은_당기순이익_단위로_나온다():
    est, _ = kq.estimates(FUTURE, con(q={"202609": 330.0}, y={"202612": 1100.0}),
                          FY_ENDS, known())
    ed = kq._editable(est, con(q={"202609": 330.0}, y={"202612": 1100.0}),
                      FY_ENDS, {e: r["val"] for e, r in net().items()},
                      1 / 1000.0, {"quarters": 8, "implied_shares": 1000})
    assert ed["unit"] == "당기순이익"
    assert ed["to_eps"] == pytest.approx(1 / 1000.0)
    assert ed["digits"] == 0
    # 차트가 쓰는 EPS 330 을 계수로 되돌린 값 — 따로 추정하지 않는다.
    assert ed["values"]["2026-09-30"] == pytest.approx(330.0 * 1000.0)
    assert "1,000주" in ed["factor_note"]


def test_고치는_칸의_연간_한도도_당기순이익_컨센이다():
    c = con(q={"202609": 330.0}, y={"202612": 1100.0})
    c["years"]["202612"]["당기순이익"] = 1_100_000.0
    est, _ = kq.estimates(FUTURE, c, FY_ENDS, known())
    ed = kq._editable(est, c, FY_ENDS,
                      {e: r["val"] for e, r in net().items()},
                      1 / 1000.0, {"quarters": 8})
    y = ed["years"]["2026-12-31"]
    assert y["total"] == pytest.approx(1_100_000.0)       # 원 단위, EPS 아님
    assert y["booked"] == pytest.approx(330_000.0)        # 110+220 → 원
    assert y["quarters"] == ["2026-09-30", "2026-12-31"]


def test_계수를_못_재면_고치는_칸을_끄고_이유를_말한다():
    est, _ = kq.estimates(FUTURE, con(q={"202609": 330.0}), FY_ENDS, known())
    ed = kq._editable(est, con(), FY_ENDS, {}, None, {"quarters": 0})
    assert ed["disabled"] is True
    assert "당기순이익" in ed["why"]
    assert "values" not in ed
