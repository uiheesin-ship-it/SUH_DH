"""Distribution-day block (기관 매도일).

A day *t* is a distribution day when all three hold, each of them a
user-tunable threshold:

    1) daily return            r_t = C_t/C_(t-1) - 1  <= -X%
    2) volume expansion        V_t >= V_(t-1) × (1 + Y%)
    3) close location value    CLV = (C_t - L_t) / (H_t - L_t) <= Z

CLV is the position of the close inside the day's range (1 = closed on the
high, 0 = on the low): a heavy down day that closes near its low is the
institutional-selling footprint the count is trying to capture. A zero-range
day is treated as neutral (0.5) rather than counted.

Two features come out of it: how many distribution days fall inside the
lookback window ending at *t*, and how long it has been since the last one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FeatureSpec


def flags(market, params) -> pd.DataFrame:
    """Per-day distribution-day diagnostics (flag + the three raw conditions)."""
    dp = params.distribution
    px = market.prices
    close = px["close"].astype(float)
    high = px["high"].astype(float)
    low = px["low"].astype(float)
    volume = px["volume"].astype(float)

    ret = (close / close.shift(1) - 1.0) * 100.0
    rng = (high - low)
    clv = ((close - low) / rng.where(rng > 0)).fillna(0.5)
    vol_ratio = volume / volume.shift(1)

    cond_ret = ret <= -float(dp.drop_pct)
    cond_vol = vol_ratio >= (1.0 + float(dp.volume_bump_pct) / 100.0)
    cond_clv = clv <= float(dp.clv_max)
    valid = ret.notna() & volume.notna() & volume.shift(1).notna() & (volume > 0)
    flag = (cond_ret & cond_vol & cond_clv & valid)

    return pd.DataFrame({
        "ret_pct": ret,
        "clv": clv,
        "vol_ratio": vol_ratio,
        "dd_flag": flag,
    }, index=px.index)


def build(market, params) -> tuple[pd.DataFrame, list[FeatureSpec], pd.DataFrame]:
    dp = params.distribution
    aux = flags(market, params)
    flag = aux["dd_flag"]
    lb = int(dp.lookback)

    count = flag.astype(float).rolling(lb, min_periods=lb).sum()

    # 마지막 분산일 이후 경과 거래일. 한 번도 없었으면(또는 아주 오래됐으면)
    # 상한값으로 눕혀서 similarity 거리에서 이상치가 되지 않게 한다.
    pos = np.arange(len(flag), dtype=float)
    last = pd.Series(np.where(flag.to_numpy(), pos, np.nan), index=flag.index).ffill()
    since = pd.Series(pos, index=flag.index) - last
    since = since.fillna(float(dp.days_since_cap)).clip(upper=float(dp.days_since_cap))
    since = since.where(count.notna())

    values = pd.DataFrame({"dd_count": count, "dd_days_since": since}, index=flag.index)
    specs = [
        FeatureSpec(key="dd_count", label=f"분산일 수 (최근 {lb}일)", group="Distribution",
                    fmt="count", default_weight=1.5,
                    description=f"r<=-{dp.drop_pct}%, V>=전일×{1 + dp.volume_bump_pct / 100:.2f}, CLV<={dp.clv_max}"),
        FeatureSpec(key="dd_days_since", label="최근 분산일 이후 경과일", group="Distribution",
                    fmt="days", default_weight=0.0,
                    description=f"상한 {dp.days_since_cap} 거래일"),
    ]
    return values, specs, aux
