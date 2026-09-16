"""Strict (rule-based) matching: "조건을 모두 만족한 과거 날짜를 찾아라".

The similarity engine ranks every day by distance; strict mode instead keeps
only the days that satisfy an explicit AND of user conditions. Both modes come
out of here with the same shape (a frame indexed by date with ``distance`` and
``score`` columns, de-clustered), so the forward-return, table and chart layers
do not care which one produced the matches.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import similarity

OPS = {
    "<=": lambda s, v: s <= v,
    "<": lambda s, v: s < v,
    ">=": lambda s, v: s >= v,
    ">": lambda s, v: s > v,
    "==": lambda s, v: s == v,
}


@dataclass(frozen=True)
class Condition:
    """One AND-ed condition on a feature column, e.g. ``dd_52w <= -10``."""

    key: str
    op: str
    value: float
    value2: float | None = None   # "between" 의 상한

    def label(self, specs: dict | None = None) -> str:
        name = (specs or {}).get(self.key).label if (specs or {}).get(self.key) else self.key
        if self.op == "between":
            return f"{self.value:g} ≤ {name} ≤ {self.value2:g}"
        return f"{name} {self.op} {self.value:g}"

    def mask(self, values: pd.DataFrame) -> pd.Series:
        if self.key not in values.columns:
            return pd.Series(False, index=values.index)
        s = values[self.key]
        if self.op == "between":
            hi = self.value if self.value2 is None else self.value2
            lo, hi = (self.value, hi) if self.value <= hi else (hi, self.value)
            m = (s >= lo) & (s <= hi)
        else:
            fn = OPS.get(self.op)
            m = fn(s, self.value) if fn else pd.Series(False, index=values.index)
        return m.fillna(False)


def apply_conditions(values: pd.DataFrame, conditions) -> pd.Series:
    """AND of every condition; a day with a missing feature never matches."""
    mask = pd.Series(True, index=values.index)
    for cond in conditions or ():
        mask &= cond.mask(values)
    return mask


def strict_match(values: pd.DataFrame, conditions, asof, sim_params,
                 weights: dict[str, float] | None = None, max_horizon: int = 0,
                 valid: pd.Series | None = None) -> tuple[pd.DataFrame, similarity.ScaleInfo]:
    """Days satisfying every condition, de-clustered like the similarity path.

    Scores are still computed when weights are supplied — a strict match is
    ranked by how close it also is to today, which is what the table sorts on.
    """
    index = pd.DatetimeIndex(values.index)
    if valid is None:
        valid = similarity._default_valid(values)
    mask = similarity.candidate_mask(index, asof, valid=valid,
                                     exclude_recent=sim_params.exclude_recent,
                                     require_full_horizon=sim_params.require_full_horizon,
                                     max_horizon=max_horizon)
    mask &= apply_conditions(values, conditions)

    info = similarity.ScaleInfo(pd.Series(dtype=float), pd.Series(dtype=float))
    if weights:
        scored, info = similarity.score_days(values, asof, weights,
                                             mode=sim_params.normalization,
                                             min_history=sim_params.min_history, mask=mask)
    else:
        hits = index[mask.reindex(index).fillna(False)]
        scored = pd.DataFrame({"distance": np.nan, "score": np.nan}, index=hits)

    pick = sim_params.episode_pick if weights else "first"
    matches = similarity.decluster(scored.fillna({"score": 0.0}), index, sim_params.min_gap,
                                   pick=pick, top_n=None)
    if weights:
        matches = matches.sort_values("score", ascending=False)
    else:
        matches = matches.sort_index()
    return matches, info
