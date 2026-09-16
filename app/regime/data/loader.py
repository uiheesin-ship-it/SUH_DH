"""Assemble one aligned market snapshot (prices + exogenous series).

``load_market`` is the only function the rest of the app calls to get data, so
swapping ^IXIC for any other ticker, or adding VIX / credit spreads / Fed funds
to the exogenous list, needs no change anywhere else.

Data can arrive two ways and the difference stops here: an **auto download**
(yfinance → stooq → cache), or a **manual upload** handed in through
:class:`DataOverrides`. Both end as the same ``MarketData`` — identical column
names, identical dtypes, identical calendar — so nothing downstream (features,
similarity, forward returns, audit, validation) can tell them apart. What the
snapshot *does* carry is provenance: ``meta["sources"]`` records, per stream,
whether it was downloaded, uploaded or explicitly proxied, which the UI shows
and the quality report checks.

A proxy volume (QQQ/ONEQ for an index) is never substituted automatically — it
only appears here when the caller passed it in deliberately.

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

from . import align, sources, upload

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(os.environ.get("SUH_DH_REGIME_CACHE", ROOT / "data" / "regime"))
CACHE_TTL = float(os.environ.get("SUH_DH_REGIME_TTL", 6 * 3600))


@dataclass
class DataOverrides:
    """User-supplied data that takes precedence over the auto downloader.

    ``volume_kind`` distinguishes a volume file the user uploaded ("upload")
    from a deliberately chosen proxy symbol ("proxy") — the UI must say which,
    because QQQ volume is not Nasdaq Composite volume.
    """

    prices: pd.DataFrame | None = None
    price_label: str = ""
    volume: pd.Series | None = None
    volume_label: str = ""
    volume_kind: str = "upload"                 # upload | proxy
    exog: dict[str, pd.Series] = field(default_factory=dict)
    exog_labels: dict[str, str] = field(default_factory=dict)

    def has_prices(self) -> bool:
        return self.prices is not None and not self.prices.empty

    def has_volume(self) -> bool:
        return self.volume is not None and len(self.volume) > 0


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


def _source_entry(kind: str, name: str, frame_or_series, extra: dict | None = None) -> dict:
    obj = frame_or_series
    entry = {"kind": kind, "name": name, "rows": 0, "first": None, "last": None, "usable": 0}
    if obj is None or len(obj) == 0:
        return {**entry, **(extra or {})}
    idx = pd.DatetimeIndex(obj.index)
    if isinstance(obj, pd.DataFrame):
        usable = int(obj["close"].notna().sum()) if "close" in obj.columns else int(len(obj))
    else:
        usable = int(pd.Series(obj).notna().sum())
    entry.update({"rows": int(len(obj)), "first": str(idx.min().date()),
                  "last": str(idx.max().date()), "usable": usable})
    return {**entry, **(extra or {})}


def load_market(ticker: str = "^IXIC", years: int = 20,
                exogenous: Iterable[dict[str, Any]] = (),
                source: str = "auto", use_cache: bool = True,
                ttl: float | None = None,
                overrides: "DataOverrides | None" = None) -> MarketData:
    """Load ``years`` of daily bars for ``ticker`` plus the exogenous series.

    Exogenous specs are ``{"key", "label", "symbol", "source", "unit"}`` dicts —
    adding VIX or a credit spread is one more dict, nothing else.

    ``source="auto"`` lets each series use its own configured provider; any
    other value (e.g. ``"synthetic"``) is forced on *every* series, so offline
    mode never mixes real prices with a synthetic macro series.

    ``overrides`` (manual upload) wins over the downloader for whichever stream
    it supplies, and only for those.
    """
    start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=int(years))).strftime("%Y-%m-%d")
    price_source = "yahoo" if source == "auto" else source
    if overrides is not None and overrides.has_prices():
        prices = sources.tidy_frame(overrides.prices)
        prices = prices[prices.index >= pd.Timestamp(start)] if len(prices) else prices
        provider = overrides.price_label or "manual upload"
    else:
        prices, provider = fetch_symbol(ticker, start, source=price_source,
                                        use_cache=use_cache, ttl=ttl)
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
        meta["sources"] = {"price": _source_entry("upload" if (overrides and overrides.has_prices())
                                                  else "auto", provider, prices,
                                                  {"symbol": ticker, "provider": provider})}
        return MarketData(ticker=ticker, prices=prices, exog=pd.DataFrame(), meta=meta)

    # --- volume: 업로드 파일이나 사용자가 고른 proxy 로만 대체된다(자동 대체 없음)
    sources_meta: dict[str, Any] = {
        "price": _source_entry("upload" if (overrides and overrides.has_prices()) else "auto",
                               provider if not (overrides and overrides.has_prices())
                               else (overrides.price_label or "manual upload"),
                               prices, {"symbol": ticker, "provider": provider}),
    }
    volume_entry = _source_entry("auto", f"{ticker} ({provider})", prices,
                                 {"usable": int(((prices["volume"] > 0) & prices["volume"].notna()).sum())
                                  if "volume" in prices.columns else 0})
    if overrides is not None and overrides.has_volume():
        prices, merge_stats = upload.merge_volume(prices, overrides.volume)
        volume_entry = _source_entry(overrides.volume_kind,
                                     overrides.volume_label or "manual upload", prices,
                                     {"usable": int(((prices["volume"] > 0) & prices["volume"].notna()).sum()),
                                      "merge": merge_stats})
    elif overrides is not None and overrides.has_prices():
        volume_entry["kind"] = "upload"
        volume_entry["name"] = f"{overrides.price_label or 'manual upload'} (같은 파일)"
    sources_meta["volume"] = volume_entry
    meta["sources"] = sources_meta

    calendar = pd.DatetimeIndex(prices.index)
    exog_cols: dict[str, pd.Series] = {}
    for spec in exogenous or ():
        key = str(spec.get("key") or spec.get("symbol"))
        symbol = str(spec.get("symbol"))
        if overrides is not None and key in (overrides.exog or {}):
            series = pd.Series(overrides.exog[key], dtype=float)
            prov = overrides.exog_labels.get(key, "manual upload")
            sources_meta[f"exog:{key}"] = _source_entry("upload", prov, series, {"symbol": symbol})
        else:
            spec_source = str(spec.get("source", "yahoo")) if source == "auto" else source
            raw, prov = fetch_symbol(symbol, start, source=spec_source, use_cache=use_cache, ttl=ttl)
            series = raw["close"] if "close" in raw.columns else pd.Series(dtype=float)
            series = _normalise_unit(series, str(spec.get("unit", "")))
            sources_meta[f"exog:{key}"] = _source_entry("auto", f"{symbol} ({prov})", series,
                                                        {"symbol": symbol, "provider": prov})
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
