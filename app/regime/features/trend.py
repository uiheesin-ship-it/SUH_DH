"""Trend block: price vs SMAs, SMA stacking, SMA slope.

All of it is a function of closes up to *t*: a rolling mean ending at *t*, a
ratio at *t*, and a slope measured backwards from *t*. Nothing peeks forward.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FeatureSpec


def build(market, params) -> tuple[pd.DataFrame, list[FeatureSpec], pd.DataFrame]:
    fp = params.features
    close = market.prices["close"].astype(float)
    values: dict[str, pd.Series] = {}
    aux: dict[str, pd.Series] = {}
    specs: list[FeatureSpec] = []

    windows = sorted(int(w) for w in fp.sma_windows)
    smas: dict[int, pd.Series] = {}
    for w in windows:
        sma = close.rolling(w, min_periods=w).mean()
        smas[w] = sma
        aux[f"sma{w}"] = sma
        # 이격률: 종가가 SMA 대비 몇 % 위/아래인가.
        values[f"px_vs_sma{w}"] = (close / sma - 1.0) * 100.0
        aux[f"above_sma{w}"] = (close > sma).where(sma.notna())
        specs.append(FeatureSpec(
            key=f"px_vs_sma{w}", label=f"Price vs SMA{w} (이격률)", group="Trend",
            fmt="pct", default_weight=1.0 if w in (50, 200) else 0.0,
            description=f"Close / SMA{w} - 1"))

    # SMA 배열: 인접한 쌍이 정배열이면 +1, 역배열이면 -1 로 점수화.
    if len(windows) >= 2:
        pairs = [(smas[a] > smas[b]).where(smas[a].notna() & smas[b].notna())
                 for a, b in zip(windows[:-1], windows[1:])]
        stack = pd.concat(pairs, axis=1).astype(float).mean(axis=1) * 2.0 - 1.0
        values["sma_stack"] = stack
        specs.append(FeatureSpec(
            key="sma_stack", label="SMA 배열 점수 (+1 정배열 / -1 역배열)",
            group="Trend", fmt="score", default_weight=1.0,
            description="인접 SMA 쌍의 정배열 비율을 [-1, +1] 로 환산"))

    n = int(fp.slope_window)
    for w in sorted(int(x) for x in fp.slope_smas):
        sma = smas.get(w)
        if sma is None:
            sma = close.rolling(w, min_periods=w).mean()
            aux[f"sma{w}"] = sma
        values[f"sma{w}_slope"] = (sma / sma.shift(n) - 1.0) * 100.0
        specs.append(FeatureSpec(
            key=f"sma{w}_slope", label=f"SMA{w} {n}일 기울기", group="Trend",
            fmt="pct", default_weight=0.5,
            description=f"SMA{w} 의 최근 {n} 거래일 변화율"))

    idx = market.prices.index
    return (pd.DataFrame(values, index=idx), specs, pd.DataFrame(aux, index=idx))
