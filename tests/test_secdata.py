"""EDGAR 접근 계층 — 티커를 **올바른 회사**로 연결하는지 검증.

여기서 틀리면 남의 재무제표를 보여 주게 된다. 그보다 나쁜 실패는 없다.

전체 목록(www.sec.gov/files/company_tickers.json)이 403 이라 쓸 수 없어서
커밋된 씨앗 목록 + 전문검색 두 갈래로 찾는다. 씨앗은 공개 미러에서 받아 온
것이라 **힌트일 뿐**이고, 반드시 submissions 응답으로 확인한다.
"""

from __future__ import annotations

import json

import pytest

from app import secdata as S


# ------------------------------------------------- 티커 → CIK 해석(전문검색)
def test_cik_resolution_needs_an_exact_ticker_match(monkeypatch):
    """본문에 그 글자가 우연히 있는 문서를 잡으면 안 된다."""
    hits = {"hits": {"hits": [
        {"_source": {"display_names": ["Mulesoft Holdings (MULE) (CIK 0001725283)"]}},
        {"_source": {"display_names": ["Micron Technology Inc (MU) (CIK 0000723125)"]}},
    ]}}
    monkeypatch.setattr(S, "_get", lambda *a, **k: json.dumps(hits).encode())
    assert S.resolve_cik("MU") == "0000723125"


def test_cik_resolution_returns_none_when_nothing_matches(monkeypatch):
    hits = {"hits": {"hits": [
        {"_source": {"display_names": ["Some Other Corp (XYZ) (CIK 0000000001)"]}}]}}
    monkeypatch.setattr(S, "_get", lambda *a, **k: json.dumps(hits).encode())
    assert S.resolve_cik("MU") is None


def test_cik_resolution_survives_a_network_failure(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("efts down")

    monkeypatch.setattr(S, "_get", boom)
    assert S.resolve_cik("MU") is None          # 예외가 새면 조회 전체가 죽는다


# ------------------------------------------- 씨앗 CIK 목록은 힌트일 뿐이다
def _wire(monkeypatch, *, seed, meta_tickers, resolved=None):
    calls = {"search": 0}
    monkeypatch.setattr(S.time, "sleep", lambda *_: None)
    monkeypatch.setattr(S, "cik_map", lambda: seed)
    monkeypatch.setattr(S, "submissions", lambda cik: {
        "name": "X", "tickers": meta_tickers, "sic": "s", "fiscal_year_end": "1231"})

    def search(t):
        calls["search"] += 1
        return resolved

    monkeypatch.setattr(S, "resolve_cik", search)
    return calls


def test_a_wrong_seed_cik_is_caught_by_the_sec_response(monkeypatch):
    """submissions 가 돌려준 tickers 와 안 맞으면 그 CIK 를 쓰지 않는다."""
    calls = _wire(monkeypatch, seed={"MU": "0000000999"}, meta_tickers=["ZZZZ"])
    with pytest.raises(LookupError):
        S.lookup("MU")
    assert calls["search"] == 1, "전문검색으로 다시 찾지 않았다"


def test_a_correct_seed_cik_costs_no_extra_request(monkeypatch):
    """맞으면 전문검색을 부르지 않는다 — 확인은 어차피 부르는 호출로 끝난다."""
    calls = _wire(monkeypatch, seed={"MU": "0000723125"}, meta_tickers=["MU"])
    cik, meta = S.lookup("MU")
    assert cik == "0000723125" and calls["search"] == 0


def test_ticker_missing_from_the_seed_falls_back_to_search(monkeypatch):
    """씨앗에 없는 신규 상장은 전문검색으로 찾는다."""
    calls = _wire(monkeypatch, seed={}, meta_tickers=["NEW"], resolved="0000001234")
    cik, _ = S.lookup("NEW")
    assert cik == "0000001234" and calls["search"] == 1


def test_the_committed_seed_map_looks_sane():
    """커밋된 씨앗이 실제로 쓸 만한지 — EDGAR 가 서빙한 값과 대조한다."""
    m = S.cik_map()
    assert len(m) > 5000, f"씨앗이 너무 작다: {len(m)}"
    for t, cik in [("AAPL", "0000320193"), ("MU", "0000723125"),
                   ("JPM", "0000019617"), ("APPS", "0000317788")]:
        assert m.get(t) == cik, f"{t} 씨앗이 {m.get(t)} 로 틀렸다"
    assert all(len(v) == 10 and v.isdigit() for v in list(m.values())[:500])
