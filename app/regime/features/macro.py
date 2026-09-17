"""Macro block — built generically from whatever exogenous series were loaded.

Today that is the US 10Y yield. Adding VIX, a credit spread or the Fed funds
rate means one more entry in ``regime_config.yaml``: this builder then emits
level / change / percentile features for it automatically, and the sidebar
picks them up without a code change.
"""

from __future__ import annotations

import pandas as pd

from .base import FeatureSpec

DEFAULT_WEIGHTS = {"y10_chg_120d": 0.5}


def build(market, params) -> tuple[pd.DataFrame, list[FeatureSpec], pd.DataFrame]:
    idx = market.prices.index
    if market.exog is None or market.exog.empty:
        return pd.DataFrame(index=idx), [], pd.DataFrame(index=idx)

    fp = params.features
    labels = {str(s.get("key")): str(s.get("label", s.get("key"))) for s in (params.exogenous or ())}
    units = {str(s.get("key")): str(s.get("unit", "")) for s in (params.exogenous or ())}

    values: dict[str, pd.Series] = {}
    specs: list[FeatureSpec] = []
    for key in market.exog.columns:
        s = market.exog[key].astype(float)
        label = labels.get(key, key)
        is_pct = units.get(key) == "percent"

        values[f"{key}_level"] = s
        specs.append(FeatureSpec(key=f"{key}_level", label=f"{label} 수준", group="Macro",
                                 fmt="num", default_weight=0.0))

        for w in (int(x) for x in fp.yield_change_windows):
            chg = s - s.shift(w)
            # 금리는 bp(=0.01%p) 로 보는 게 직관적이라 100 배해서 저장한다.
            values[f"{key}_chg_{w}d"] = chg * 100.0 if is_pct else chg
            specs.append(FeatureSpec(
                key=f"{key}_chg_{w}d", label=f"{label} {w}일 변화",
                group="Macro", fmt="bp" if is_pct else "num",
                default_weight=DEFAULT_WEIGHTS.get(f"{key}_chg_{w}d", 0.0),
                description=f"{label}(t) - {label}(t-{w})"))

        pw = int(fp.yield_pctile_window)
        values[f"{key}_pctile"] = s.rolling(pw, min_periods=max(60, pw // 4)).rank(pct=True) * 100.0
        specs.append(FeatureSpec(key=f"{key}_pctile", label=f"{label} {pw}일 백분위",
                                 group="Macro", fmt="num", default_weight=0.0,
                                 description="최근 구간 안에서의 상대적 위치(0~100)"))

    return pd.DataFrame(values, index=idx), specs, pd.DataFrame(index=idx)
