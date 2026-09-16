"""Similarity between today's market state and every past trading day.

Method (all of it point-in-time safe):

1. **Scaling** — features live on wildly different scales (이격률 %, 분산일
   개수, bp). Each is standardised with a location/scale estimated **only from
   data up to the anchor date** (:func:`normalize_asof`). In the live app the
   anchor is the last bar, so this is simply "everything we know today"; in
   walk-forward validation the anchor is the evaluation date, so no future
   observation ever touches the scaling. Default is the robust pair
   (median, 1.4826·MAD) so one crash does not compress the whole axis.
2. **Distance** — weighted Euclidean distance in that standardised space,
   normalised by the weights so the number is comparable across different
   weight sets:  d = sqrt( Σ wᵢ (zᵢ − zᵢ*)² / Σ wᵢ ).
3. **Score** — a Gaussian kernel, ``score = 100 · exp(−d²/2)``: 100 = identical,
   ~61 at one standard-deviation-equivalent away, ~14 at two, ~1 at three.
4. **De-clustering** — consecutive days inside the same market episode are near
   duplicates. Matches are thinned so that any two are at least ``min_gap``
   trading days apart, keeping either the highest-scoring day in the episode or
   the first one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MAD_TO_SIGMA = 1.4826
# De-clustering 전에 후보를 상위 몇 개로 줄일지. episode 대표를 "가장 먼저 나온
# 날"로 고를 때, 점수가 바닥인 날이 episode 씨앗이 되는 것을 막는다.
POOL_MULTIPLIER = 10
POOL_MIN = 100


@dataclass
class ScaleInfo:
    center: pd.Series
    scale: pd.Series
    used_keys: list[str] = field(default_factory=list)
    dropped_keys: dict[str, str] = field(default_factory=dict)


def _default_valid(values: pd.DataFrame) -> pd.Series:
    """Rows with every (non-empty) feature computed. All-NaN columns — a macro
    series the provider could not deliver — are ignored rather than blanking
    out every candidate."""
    cols = [c for c in values.columns if values[c].notna().any()]
    if not cols:
        return pd.Series(False, index=values.index)
    return values[cols].notna().all(axis=1)


def normalize_asof(values: pd.DataFrame, asof, keys: list[str] | None = None,
                   mode: str = "robust", min_history: int = 250) -> tuple[pd.DataFrame, ScaleInfo]:
    """Standardise ``values`` using location/scale from rows up to ``asof`` only."""
    asof = pd.Timestamp(asof)
    keys = [k for k in (keys or list(values.columns)) if k in values.columns]
    hist = values.loc[values.index <= asof, keys]

    center, scale, dropped, used = {}, {}, {}, []
    for k in keys:
        col = hist[k].dropna()
        if len(col) < int(min_history):
            dropped[k] = f"관측치 부족 ({len(col)} < {min_history})"
            continue
        if mode == "zscore":
            c, s = float(col.mean()), float(col.std(ddof=1))
        else:
            c = float(col.median())
            s = float((col - c).abs().median()) * MAD_TO_SIGMA
            if not np.isfinite(s) or s <= 0:  # 상수에 가까운 분포면 표준편차로 대체
                s = float(col.std(ddof=1))
        if not np.isfinite(s) or s <= 0:
            dropped[k] = "분산 없음"
            continue
        center[k], scale[k] = c, s
        used.append(k)

    info = ScaleInfo(center=pd.Series(center, dtype=float),
                     scale=pd.Series(scale, dtype=float),
                     used_keys=used, dropped_keys=dropped)
    if not used:
        return pd.DataFrame(index=values.index), info
    z = (values[used] - info.center[used]) / info.scale[used]
    return z, info


def candidate_mask(index: pd.DatetimeIndex, asof, *, valid: pd.Series,
                   exclude_recent: int = 0, require_full_horizon: bool = False,
                   max_horizon: int = 0) -> pd.Series:
    """Which past days may be matched at all.

    * strictly before the anchor, and at least ``exclude_recent`` trading days
      back (오늘과 겹치는 어제·그제를 '유사한 과거'라고 부르지 않도록),
    * features fully computed,
    * optionally far enough from the end of history that the longest forward
      horizon is fully observed.
    """
    asof = pd.Timestamp(asof)
    pos = pd.Series(np.arange(len(index)), index=index)
    anchor_pos = int(pos.loc[asof])
    mask = pos <= anchor_pos - max(1, int(exclude_recent))
    mask &= valid.reindex(index).fillna(False)
    if require_full_horizon and max_horizon:
        mask &= pos <= (len(index) - 1 - int(max_horizon))
    return mask


def score_days(values: pd.DataFrame, asof, weights: dict[str, float], *,
               mode: str = "robust", min_history: int = 250,
               mask: pd.Series | None = None) -> tuple[pd.DataFrame, ScaleInfo]:
    """Distance + similarity score of every day against the anchor day."""
    asof = pd.Timestamp(asof)
    keys = [k for k, w in (weights or {}).items() if float(w) > 0 and k in values.columns]
    if not keys:
        empty = pd.DataFrame(columns=["distance", "score"], index=values.index[:0])
        return empty, ScaleInfo(pd.Series(dtype=float), pd.Series(dtype=float))

    z, info = normalize_asof(values, asof, keys, mode=mode, min_history=min_history)
    if not info.used_keys:
        return pd.DataFrame(columns=["distance", "score"], index=values.index[:0]), info

    anchor = z.loc[asof]
    bad = [k for k in info.used_keys if not np.isfinite(anchor.get(k, np.nan))]
    for k in bad:
        info.dropped_keys[k] = "기준일 값이 비어 있음"
    use = [k for k in info.used_keys if k not in bad]
    info.used_keys = use
    if not use:
        return pd.DataFrame(columns=["distance", "score"], index=values.index[:0]), info

    w = np.array([float(weights[k]) for k in use], dtype=float)
    diff = (z[use] - anchor[use]).to_numpy(dtype=float)
    ok = np.isfinite(diff).all(axis=1)
    d = np.full(len(z), np.nan)
    d[ok] = np.sqrt((diff[ok] ** 2 * w).sum(axis=1) / w.sum())

    out = pd.DataFrame({"distance": d, "score": 100.0 * np.exp(-0.5 * d ** 2)}, index=z.index)
    if mask is not None:
        out = out[mask.reindex(out.index).fillna(False)]
    return out.dropna(subset=["distance"]), info


def decluster(scored: pd.DataFrame, index: pd.DatetimeIndex, min_gap: int,
              pick: str = "best", top_n: int | None = None) -> pd.DataFrame:
    """Thin matches so no two selected days sit inside the same episode.

    ``pick="best"``  — greedy from the highest score down: the strongest day in
    an episode represents it.
    ``pick="first"`` — greedy in calendar order within a generous score pool:
    the first day of an episode represents it (신호가 처음 켜진 날 기준).
    """
    # 달력에 없는 날짜(다른 데이터셋에서 넘어온 잔여물)는 조용히 버린다 — 여기서
    # KeyError 로 죽으면 데이터 소스를 바꾼 직후 화면 전체가 멈춘다.
    scored = scored[scored.index.isin(index)]
    if scored.empty or min_gap <= 1:
        out = scored.sort_values("score", ascending=False)
        return out.head(top_n) if top_n else out

    pos_of = pd.Series(np.arange(len(index)), index=index)
    ranked = scored.sort_values("score", ascending=False)
    if pick == "first":
        pool = max(POOL_MIN, (top_n or 25) * POOL_MULTIPLIER)
        ranked = ranked.head(pool).sort_index()

    taken: list[pd.Timestamp] = []
    taken_pos: list[int] = []
    for date in ranked.index:
        p = int(pos_of.loc[date])
        if any(abs(p - q) < int(min_gap) for q in taken_pos):
            continue
        taken.append(date)
        taken_pos.append(p)
        if top_n and pick == "best" and len(taken) >= int(top_n):
            break
    out = scored.loc[taken].sort_values("score", ascending=False)
    return out.head(top_n) if top_n else out


def candidate_scores(values: pd.DataFrame, asof, weights: dict[str, float], sim_params,
                     *, valid: pd.Series | None = None, max_horizon: int = 0,
                     extra_mask: pd.Series | None = None) -> tuple[pd.DataFrame, ScaleInfo]:
    """Every *eligible* past day with its distance and score, before de-clustering.

    The audit screen needs this pool (to show a match's rank among candidates),
    and both the similarity and strict paths build on it.
    """
    index = pd.DatetimeIndex(values.index)
    if valid is None:
        valid = _default_valid(values)
    mask = candidate_mask(index, asof, valid=valid,
                          exclude_recent=sim_params.exclude_recent,
                          require_full_horizon=sim_params.require_full_horizon,
                          max_horizon=max_horizon)
    if extra_mask is not None:
        mask &= extra_mask.reindex(index).fillna(False)
    scored, info = score_days(values, asof, weights, mode=sim_params.normalization,
                              min_history=sim_params.min_history, mask=mask)
    if sim_params.max_distance is not None and not scored.empty:
        scored = scored[scored["distance"] <= float(sim_params.max_distance)]
    return scored, info


def find_similar(values: pd.DataFrame, asof, weights: dict[str, float], sim_params,
                 *, valid: pd.Series | None = None, max_horizon: int = 0) -> tuple[pd.DataFrame, ScaleInfo]:
    """candidate_scores → de-cluster → top N, in one call."""
    scored, info = candidate_scores(values, asof, weights, sim_params, valid=valid,
                                    max_horizon=max_horizon)
    matches = decluster(scored, pd.DatetimeIndex(values.index), sim_params.min_gap,
                        pick=sim_params.episode_pick, top_n=sim_params.top_n)
    return matches, info
