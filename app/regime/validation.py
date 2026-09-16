"""Out-of-sample / walk-forward validation.

The trap this module exists for: tune weights and thresholds on 20 years of
history, then measure the rule on those same 20 years and call the result
evidence. Here the rule is *frozen* and replayed forward.

At every evaluation date *t* (sampled every ``step`` trading days) the engine
stands where a live user would stand:

* scaling (median/MAD) uses observations up to *t* only;
* candidate matches are restricted to days whose own forward window already
  **closed** before *t* — at *t* you cannot know what happened after a match
  that is still running, so those days are not allowed to vote;
* the signal is the median forward return of the matched days;
* the realised forward return at *t* is then compared with that signal.

Two layouts are offered — a fixed Train / Validation / Out-of-Sample split, and
an expanding window that re-evaluates year by year. Folds are labelled
in-sample or out-of-sample so the two can be read side by side: a rule that
only works in-sample is a rule that was fitted to noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import forward as fwd_mod
from . import similarity


@dataclass(frozen=True)
class Fold:
    name: str
    kind: str                       # in_sample | out_of_sample
    start: pd.Timestamp
    end: pd.Timestamp
    knowledge_end: pd.Timestamp | None = None   # None = expanding (t 시점까지 모두 사용)


@dataclass
class FoldResult:
    fold: Fold
    trials: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def make_folds(index: pd.DatetimeIndex, params) -> list[Fold]:
    v = params.validation
    start, end = index.min(), index.max()
    if v.mode == "expanding":
        first = max(pd.Timestamp(v.expanding_start), start)
        folds: list[Fold] = []
        for year in range(first.year, end.year + 1):
            y0 = max(pd.Timestamp(f"{year}-01-01"), first)
            y1 = min(pd.Timestamp(f"{year}-12-31"), end)
            if y0 >= y1:
                continue
            folds.append(Fold(name=str(year), kind="out_of_sample", start=y0, end=y1,
                              knowledge_end=None))
        # 첫 학습 구간은 in-sample 기준선으로 함께 보여 준다.
        folds.insert(0, Fold(name=f"~{first.year - 1} (In-Sample)", kind="in_sample",
                             start=start, end=first - pd.Timedelta(days=1), knowledge_end=None))
        return folds

    train_end = pd.Timestamp(v.train_end)
    valid_end = pd.Timestamp(v.validation_end)
    return [
        Fold("Training (In-Sample)", "in_sample", start, min(train_end, end), None),
        Fold("Validation (OOS)", "out_of_sample", train_end + pd.Timedelta(days=1),
             min(valid_end, end), None),
        Fold("Out-of-Sample", "out_of_sample", valid_end + pd.Timedelta(days=1), end, None),
    ]


def _eval_dates(index: pd.DatetimeIndex, fold: Fold, step: int, horizon: int,
                min_warmup: int) -> pd.DatetimeIndex:
    pos = pd.Series(np.arange(len(index)), index=index)
    in_fold = index[(index >= fold.start) & (index <= fold.end)]
    # 평가일 자신도 realized forward return 이 필요하므로 끝에서 horizon 만큼 자른다.
    ok = [d for d in in_fold
          if pos.loc[d] >= min_warmup and pos.loc[d] + horizon <= len(index) - 1]
    return pd.DatetimeIndex(ok[:: max(1, int(step))])


def run_fold(values: pd.DataFrame, close: pd.Series, weights: dict[str, float],
             sim_params, fold: Fold, *, horizon: int = 20, step: int = 5,
             valid: pd.Series | None = None, min_warmup: int = 250) -> FoldResult:
    index = pd.DatetimeIndex(values.index)
    if valid is None:
        valid = similarity._default_valid(values)
    fwd = fwd_mod.forward_returns(close, [horizon])[f"fwd_{horizon}"]
    pos = pd.Series(np.arange(len(index)), index=index)

    rows = []
    for t in _eval_dates(index, fold, step, horizon, min_warmup):
        # 후보는 (a) t 이전이고 (b) forward 구간이 t 이전에 끝난 날들뿐이다.
        cutoff_pos = int(pos.loc[t]) - int(horizon)
        allowed = pos <= cutoff_pos
        if fold.knowledge_end is not None:
            allowed &= index <= fold.knowledge_end
        mask = allowed & valid.reindex(index).fillna(False)
        if sim_params.exclude_recent:
            mask &= pos <= int(pos.loc[t]) - int(sim_params.exclude_recent)
        if not bool(mask.any()):
            continue
        scored, _ = similarity.score_days(values.loc[index <= t], t, weights,
                                          mode=sim_params.normalization,
                                          min_history=sim_params.min_history,
                                          mask=mask.loc[index <= t])
        if scored.empty:
            continue
        matches = similarity.decluster(scored, index, sim_params.min_gap,
                                       pick=sim_params.episode_pick, top_n=sim_params.top_n)
        if matches.empty:
            continue
        sample = fwd.reindex(matches.index).dropna()
        if sample.empty:
            continue
        rows.append({
            "date": t,
            "n_matches": int(len(sample)),
            "mean_score": float(matches["score"].mean()),
            "signal_median": float(sample.median()),
            "signal_mean": float(sample.mean()),
            "signal_win_rate": float((sample > 0).mean() * 100.0),
            "realized": float(fwd.loc[t]),
        })

    trials = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(
        columns=["n_matches", "mean_score", "signal_median", "signal_mean",
                 "signal_win_rate", "realized"])
    return FoldResult(fold=fold, trials=trials, metrics=fold_metrics(trials, fwd, fold))


def fold_metrics(trials: pd.DataFrame, fwd: pd.Series, fold: Fold) -> dict:
    """Did the signal carry information about what actually happened next?"""
    period = fwd[(fwd.index >= fold.start) & (fwd.index <= fold.end)].dropna()
    base = float(period.mean()) if len(period) else np.nan
    out = {
        "n_trials": int(len(trials)),
        "baseline_mean": base,
        "baseline_win_rate": float((period > 0).mean() * 100.0) if len(period) else np.nan,
    }
    if trials.empty:
        return out
    sig, real = trials["signal_median"], trials["realized"]
    out.update({
        "signal_mean": float(sig.mean()),
        "realized_mean": float(real.mean()),
        "realized_win_rate": float((real > 0).mean() * 100.0),
        "pearson": float(sig.corr(real)) if len(trials) > 2 else np.nan,
        # Spearman = 순위끼리의 Pearson. 직접 계산해 scipy 의존성을 피한다.
        "spearman": float(sig.rank().corr(real.rank())) if len(trials) > 2 else np.nan,
        "sign_hit_rate": float((np.sign(sig) == np.sign(real)).mean() * 100.0),
        "edge_vs_baseline": float(real.mean() - base) if np.isfinite(base) else np.nan,
    })
    # 신호가 강한 쪽(상위 1/3)과 약한 쪽(하위 1/3)의 실제 성과 차이 = spread.
    if len(trials) >= 9:
        hi = real[sig >= sig.quantile(2 / 3)]
        lo = real[sig <= sig.quantile(1 / 3)]
        out["top_tercile_mean"] = float(hi.mean())
        out["bottom_tercile_mean"] = float(lo.mean())
        out["tercile_spread"] = float(hi.mean() - lo.mean())
    return out


def walk_forward(values: pd.DataFrame, close: pd.Series, weights: dict[str, float],
                 sim_params, params, *, valid: pd.Series | None = None,
                 progress=None) -> list[FoldResult]:
    """Run every fold of the configured layout, frozen parameters throughout."""
    folds = make_folds(pd.DatetimeIndex(values.index), params)
    results: list[FoldResult] = []
    for i, fold in enumerate(folds):
        if progress is not None:
            progress((i) / max(1, len(folds)), f"{fold.name} …")
        if fold.start > fold.end:
            continue
        results.append(run_fold(values, close, weights, sim_params, fold,
                                horizon=params.validation.horizon,
                                step=params.validation.step, valid=valid))
    if progress is not None:
        progress(1.0, "완료")
    return results


def summary_table(results: list[FoldResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        m = r.metrics
        rows.append({
            "Fold": r.fold.name,
            "구분": "In-Sample" if r.fold.kind == "in_sample" else "Out-of-Sample",
            "기간": f"{r.fold.start.date()} ~ {r.fold.end.date()}",
            "평가 횟수": m.get("n_trials", 0),
            "신호 평균(%)": m.get("signal_mean", np.nan),
            "실현 평균(%)": m.get("realized_mean", np.nan),
            "기간 평균(%)": m.get("baseline_mean", np.nan),
            "초과(%p)": m.get("edge_vs_baseline", np.nan),
            "방향 적중률(%)": m.get("sign_hit_rate", np.nan),
            "Spearman": m.get("spearman", np.nan),
            "상·하위 스프레드(%p)": m.get("tercile_spread", np.nan),
        })
    return pd.DataFrame(rows)
