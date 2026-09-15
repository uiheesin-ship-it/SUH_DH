"""일봉 배치 수신(app.base.data.prefetch) 검증.

배치로 받으면 스캔이 빨라지지만, 종목별 경로와 **다른 데이터**를 캐시에 넣으면
스크리너가 조용히 다른 답을 낸다. 그래서 모양이 같은지, 캐시 키가 같은지,
못 받은 종목이 안전망(종목별 경로)으로 넘어가는지를 못 박아 둔다.
"""

from __future__ import annotations

import pytest

from app import cache
from app.base import data as bd


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _frame(tickers, n=5):
    """yf.download 가 돌려주는 모양(열이 MultiIndex(필드, 티커))을 흉내 낸다."""
    pd = pytest.importorskip("pandas")
    idx = pd.bdate_range("2026-01-01", periods=n)
    cols, data = [], {}
    for f, base in (("Open", 10), ("High", 11), ("Low", 9), ("Close", 10.5), ("Volume", 1000)):
        for t in tickers:
            cols.append((f, t))
            data[(f, t)] = [base + i for i in range(n)]
    return pd.DataFrame(data, index=idx, columns=pd.MultiIndex.from_tuples(cols))


def test_batch_shape_matches_the_per_ticker_contract(monkeypatch):
    """배치 결과가 fetch_bars 와 같은 키·같은 길이를 가져야 한다."""
    pytest.importorskip("pandas")
    monkeypatch.setattr(bd, "_demo", lambda: False)
    fake = _frame(["AAA", "BBB"])
    monkeypatch.setitem(__import__("sys").modules, "yfinance",
                        type("M", (), {"download": staticmethod(lambda *a, **k: fake)}))

    out = bd._batch_bars(["AAA", "BBB"], "2y")
    assert set(out) == {"AAA", "BBB"}
    for t, bars in out.items():
        assert set(bars) == {"ticker", "dates", "open", "high", "low", "close", "volume"}
        assert bars["ticker"] == t
        n = len(bars["close"])
        assert n == 5
        assert all(len(bars[k]) == n for k in ("dates", "open", "high", "low", "volume"))
        assert all(isinstance(v, int) for v in bars["volume"])
        assert all(isinstance(v, float) for v in bars["close"])
        assert bars["dates"][0] == "2026-01-01"


def test_prefetch_fills_the_same_cache_key_fetch_bars_reads(monkeypatch):
    """배치로 채운 값을 fetch_bars 가 네트워크 없이 그대로 읽어야 한다.

    이게 깨지면 배치 수신은 시간만 쓰고 스캔은 여전히 종목별로 다 받는다.
    """
    pytest.importorskip("pandas")
    monkeypatch.setattr(bd, "_demo", lambda: False)
    monkeypatch.setattr(bd, "BATCH_PAUSE", 0.0)
    fake = _frame(["AAA"])
    monkeypatch.setitem(__import__("sys").modules, "yfinance",
                        type("M", (), {"download": staticmethod(lambda *a, **k: fake)}))

    assert bd.is_cached("AAA") is False
    stat = bd.prefetch(["AAA"], pause=0.0)
    assert stat == {"requested": 1, "cached": 0, "fetched": 1, "missing": 0}
    assert bd.is_cached("AAA") is True

    def boom(*a, **k):
        raise AssertionError("배치로 채웠는데도 종목별 수신을 탔다")

    monkeypatch.setattr(bd, "_fetch_yahoo", boom)
    monkeypatch.setattr(bd, "_fetch_stooq", boom)
    assert bd.fetch_bars("AAA")["close"]


def test_prefetch_skips_already_cached(monkeypatch):
    """이미 캐시에 있는 종목은 다시 받지 않는다(두 번째 스크리너가 공짜여야 한다)."""
    pytest.importorskip("pandas")
    monkeypatch.setattr(bd, "_demo", lambda: False)
    calls = []

    def fake_batch(chunk, period):
        calls.append(list(chunk))
        return {t: {"ticker": t, "dates": ["2026-01-01"], "open": [1.0], "high": [1.0],
                    "low": [1.0], "close": [1.0], "volume": [1]} for t in chunk}

    monkeypatch.setattr(bd, "_batch_bars", fake_batch)
    bd.prefetch(["AAA", "BBB"], pause=0.0)
    bd.prefetch(["AAA", "BBB", "CCC"], pause=0.0)
    assert calls == [["AAA", "BBB"], ["CCC"]], calls


def test_unfetched_tickers_are_left_to_the_per_ticker_fallback(monkeypatch):
    """배치가 못 받은 종목은 캐시에 넣지 않아야 한다 — 안전망이 살아 있어야 한다."""
    monkeypatch.setattr(bd, "_demo", lambda: False)
    monkeypatch.setattr(bd, "_batch_bars", lambda chunk, period: {})
    stat = bd.prefetch(["AAA", "BBB"], pause=0.0, rounds=1)
    assert stat["fetched"] == 0 and stat["missing"] == 2
    assert bd.is_cached("AAA") is False, "못 받은 종목이 캐시에 들어갔다"


def test_batch_failure_never_raises(monkeypatch):
    """yfinance 가 터져도 배치 경로는 조용히 물러나야 한다(스캔이 죽으면 안 된다)."""
    monkeypatch.setattr(bd, "_demo", lambda: False)

    def boom(*a, **k):
        raise RuntimeError("rate limited")

    monkeypatch.setitem(__import__("sys").modules, "yfinance",
                        type("M", (), {"download": staticmethod(boom)}))
    assert bd._batch_bars(["AAA"], "2y") == {}


def test_courtesy_sleep_is_skipped_for_cached_tickers(monkeypatch):
    """캐시 히트면 네트워크를 안 타므로 0.2초 대기도 건너뛴다.

    안 건너뛰면 배치로 아낀 시간을 대기로 도로 까먹는다 — 8,000종목이면 27분이다.
    """
    monkeypatch.setattr(bd, "_demo", lambda: False)
    monkeypatch.setattr(bd, "_batch_bars", lambda chunk, period: {
        t: {"ticker": t, "dates": ["2026-01-01"], "open": [1.0], "high": [1.0],
            "low": [1.0], "close": [1.0], "volume": [1]} for t in chunk})
    bd.prefetch(["AAA"], pause=0.0)
    assert bd.is_cached("AAA") is True
    assert bd.is_cached("ZZZ") is False
