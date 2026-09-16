"""Momentum / position block: trailing returns and 52-week drawdown."""

from __future__ import annotations

import pandas as pd

from .base import FeatureSpec


def build(market, params) -> tuple[pd.DataFrame, list[FeatureSpec], pd.DataFrame]:
    fp = params.features
    close = market.prices["close"].astype(float)
    values: dict[str, pd.Series] = {}
    specs: list[FeatureSpec] = []

    for k in sorted(int(x) for x in fp.return_windows):
        values[f"ret_{k}"] = (close / close.shift(k) - 1.0) * 100.0
        specs.append(FeatureSpec(
            key=f"ret_{k}", label=f"{k}일 수익률", group="Momentum", fmt="pct",
            default_weight=1.0 if k == 20 else (0.5 if k == 60 else 0.0),
            description=f"Close_t / Close_(t-{k}) - 1"))

    hw = int(fp.high_window)
    # 52주 고점은 "t 까지의" 종가 최고치 — 미래 고점을 쓰지 않는다.
    rolling_high = close.rolling(hw, min_periods=hw).max()
    values["dd_52w"] = (close / rolling_high - 1.0) * 100.0
    specs.append(FeatureSpec(
        key="dd_52w", label=f"{hw}일 고점 대비 낙폭", group="Momentum", fmt="pct",
        default_weight=1.5, description="Close / rolling max(Close) - 1"))

    aux = pd.DataFrame({"rolling_high": rolling_high}, index=market.prices.index)
    return pd.DataFrame(values, index=market.prices.index), specs, aux
