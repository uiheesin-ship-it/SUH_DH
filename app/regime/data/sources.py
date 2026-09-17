"""Raw daily series providers for the Market Regime Lab.

Three interchangeable sources behind one function signature so the rest of the
package never knows where the bars came from:

* ``yahoo``     — yfinance daily OHLCV (기본). Indices (^IXIC, ^TNX) and any
                  ordinary ticker work the same way.
* ``stooq``     — key-free CSV fallback, used when Yahoo blocks the host
                  (same resilience pattern as app/base/data.py).
* ``synthetic`` — deterministic offline bars so the app, the tests and a
                  network-less machine all still work (SUH_DH_DEMO=1).

Every provider returns a DataFrame indexed by tz-naive, normalised dates with
the columns ``open/high/low/close/volume`` (a yield series only fills
``close``). Nothing here knows about features — that separation is what lets a
new source (VIX, credit spreads, Fed funds) be added with one function.
"""

from __future__ import annotations

import io
import os
import zlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]

# Stooq symbol mapping for the handful of indices we care about; anything else
# is assumed to be a US equity ticker (stooq spells those "aapl.us").
STOOQ_SYMBOLS = {
    "^IXIC": "^ndq",
    "^GSPC": "^spx",
    "^DJI": "^dji",
    "^RUT": "^rut",
    "^VIX": "^vix",
    "^TNX": "10usy.b",
    "^FVX": "5usy.b",
    "^TYX": "30usy.b",
}


def demo_mode() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], name="date"))


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise any provider frame: lower-case columns, tz-naive dates, sorted,
    de-duplicated, numeric, and with all-NaN close rows dropped."""
    if df is None or len(df) == 0:
        return _empty()
    out = df.copy()
    out.columns = [str(c).split(" ")[0].lower() for c in out.columns]
    for col in COLUMNS:
        if col not in out.columns:
            out[col] = np.nan
    out = out[COLUMNS].apply(pd.to_numeric, errors="coerce")
    idx = pd.to_datetime(out.index, errors="coerce")
    try:
        idx = idx.tz_localize(None)
    except (TypeError, AttributeError):
        idx = pd.DatetimeIndex(idx).tz_localize(None) if getattr(idx, "tz", None) else pd.DatetimeIndex(idx)
    out.index = pd.DatetimeIndex(idx).normalize()
    out.index.name = "date"
    out = out[~out.index.isna()]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["close"])


def tidy_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Public alias of the provider normaliser — manual uploads go through the
    exact same shaping as a download, so the two are indistinguishable later."""
    return _tidy(df)


def fetch_yahoo(symbol: str, start: str | datetime) -> pd.DataFrame:
    """Daily bars from Yahoo. ``auto_adjust=True`` so moving averages and
    returns are split/dividend-consistent for ordinary tickers (indices are
    unaffected). Volume comes back unadjusted, which only matters for the
    day-over-day volume ratio on a split date."""
    import yfinance as yf

    raw = yf.download(symbol, start=pd.Timestamp(start).strftime("%Y-%m-%d"),
                      interval="1d", auto_adjust=True, progress=False,
                      threads=False, group_by="column")
    if raw is None or len(raw) == 0:
        return _empty()
    if isinstance(raw.columns, pd.MultiIndex):
        # yf.download nests (field, ticker) even for a single symbol.
        lvl = 0 if "Close" in set(raw.columns.get_level_values(0)) else 1
        raw.columns = raw.columns.get_level_values(lvl)
    return _tidy(raw)


def fetch_stooq(symbol: str, start: str | datetime) -> pd.DataFrame:
    """Key-free CSV fallback. Only used when Yahoo comes back empty."""
    import urllib.request

    sym = STOOQ_SYMBOLS.get(symbol.upper())
    if sym is None:
        sym = symbol.lower() if symbol.lower().endswith(".us") else f"{symbol.lower()}.us"
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed host
        body = resp.read().decode("utf-8", "replace")
    if "Date" not in body[:64]:
        return _empty()
    df = pd.read_csv(io.StringIO(body))
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "date" not in df.columns:
        return _empty()
    df = df.set_index("date")
    out = _tidy(df)
    return out[out.index >= pd.Timestamp(start)]


def synthetic_prices(symbol: str, start: str | datetime, end: str | datetime | None = None) -> pd.DataFrame:
    """Deterministic offline bars: a drifting index with volatility clustering,
    a couple of crash/recovery episodes and volume that spikes on down days.

    Not a forecast of anything — it exists so the UI, the unit tests and a
    machine without market-data access all behave exactly like the live path.
    """
    end_ts = pd.Timestamp(end or pd.Timestamp.today().normalize())
    idx = pd.bdate_range(pd.Timestamp(start), end_ts)
    # 미국 공휴일 근사: 연중 임의의 9일을 빼서 거래일 수(연 ~252일)를 맞춘다.
    # 파이썬 hash() 는 프로세스마다 달라지므로(PYTHONHASHSEED) 안정적인 crc32 로
    # 시드를 만든다 — 같은 티커는 어디서 돌려도 같은 데모 시계열이 나온다.
    rng = np.random.default_rng(zlib.crc32(symbol.upper().encode()) % (2**32))
    n = len(idx)
    if n == 0:
        return _empty()
    drop = rng.choice(n, size=max(0, int(n * 9 / 252)), replace=False)
    idx = idx.delete(np.sort(drop))
    n = len(idx)

    is_yield = symbol.upper() in {"^TNX", "^FVX", "^TYX"}
    if is_yield:
        # Ornstein-Uhlenbeck around 3.2% — 수준/변화율만 쓰므로 OHLC 는 동일.
        y = np.empty(n)
        y[0] = 4.3
        for i in range(1, n):
            y[i] = y[i - 1] + 0.004 * (3.2 - y[i - 1]) + rng.normal(0, 0.045)
        y = np.clip(y, 0.35, 9.0)
        return _tidy(pd.DataFrame({"open": y, "high": y, "low": y, "close": y,
                                   "volume": np.nan}, index=idx))

    vol = np.empty(n)
    ret = np.empty(n)
    vol[0] = 0.010
    for i in range(1, n):
        # GARCH(1,1)-ish: 변동성이 뭉치도록(군집성) 만들어 realized vol feature 가
        # 실제 데이터처럼 레짐을 갖게 한다.
        shock = ret[i - 1] if i > 1 else 0.0
        vol[i] = np.sqrt(max(1e-8, 0.000002 + 0.09 * shock**2 + 0.89 * vol[i - 1] ** 2))
        ret[i] = rng.normal(0.00035, vol[i])
    ret[0] = 0.0
    # 두 번의 큰 하락 국면(글로벌 금융위기 / 팬데믹 느낌)을 심어 둔다.
    for frac, length, depth in ((0.18, 260, -0.55), (0.72, 30, -0.33)):
        s = int(n * frac)
        e = min(n, s + length)
        ret[s:e] += depth / max(1, e - s)
    close = 2000.0 * np.exp(np.cumsum(ret))
    intraday = np.abs(rng.normal(0, 0.006, n)) + 0.002
    high = close * (1 + intraday * rng.uniform(0.3, 1.0, n))
    low = close * (1 - intraday * rng.uniform(0.3, 1.0, n))
    open_ = np.clip(close * (1 + rng.normal(0, 0.004, n)), low, high)
    volume = 2.0e9 * np.exp(rng.normal(0, 0.18, n) + 6.0 * np.abs(ret) - 3.0 * ret)
    return _tidy(pd.DataFrame({"open": open_, "high": high, "low": low,
                               "close": close, "volume": volume}, index=idx))


def fetch(symbol: str, start: str | datetime, source: str = "yahoo") -> tuple[pd.DataFrame, str]:
    """Fetch ``symbol`` and report which provider actually served it.

    Order: demo short-circuit → requested source → stooq → synthetic. The app
    surfaces the returned provider name so a fallback is never silent.
    """
    if demo_mode() or source == "synthetic":
        return synthetic_prices(symbol, start), "synthetic"
    attempts = ["yahoo", "stooq"] if source == "yahoo" else [source, "yahoo", "stooq"]
    errors: list[str] = []
    for name in dict.fromkeys(attempts):
        fn = {"yahoo": fetch_yahoo, "stooq": fetch_stooq}.get(name)
        if fn is None:
            continue
        try:
            df = fn(symbol, start)
        except Exception as exc:  # noqa: BLE001 - any provider hiccup falls through
            errors.append(f"{name}: {type(exc).__name__}")
            continue
        if len(df) > 0:
            return df, name
        errors.append(f"{name}: empty")
    return _empty(), "unavailable (" + ", ".join(errors) + ")"
