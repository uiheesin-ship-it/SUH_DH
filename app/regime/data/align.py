"""Calendar alignment with an explicit no-look-ahead guarantee.

The price series defines the trading calendar; every other series (10Y yield
today, VIX / credit spreads / Fed funds later) is re-indexed onto it. Holes are
filled **forward only** — a forward fill copies a value from the past into the
present, which is exactly what an observer standing at date *t* would have had.
A backward fill (or an interpolation) would copy a *future* value backwards and
silently leak information into every feature built on top, so neither is used
anywhere in this package.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 시장이 열렸는데 매크로 시계열만 비어 있는 날(공휴일 차이 등)은 이어 붙이되,
# 그 이상 오래 끊긴 구간까지 옛날 값으로 채우면 사실상 없는 데이터를 있는 척
# 하게 된다 — 한 주 이상 비면 NaN 으로 남긴다.
MAX_STALE_DAYS = 5


def align_series(calendar: pd.DatetimeIndex, series: pd.Series,
                 max_stale_days: int = MAX_STALE_DAYS) -> pd.Series:
    """Re-index ``series`` onto ``calendar``, forward-filling short gaps only."""
    if series is None or len(series) == 0:
        return pd.Series(np.nan, index=calendar, dtype=float)
    s = series.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    union = s.index.union(calendar)
    filled = s.reindex(union).ffill(limit=None)
    # 마지막 실제 관측일로부터 며칠이 지났는지 계산해, 오래된 값은 버린다.
    last_obs = pd.Series(s.index, index=s.index).reindex(union).ffill()
    stale = (pd.Series(union, index=union) - last_obs).dt.days
    filled = filled.where(stale <= max_stale_days)
    out = filled.reindex(calendar)
    out.name = series.name
    return out.astype(float)


def align_frame(calendar: pd.DatetimeIndex, frame: pd.DataFrame,
                max_stale_days: int = MAX_STALE_DAYS) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(index=calendar)
    return pd.DataFrame(
        {c: align_series(calendar, frame[c], max_stale_days) for c in frame.columns},
        index=calendar,
    )


def stale_days(calendar: pd.DatetimeIndex, series: pd.Series) -> int | None:
    """Calendar days between the last real observation and the last trading day —
    what the UI shows as "이 시계열은 며칠 늦었다"."""
    if series is None or series.dropna().empty or len(calendar) == 0:
        return None
    return int((calendar.max() - series.dropna().index.max()).days)
