"""Volatility block: realized volatility and ATR%.

Both are offered as separate features so the sidebar can weight either (or
both) — realized vol is close-to-close, ATR% also carries gap/intraday range.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FeatureSpec

TRADING_DAYS = 252


def build(market, params) -> tuple[pd.DataFrame, list[FeatureSpec], pd.DataFrame]:
    fp = params.features
    px = market.prices
    close = px["close"].astype(float)
    values: dict[str, pd.Series] = {}
    specs: list[FeatureSpec] = []

    w = int(fp.vol_window)
    logret = np.log(close / close.shift(1))
    values["vol_realized"] = (logret.rolling(w, min_periods=w).std(ddof=1)
                              * np.sqrt(TRADING_DAYS) * 100.0)
    specs.append(FeatureSpec(
        key="vol_realized", label=f"실현 변동성 {w}일 (연율)", group="Volatility",
        fmt="pct_abs", default_weight=1.0,
        description=f"std(log return, {w}d) × √252"))

    a = int(fp.atr_window)
    high, low, prev_close = px["high"].astype(float), px["low"].astype(float), close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    # Wilder smoothing (= EMA with alpha 1/n), 첫 n 개는 표본이 모자라 NaN.
    atr = tr.ewm(alpha=1.0 / a, adjust=False, min_periods=a).mean()
    values["atr_pct"] = (atr / close) * 100.0
    specs.append(FeatureSpec(
        key="atr_pct", label=f"ATR% {a}일", group="Volatility", fmt="pct_abs",
        default_weight=0.0, description="Wilder ATR / Close"))

    return pd.DataFrame(values, index=px.index), specs, pd.DataFrame(index=px.index)
