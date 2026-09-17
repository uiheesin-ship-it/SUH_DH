"""Forward-return analysis: what happened *after* the matched days.

This is the only module that deliberately looks into the future — it is the
evaluation step, never an input to a feature. For a match at date *t*:

    fwd_h  = Close_(t+h) / Close_t − 1                    (h ∈ 5/20/60/120 거래일)
    mdd_h  = min over j ≤ h of  Close_(t+j) / max(Close_t..Close_(t+j)) − 1

Each horizon is summarised (n, mean, median, win rate, p25/p75, min/max, std,
forward max drawdown) for the matched sample and for the *unconditional*
baseline — every day in the same 20-year window — so the interesting number is
always the difference between the two, not the level.

Uncertainty is reported with a percentile bootstrap (95% by default) around the
mean and the median. Overlapping windows are the whole problem here, so three
things guard against a falsely narrow interval:

* the **baseline** uses a moving-block bootstrap with block length = horizon;
* the **matched** sample uses a **cluster bootstrap** by default — matches whose
  forward windows overlap (positions closer than the horizon) form one episode,
  and whole episodes are resampled, so the dependency survives resampling
  instead of being averaged away. An i.i.d. bootstrap is computed alongside it
  so the narrowing it would have produced is visible, not hidden;
* an **effective sample size** is reported,
  ``n_eff = n² / Σᵢⱼ max(0, 1 − |tᵢ−tⱼ|/h)``, i.e. n discounted by how much the
  forward windows overlap. n_eff ≈ n means genuinely independent episodes;
  n_eff ≪ n means the headline n is inflated.

Optionally (``independence="horizon"``) the matched set is re-de-clustered per
horizon with a minimum gap of h trading days, which makes the sample strictly
non-overlapping at the cost of dropping matches. Both views are available
because the strict one can shrink a 25-match sample to 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def forward_returns(close: pd.Series, horizons: Iterable[int]) -> pd.DataFrame:
    close = close.astype(float)
    return pd.DataFrame({f"fwd_{int(h)}": (close.shift(-int(h)) / close - 1.0) * 100.0
                         for h in horizons}, index=close.index)


def forward_max_drawdown(close: pd.Series, horizons: Iterable[int]) -> pd.DataFrame:
    """Worst peak-to-trough move inside each forward window (%, negative)."""
    arr = close.astype(float).to_numpy()
    n = len(arr)
    out: dict[str, np.ndarray] = {}
    for h in (int(x) for x in horizons):
        col = np.full(n, np.nan)
        if 0 < h < n:
            win = np.lib.stride_tricks.sliding_window_view(arr, h + 1)  # (n-h, h+1)
            peak = np.maximum.accumulate(win, axis=1)
            col[: n - h] = (win / peak - 1.0).min(axis=1) * 100.0
        out[f"mdd_{h}"] = col
    return pd.DataFrame(out, index=close.index)


def episode_clusters(positions: Sequence[int], horizon: int) -> np.ndarray:
    """Group matches whose forward windows overlap into one episode.

    Single-linkage on the trading-day axis: two matches less than ``horizon``
    days apart share an episode, and the relation chains (0, 15, 30 with h=20 is
    one episode, not two). Conservative on purpose — the point is to avoid
    counting one market episode as several independent observations.
    """
    pos = np.asarray(list(positions), dtype=float)
    if pos.size == 0:
        return np.empty(0, dtype=int)
    order = np.argsort(pos)
    ids = np.empty(pos.size, dtype=int)
    cur, prev = 0, None
    for i in order:
        if prev is not None and (pos[i] - prev) >= int(horizon):
            cur += 1
        ids[i] = cur
        prev = pos[i]
    return ids


def effective_sample_size(positions: Sequence[int], horizon: int) -> float:
    """n discounted by forward-window overlap.

    Two matches h/2 days apart share half of their forward window, so they carry
    about 1.5 observations' worth of information, not 2. Summing that pairwise
    overlap gives ``n_eff = n² / Σᵢⱼ oᵢⱼ`` with ``oᵢⱼ = max(0, 1 − |Δt|/h)``.
    """
    pos = np.asarray(list(positions), dtype=float)
    n = pos.size
    if n == 0:
        return 0.0
    if horizon <= 0:
        return float(n)
    d = np.abs(pos[:, None] - pos[None, :])
    o = np.clip(1.0 - d / float(horizon), 0.0, 1.0)
    total = float(o.sum())
    return float(n * n / total) if total > 0 else float(n)


def _percentile_ci(draws: np.ndarray, ci_level: float) -> tuple[float, float]:
    alpha = (1.0 - float(ci_level)) / 2.0
    return (float(np.nanpercentile(draws, alpha * 100)),
            float(np.nanpercentile(draws, (1 - alpha) * 100)))


def bootstrap_ci(sample: Sequence[float], *, n_boot: int = 2000, ci_level: float = 0.95,
                 seed: int = 20240101, block: int = 1,
                 clusters: Sequence[int] | None = None) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap CI for the mean and the median.

    * ``clusters`` — resample whole episodes with replacement (cluster
      bootstrap). Use it whenever the observations inside an episode are not
      independent of each other, which is exactly the overlapping-window case.
    * ``block > 1`` — moving-block bootstrap for a *time series* sample (the
      unconditional baseline), keeping local autocorrelation inside each block.
    * neither — plain i.i.d. bootstrap.
    """
    values = np.asarray(list(sample), dtype=float)
    finite = np.isfinite(values)
    if clusters is not None:
        cl = np.asarray(list(clusters), dtype=int)[finite]
    x = values[finite]
    n = x.size
    if n < 3:
        return {"mean": (np.nan, np.nan), "median": (np.nan, np.nan)}
    rng = np.random.default_rng(seed)
    if clusters is not None:
        groups = [x[cl == c] for c in np.unique(cl)]
        k = len(groups)
        if k < 2:   # 에피소드가 하나뿐이면 재표본할 축이 없다
            return {"mean": (np.nan, np.nan), "median": (np.nan, np.nan)}
        means = np.empty(int(n_boot))
        medians = np.empty(int(n_boot))
        picks = rng.integers(0, k, size=(int(n_boot), k))
        for b in range(int(n_boot)):
            draw = np.concatenate([groups[j] for j in picks[b]])
            means[b] = draw.mean()
            medians[b] = np.median(draw)
        return {"mean": _percentile_ci(means, ci_level),
                "median": _percentile_ci(medians, ci_level)}
    block = max(1, min(int(block), n))
    if block == 1:
        draws = x[rng.integers(0, n, size=(int(n_boot), n))]
    else:
        n_blocks = int(np.ceil(n / block))
        starts = rng.integers(0, n - block + 1, size=(int(n_boot), n_blocks))
        offs = np.arange(block)
        idx = (starts[:, :, None] + offs[None, None, :]).reshape(int(n_boot), -1)[:, :n]
        draws = x[idx]
    return {"mean": _percentile_ci(draws.mean(axis=1), ci_level),
            "median": _percentile_ci(np.median(draws, axis=1), ci_level)}


def summarize(returns: Sequence[float], mdds: Sequence[float] | None = None, *,
              n_boot: int = 2000, ci_level: float = 0.95, seed: int = 20240101,
              block: int = 1, clusters: Sequence[int] | None = None,
              positions: Sequence[int] | None = None, horizon: int = 0) -> dict:
    """n / mean / median / win rate / quartiles / extremes / std / MDD / CI.

    When ``clusters`` (and ``positions``) are supplied the CI is a cluster
    bootstrap and the report also carries the i.i.d. interval it would have
    produced, plus the overlap-discounted effective sample size — the two
    numbers that say whether the headline interval is honest.
    """
    x = np.asarray([v for v in returns if v is not None and np.isfinite(v)], dtype=float)
    stats: dict = {"n": int(x.size)}
    if x.size == 0:
        return {**stats, "mean": np.nan, "median": np.nan, "win_rate": np.nan,
                "p25": np.nan, "p75": np.nan, "min": np.nan, "max": np.nan,
                "std": np.nan, "mdd_mean": np.nan, "mdd_median": np.nan,
                "ci_mean": (np.nan, np.nan), "ci_median": (np.nan, np.nan),
                "ci_mean_iid": (np.nan, np.nan), "ci_method": "none",
                "ess": 0.0, "n_episodes": 0}
    stats.update({
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "win_rate": float(np.mean(x > 0) * 100.0),
        "p25": float(np.percentile(x, 25)),
        "p75": float(np.percentile(x, 75)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
        "std": float(np.std(x, ddof=1)) if x.size > 1 else np.nan,
    })
    mdd_in = [] if mdds is None else list(mdds)
    m = np.asarray([v for v in mdd_in if v is not None and np.isfinite(v)], dtype=float)
    stats["mdd_mean"] = float(np.mean(m)) if m.size else np.nan
    stats["mdd_median"] = float(np.median(m)) if m.size else np.nan

    ci = bootstrap_ci(x, n_boot=n_boot, ci_level=ci_level, seed=seed, block=block,
                      clusters=clusters)
    stats["ci_mean"], stats["ci_median"] = ci["mean"], ci["median"]
    iid = bootstrap_ci(x, n_boot=n_boot, ci_level=ci_level, seed=seed)
    stats["ci_mean_iid"] = iid["mean"]
    if not np.isfinite(stats["ci_mean"][0]):     # 에피소드가 하나뿐인 경우의 안전장치
        stats["ci_mean"], stats["ci_median"] = iid["mean"], iid["median"]
        stats["ci_method"] = "iid"
    else:
        stats["ci_method"] = ("cluster" if clusters is not None
                              else ("block" if block > 1 else "iid"))
    stats["ess"] = (effective_sample_size(positions, horizon)
                    if positions is not None and horizon else float(x.size))
    stats["n_episodes"] = int(len(np.unique(np.asarray(list(clusters), dtype=int)))) \
        if clusters is not None else int(x.size)
    return stats


@dataclass
class HorizonResult:
    horizon: int
    matched: dict
    baseline: dict
    diff_mean: float = np.nan
    diff_median: float = np.nan
    diff_win_rate: float = np.nan
    ci_excludes_zero: bool = False
    baseline_pctile: float = np.nan     # matched mean 이 baseline 분포의 몇 번째 백분위인가
    n_input: int = 0                    # horizon 독립화 이전 match 개수
    dropped: int = 0                    # horizon 독립화로 제외된 개수
    dates: pd.DatetimeIndex = field(default_factory=lambda: pd.DatetimeIndex([]))
    warnings: list[str] = field(default_factory=list)

    @property
    def ess(self) -> float:
        return float(self.matched.get("ess", np.nan))

    @property
    def ci_width(self) -> float:
        lo, hi = self.matched.get("ci_mean", (np.nan, np.nan))
        return float(hi - lo)

    @property
    def ci_width_iid(self) -> float:
        lo, hi = self.matched.get("ci_mean_iid", (np.nan, np.nan))
        return float(hi - lo)


def analyze(close: pd.Series, matches, fwd_params, *,
            baseline_mask: pd.Series | None = None, min_gap: int = 0,
            index: pd.DatetimeIndex | None = None,
            episode_pick: str = "best") -> dict[int, HorizonResult]:
    """Matched vs unconditional forward-return statistics for every horizon.

    ``matches`` is either the scored frame from the similarity/strict engines
    (index = match dates, ``score`` column) or a plain sequence of dates.

    ``fwd_params.independence``
      * ``"all"``      — every match is used; overlap is priced into the CI by
        the cluster bootstrap and reported through the effective sample size.
      * ``"horizon"``  — the matched set is re-de-clustered per horizon with a
        minimum gap of h trading days, giving a strictly non-overlapping sample
        (fewer observations, no overlap left to model).
    """
    from . import similarity  # 순환 import 없음: similarity 는 forward 를 쓰지 않는다

    horizons = [int(h) for h in fwd_params.horizons]
    fwd = forward_returns(close, horizons)
    mdd = forward_max_drawdown(close, horizons)
    calendar = pd.DatetimeIndex(index if index is not None else close.index)
    pos_of = pd.Series(np.arange(len(calendar)), index=calendar)

    if isinstance(matches, pd.DataFrame):
        scored = matches
    else:
        dates = pd.DatetimeIndex([d for d in matches])
        scored = pd.DataFrame({"distance": np.nan, "score": np.nan}, index=dates)
    scored = scored[scored.index.isin(fwd.index)]

    independence = str(getattr(fwd_params, "independence", "all"))
    ci_method = str(getattr(fwd_params, "ci_method", "cluster"))

    out: dict[int, HorizonResult] = {}
    for h in horizons:
        col, mcol = f"fwd_{h}", f"mdd_{h}"
        base_series = fwd[col]
        if baseline_mask is not None:
            base_series = base_series[baseline_mask.reindex(base_series.index).fillna(False)]
        base_mdd = mdd[mcol].reindex(base_series.index)

        sub = scored
        if independence == "horizon" and len(scored) and int(h) > int(min_gap or 0):
            sub = similarity.decluster(scored.fillna({"score": 0.0}), calendar,
                                       min_gap=int(h), pick=episode_pick, top_n=None)
        dates = pd.DatetimeIndex(sub.index)
        sample = pd.DataFrame({
            "ret": fwd[col].reindex(dates),
            "mdd": mdd[mcol].reindex(dates),
            "pos": pos_of.reindex(dates),
        }).dropna(subset=["ret"])

        positions = sample["pos"].to_numpy(dtype=int) if len(sample) else np.empty(0, dtype=int)
        clusters = episode_clusters(positions, h) if len(sample) else np.empty(0, dtype=int)
        matched = summarize(sample["ret"], sample["mdd"],
                            n_boot=fwd_params.bootstrap_samples, ci_level=fwd_params.ci_level,
                            seed=fwd_params.seed, block=1,
                            clusters=clusters if ci_method == "cluster" else None,
                            positions=positions, horizon=h)
        baseline = summarize(base_series, base_mdd, n_boot=fwd_params.bootstrap_samples,
                             ci_level=fwd_params.ci_level, seed=fwd_params.seed + 1, block=h)

        # 에피소드 수는 CI 방식과 무관한 사실이므로 항상 실제 값으로 기록한다.
        matched["n_episodes"] = int(len(np.unique(clusters))) if len(clusters) else 0
        res = HorizonResult(horizon=h, matched=matched, baseline=baseline,
                            n_input=int(len(scored)), dropped=int(len(scored) - len(sub)),
                            dates=dates)
        if matched["n"]:
            res.diff_mean = matched["mean"] - baseline["mean"]
            res.diff_median = matched["median"] - baseline["median"]
            res.diff_win_rate = matched["win_rate"] - baseline["win_rate"]
            lo, hi = matched["ci_mean"]
            res.ci_excludes_zero = bool(np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0))
            clean = base_series.dropna()
            if len(clean):
                res.baseline_pctile = float((clean < matched["mean"]).mean() * 100.0)
        res.warnings = _warnings(res, fwd_params, min_gap, independence, ci_method)
        out[h] = res
    return out


def _warnings(res: HorizonResult, fwd_params, min_gap: int, independence: str,
              ci_method: str) -> list[str]:
    h, matched = res.horizon, res.matched
    msgs: list[str] = []
    if matched["n"] < int(fwd_params.min_sample_warn):
        msgs.append(f"표본이 {matched['n']}개뿐입니다 (경고 기준 {fwd_params.min_sample_warn}개) — "
                    "평균·승률을 신뢰하기 어렵습니다.")
    if res.dropped:
        msgs.append(f"horizon 독립 표본 모드로 {res.dropped}개를 제외해 {matched['n']}개만 사용했습니다 "
                    f"(최소 간격 {h}거래일).")
    ess = matched.get("ess", np.nan)
    if matched["n"] > 1 and np.isfinite(ess) and ess < matched["n"] * 0.8:
        msgs.append(f"forward 구간이 겹쳐 유효 표본은 약 {ess:.1f}개입니다 (표시된 n={matched['n']}, "
                    f"독립 에피소드 {matched.get('n_episodes', '?')}개) — n 을 액면 그대로 읽지 마세요.")
    if ci_method == "iid" and np.isfinite(ess) and ess < matched["n"] * 0.8:
        msgs.append("i.i.d. bootstrap 은 이 겹침을 무시하므로 신뢰구간이 실제보다 좁습니다 — "
                    "cluster bootstrap 사용을 권합니다.")
    if min_gap and matched["n"] > 1 and int(min_gap) < h and independence != "horizon":
        msgs.append(f"de-clustering 간격({min_gap}일)이 horizon({h}일)보다 짧아 forward 구간이 겹칩니다.")
    if matched["n"] and not res.ci_excludes_zero:
        msgs.append("평균의 95% 신뢰구간이 0을 포함합니다 (방향성 결론 불가).")
    return msgs
