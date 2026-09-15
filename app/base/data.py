"""OHLCV loading for the base screener (adjusted daily bars, ~2 years).

Reuses the same resilient pattern as app/charts.py: yfinance first (with a short
retry to ride out cloud-IP throttling), Stooq CSV as a key-free fallback so a
scan is never blank just because Yahoo blocked this server. Benchmark/ETF series
are cached per process so we fetch SPY/QQQ/sector ETFs once per scan.

All series are returned as adjusted OHLCV (auto_adjust=True) so moving averages,
ATR and returns are split/dividend-consistent. A demo mode (SUH_DH_DEMO=1)
returns deterministic synthetic bars so the build and tests run fully offline.
"""

from __future__ import annotations

import math
import os
import time

from .. import cache

BARS_TTL = float(os.environ.get("SUH_DH_BASE_BARS_TTL", "1800"))
DEFAULT_PERIOD = os.environ.get("SUH_DH_BASE_PERIOD", "2y")

# 배치 수신 설정. yf.download 는 한 번에 여러 종목을 받아 오므로, 종목당 요청을
# 보내는 fetch_bars 보다 훨씬 빠르고 요청 수가 적어 레이트 리밋에도 안전하다
# (실측 종목당 0.081초 vs 0.350초, 요청 수 1/150). 값은 상관 수집기가 실전에서
# 검증한 것과 같게 둔다 — 400개씩 쉬지 않고 붙였다가 YFRateLimitError 로
# 수천 종목을 놓친 적이 있다.
BATCH = 150
BATCH_PAUSE = 2.0


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _empty(ticker: str) -> dict:
    return {"ticker": ticker, "dates": [], "open": [], "high": [],
            "low": [], "close": [], "volume": []}


def _fetch_yahoo(ticker: str, period: str) -> dict:
    import yfinance as yf

    hist = None
    for attempt in range(3):
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        except Exception:
            hist = None
        if hist is not None and not hist.empty:
            break
        time.sleep(0.7 * (attempt + 1))
    if hist is None or hist.empty:
        return _empty(ticker)
    hist = hist.dropna(subset=["Close"])
    return {
        "ticker": ticker,
        "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
        "open": [round(float(x), 4) for x in hist["Open"]],
        "high": [round(float(x), 4) for x in hist["High"]],
        "low": [round(float(x), 4) for x in hist["Low"]],
        "close": [round(float(x), 4) for x in hist["Close"]],
        "volume": [int(x) for x in hist["Volume"].fillna(0)],
    }


def _fetch_stooq(ticker: str, period: str) -> dict:
    import csv
    import io
    import urllib.request

    sym = ticker.lower().replace(".", "-")
    url = f"https://stooq.com/q/d/l/?s={sym}.us&i=d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        return _empty(ticker)

    dates, o, h, l, c, v = [], [], [], [], [], []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            close = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
        dates.append(row["Date"])
        o.append(round(float(row.get("Open") or close), 4))
        h.append(round(float(row.get("High") or close), 4))
        l.append(round(float(row.get("Low") or close), 4))
        c.append(round(close, 4))
        try:
            v.append(int(float(row.get("Volume") or 0)))
        except (ValueError, TypeError):
            v.append(0)
    if not c:
        return _empty(ticker)
    # ~2 years of trading days.
    keep = 520
    if len(dates) > keep:
        dates, o, h, l, c, v = (x[-keep:] for x in (dates, o, h, l, c, v))
    return {"ticker": ticker, "dates": dates, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _demo_bars(ticker: str, period: str = DEFAULT_PERIOD) -> dict:
    """Deterministic synthetic bars: prior uptrend -> a tightening VCP base.

    Purely a function of the ticker string (no RNG that would break resume), so
    the offline build/tests are reproducible.
    """
    seed = sum(ord(ch) for ch in ticker)
    n = 420
    base_price = 20 + (seed % 80)
    o, h, l, c, v = [], [], [], [], []
    price = base_price
    dates = []
    # Build a fake but chronological date axis (weekdays only-ish is not needed
    # for the math; the frontend uses /api/chart for real dates).
    for i in range(n):
        dates.append(f"D{i:04d}")
        if i < 250:                     # prior uptrend
            drift = 0.004
            wob = 0.02 * math.sin((i + seed) / 7.0)
        else:                           # tightening base
            k = (i - 250) / (n - 250)
            drift = 0.0
            wob = 0.05 * (1 - k) * math.sin((i + seed) / 5.0)
        price = max(1.0, price * (1 + drift + wob))
        hi = price * (1 + abs(wob) * 0.6 + 0.005)
        lo = price * (1 - abs(wob) * 0.6 - 0.005)
        op = (hi + lo) / 2
        vol = 2_000_000 * (1.4 - 0.6 * (i / n))     # volume fades over time
        if i > 250:
            vol *= 0.7
        o.append(round(op, 4)); h.append(round(hi, 4)); l.append(round(lo, 4))
        c.append(round(price, 4)); v.append(int(vol))
    return {"ticker": ticker, "dates": dates, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _bars_key(ticker: str, period: str) -> str:
    return f"basebars:{ticker}:{period}"


def is_cached(ticker: str, period: str = DEFAULT_PERIOD) -> bool:
    """이미 캐시에 있나 — 있으면 네트워크를 안 타므로 예의상 대기도 필요 없다."""
    return cache.peek(_bars_key((ticker or "").upper().strip(), period), BARS_TTL) is not None


def _store_bars(ticker: str, period: str, bars: dict) -> None:
    """fetch_bars 와 같은 키로 캐시에 넣는다(빈 결과는 넣지 않는다)."""
    cache.get_or_set(_bars_key(ticker, period), BARS_TTL, lambda: bars,
                     cache_when=lambda d: bool(d and d.get("close")))


def _batch_bars(chunk: list[str], period: str) -> dict[str, dict]:
    """여러 종목을 요청 한 번으로 받아 {티커: fetch_bars 와 같은 모양} 으로 편다.

    yf.download 는 종목이 여럿이면 열이 MultiIndex(필드, 티커)로 오고 하나면
    평평하게 온다. 어느 쪽이든 df["Close"] 가 티커별 표(또는 Series)를 준다.
    실패하면 빈 dict 를 돌려준다 — 부르는 쪽이 종목별 경로로 되돌아간다.
    """
    import pandas as pd
    import yfinance as yf

    try:
        df = yf.download(chunk, period=period, interval="1d", auto_adjust=True,
                         progress=False, threads=True)
    except Exception:  # noqa: BLE001
        return {}
    if df is None or df.empty:
        return {}

    cols: dict[str, object] = {}
    for f in ("Open", "High", "Low", "Close", "Volume"):
        try:
            x = df[f]
        except Exception:  # noqa: BLE001
            return {}
        cols[f] = x.to_frame(chunk[0]) if isinstance(x, pd.Series) else x

    out: dict[str, dict] = {}
    close_df = cols["Close"]
    for t in chunk:
        if t not in getattr(close_df, "columns", []):
            continue
        c = close_df[t]
        keep = c.notna()
        if not keep.any():
            continue
        idx = c.index[keep]
        cc = c[keep]

        def at(field, fill):
            frame = cols[field]
            if t not in frame.columns:
                return fill
            return frame[t].reindex(idx).fillna(fill)

        vol = at("Volume", 0)
        out[t] = {
            "ticker": t,
            "dates": [d.strftime("%Y-%m-%d") for d in idx],
            "open": [round(float(x), 4) for x in at("Open", cc)],
            "high": [round(float(x), 4) for x in at("High", cc)],
            "low": [round(float(x), 4) for x in at("Low", cc)],
            "close": [round(float(x), 4) for x in cc],
            "volume": [int(x) for x in (vol if hasattr(vol, "__iter__") else [0] * len(idx))],
        }
    return out


def prefetch(tickers, period: str = DEFAULT_PERIOD, batch: int = BATCH,
             pause: float = BATCH_PAUSE, rounds: int = 2, progress: bool = False) -> dict:
    """종목 목록의 일봉을 배치로 미리 받아 캐시에 채운다.

    fetch_bars 는 종목당 요청 1건이라 8,000종목이면 47분이 든다. 배치로 받으면
    같은 양이 11분이다. 캐시 키가 fetch_bars 와 같으므로, 스캔 전에 이걸 한 번
    돌려 두면 이후의 종목별 호출이 전부 캐시 히트가 된다 — **스크리너 코드는
    바뀌지 않는다.**

    못 받은 종목은 캐시에 넣지 않는다. 그 종목은 스캔 중에 기존 종목별 경로
    (3회 재시도 + Stooq 폴백)를 그대로 타므로 안전망이 유지된다.
    """
    if _demo():
        return {"requested": 0, "cached": 0, "fetched": 0, "missing": 0}

    seen, want = set(), []
    for t in tickers:
        t = (t or "").upper().strip()
        if not t or t in seen:
            continue
        seen.add(t)
        if not is_cached(t, period):
            want.append(t)

    got, pending = 0, want
    for rnd in range(max(1, rounds)):
        if not pending:
            break
        wait = pause * (rnd + 1)
        failed: list[str] = []
        for i in range(0, len(pending), batch):
            chunk = pending[i:i + batch]
            bars = _batch_bars(chunk, period)
            for t in chunk:
                d = bars.get(t)
                if d and d.get("close"):
                    _store_bars(t, period, d)
                    got += 1
                else:
                    failed.append(t)
            time.sleep(wait)
            if progress:
                done = min(i + batch, len(pending))
                print(f"    ... 배치 수신 {done}/{len(pending)} (누적 {got})", flush=True)
        pending = failed

    return {"requested": len(seen), "cached": len(seen) - len(want),
            "fetched": got, "missing": len(pending)}


def fetch_bars(ticker: str, period: str = DEFAULT_PERIOD, use_cache: bool = True) -> dict:
    """Adjusted daily OHLCV for one ticker (cached, with fallback source)."""
    ticker = ticker.upper().strip()

    def producer():
        if _demo():
            return _demo_bars(ticker, period)
        data = _fetch_yahoo(ticker, period)
        if data["close"]:
            return data
        return _fetch_stooq(ticker, period)

    if not use_cache:
        return producer()
    # Only cache non-empty results so a transient block is retried next time.
    return cache.get_or_set(
        _bars_key(ticker, period), BARS_TTL, producer,
        cache_when=lambda d: bool(d and d.get("close")),
    )


_bench_cache: dict[str, dict] = {}


def fetch_benchmarks(tickers: list[str], period: str = DEFAULT_PERIOD) -> dict[str, dict]:
    """Fetch a set of benchmark/ETF series once, memoized for the whole scan."""
    out: dict[str, dict] = {}
    for t in tickers:
        t = t.upper().strip()
        if not t:
            continue
        if t not in _bench_cache:
            bars = fetch_bars(t, period)
            if bars and bars.get("close"):
                _bench_cache[t] = bars
        if t in _bench_cache:
            out[t] = _bench_cache[t]
        if not _demo():
            time.sleep(0.25)   # be gentle with the source
    return out


def clear_benchmark_cache() -> None:
    _bench_cache.clear()
