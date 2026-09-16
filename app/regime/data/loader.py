"""Assemble one aligned market snapshot (prices + exogenous series).

``load_market`` is the only function the rest of the app calls to get data, so
swapping ^IXIC for any other ticker, or adding VIX / credit spreads / Fed funds
to the exogenous list, needs no change anywhere else.

Fetched series are cached on disk under ``data/regime/`` so repeated Streamlit
reruns (and a machine that is temporarily offline) do not re-hit the provider.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import align, sources

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(os.environ.get("SUH_DH_REGIME_CACHE", ROOT / "data" / "regime"))
CACHE_TTL = float(os.environ.get("SUH_DH_REGIME_TTL", 6 * 3600))


@dataclass
class MarketData:
    """Prices on their own trading calendar plus every exogenous series aligned
    onto that same calendar."""

    ticker: str
    prices: pd.DataFrame
    exog: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.prices.index)

    @property
    def last_date(self) -> pd.Timestamp | None:
        return self.calendar.max() if len(self.prices) else None

    @property
    def empty(self) -> bool:
        return self.prices is None or self.prices.empty

    def frame(self) -> pd.DataFrame:
        """prices + exog side by side (what the feature layer consumes)."""
        return self.prices.join(self.exog, how="left")


def _cache_path(symbol: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", symbol)
    return CACHE_DIR / f"{safe}.csv"


def _read_cache(symbol: str, ttl: float) -> pd.DataFrame | None:
    p = _cache_path(symbol)
    try:
        if not p.exists() or (ttl > 0 and time.time() - p.stat().st_mtime > ttl):
            return None
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        return df if len(df) else None
    except Exception:
        return None


def _write_cache(symbol: str, df: pd.DataFrame) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(_cache_path(symbol))
    except Exception:
        pass  # 캐시는 편의 기능 — 못 써도 분석은 그대로 돌아간다.


def _stale_cache(symbol: str) -> pd.DataFrame | None:
    """TTL 을 무시한 캐시. 네트워크가 막혔을 때 마지막 보루."""
    return _read_cache(symbol, ttl=0)


def fetch_symbol(symbol: str, start: str, source: str = "yahoo",
                 use_cache: bool = True, ttl: float | None = None) -> tuple[pd.DataFrame, str]:
    ttl = CACHE_TTL if ttl is None else ttl
    if use_cache:
        cached = _read_cache(symbol, ttl)
        if cached is not None:
            return cached[cached.index >= pd.Timestamp(start)], "cache"
    df, provider = sources.fetch(symbol, start, source=source)
    if len(df):
        # 합성(데모) 시계열은 디스크에 남기지 않는다 — 나중에 진짜 데이터인 줄
        # 알고 다시 읽는 사고를 원천 차단.
        if use_cache and provider != "synthetic":
            _write_cache(symbol, df)
        return df, provider
    if use_cache:
        stale = _stale_cache(symbol)
        if stale is not None:
            return stale[stale.index >= pd.Timestamp(start)], "cache (stale)"
    return df, provider


def load_market(ticker: str = "^IXIC", years: int = 20,
                exogenous: Iterable[dict[str, Any]] = (),
                source: str = "auto", use_cache: bool = True,
                ttl: float | None = None) -> MarketData:
    """Load ``years`` of daily bars for ``ticker`` plus the exogenous series.

    Exogenous specs are ``{"key", "label", "symbol", "source", "unit"}`` dicts —
    adding VIX or a credit spread is one more dict, nothing else.

    ``source="auto"`` lets each series use its own configured provider; any
    other value (e.g. ``"synthetic"``) is forced on *every* series, so offline
    mode never mixes real prices with a synthetic macro series.
    """
    start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=int(years))).strftime("%Y-%m-%d")
    price_source = "yahoo" if source == "auto" else source
    prices, provider = fetch_symbol(ticker, start, source=price_source, use_cache=use_cache, ttl=ttl)
    meta: dict[str, Any] = {
        "ticker": ticker,
        "requested_start": start,
        "series": {
            ticker: {
                "label": ticker,
                "source": provider,
                "rows": int(len(prices)),
                "last_date": None if prices.empty else prices.index.max().date().isoformat(),
                "first_date": None if prices.empty else prices.index.min().date().isoformat(),
                "stale_days": 0,
            }
        },
    }
    if prices.empty:
        return MarketData(ticker=ticker, prices=prices, exog=pd.DataFrame(), meta=meta)

    calendar = pd.DatetimeIndex(prices.index)
    exog_cols: dict[str, pd.Series] = {}
    for spec in exogenous or ():
        key = str(spec.get("key") or spec.get("symbol"))
        symbol = str(spec.get("symbol"))
        spec_source = str(spec.get("source", "yahoo")) if source == "auto" else source
        raw, prov = fetch_symbol(symbol, start, source=spec_source, use_cache=use_cache, ttl=ttl)
        series = raw["close"] if "close" in raw.columns else pd.Series(dtype=float)
        series = _normalise_unit(series, str(spec.get("unit", "")))
        series.name = key
        aligned = align.align_series(calendar, series)
        exog_cols[key] = aligned
        meta["series"][symbol] = {
            "label": str(spec.get("label", symbol)),
            "key": key,
            "source": prov,
            "rows": int(series.dropna().shape[0]),
            "last_date": None if series.dropna().empty else series.dropna().index.max().date().isoformat(),
            "first_date": None if series.dropna().empty else series.dropna().index.min().date().isoformat(),
            "stale_days": align.stale_days(calendar, series),
            "coverage": round(float(aligned.notna().mean()), 4),
        }
    exog = pd.DataFrame(exog_cols, index=calendar) if exog_cols else pd.DataFrame(index=calendar)
    return MarketData(ticker=ticker, prices=prices, exog=exog, meta=meta)


def _normalise_unit(series: pd.Series, unit: str) -> pd.Series:
    """Yahoo 의 ^TNX 는 보통 퍼센트(4.28)로 오지만, 소스에 따라 10배(42.8) 로
    오는 경우가 있어 수준을 보고 맞춰 준다."""
    if series.empty or unit != "percent":
        return series
    med = float(series.dropna().median()) if series.notna().any() else 0.0
    if med > 20:
        return series / 10.0
    return series
