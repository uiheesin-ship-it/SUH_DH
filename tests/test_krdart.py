"""DART 키가 잘못됐을 때 **바로, 이유를 말하며** 실패하는가.

키 문제를 보고서 조회에 맡기면 "자료 없음"(013)으로 답해서, 5년치 48번을 다
두드린 뒤 빈손으로 끝난다. 화면에는 "정기보고서를 받지 못했습니다" 라고만 떠서
키가 문제인지 종목이 문제인지 알 수가 없다.
"""

from __future__ import annotations

import pytest

from app import cache, krdart


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    cache.clear()
    monkeypatch.setattr(krdart.dartdoc, "key", lambda: "testkey123456")
    yield
    cache.clear()


def wire(monkeypatch, status, message="", boom=None):
    def api(path, **params):
        if boom:
            raise boom
        return {"status": status, "message": message, "list": []}
    monkeypatch.setattr(krdart, "_api", api)


def test_정상이면_통과한다(monkeypatch):
    wire(monkeypatch, "000")
    krdart.check_key()                      # 예외가 없으면 통과


def test_그날_공시가_없어도_키는_멀쩡한_것이다(monkeypatch):
    """013 은 '자료 없음' 이지 '키가 틀림' 이 아니다."""
    wire(monkeypatch, "013")
    krdart.check_key()


@pytest.mark.parametrize("status, 말", [
    ("010", "등록되지 않은"),
    ("011", "활성화"),
    ("020", "한도"),
    ("800", "점검"),
])
def test_상태코드를_사람_말로_바꾼다(monkeypatch, status, 말):
    wire(monkeypatch, status)
    with pytest.raises(LookupError) as e:
        krdart.check_key()
    assert 말 in str(e.value)


def test_모르는_상태코드도_숨기지_않는다(monkeypatch):
    wire(monkeypatch, "777", "뭔가 새로운 오류")
    with pytest.raises(LookupError) as e:
        krdart.check_key()
    assert "777" in str(e.value) and "뭔가 새로운 오류" in str(e.value)


def test_연결_자체가_안_되면_그렇게_말한다(monkeypatch):
    wire(monkeypatch, "000", boom=TimeoutError("no route"))
    with pytest.raises(LookupError) as e:
        krdart.check_key()
    assert "연결하지 못했습니다" in str(e.value)


def test_못_쓰는_키_판정은_기억하지_않는다(monkeypatch):
    """키를 고치자마자 다시 되어야 한다 — 실패를 캐시하면 10분을 기다린다."""
    wire(monkeypatch, "010")
    with pytest.raises(LookupError):
        krdart.check_key()
    wire(monkeypatch, "000")
    krdart.check_key()                      # 고치면 바로 통과


def test_키가_없으면_보고서를_두드리기도_전에_멈춘다(monkeypatch):
    monkeypatch.setattr(krdart.dartdoc, "key", lambda: "")
    monkeypatch.setattr(krdart, "_api",
                        lambda *a, **k: pytest.fail("키도 없이 DART 를 불렀다"))
    with pytest.raises(LookupError) as e:
        krdart.fetch("005930")
    assert ".env" in str(e.value)
