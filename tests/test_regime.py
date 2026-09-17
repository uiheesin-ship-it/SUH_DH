"""Offline unit tests for the Market Regime Lab (app/regime).

Nothing here touches the network: series are either hand-built (so the expected
answer is known by construction) or come from the deterministic synthetic
provider. The look-ahead tests are the important ones — they re-compute every
feature on a truncated history and require the value at date t to be identical.

Run with:  python -m pytest tests/test_regime.py -q
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from app.regime import forward, matching, similarity, validation
from app.regime.config import (DistributionParams, FeatureParams, ForwardParams,
                               Params, SimilarityParams, ValidationParams, load_config)
from app.regime.data import loader, sources
from app.regime.data.align import align_series, stale_days
from app.regime.features import build_features
from app.regime.features.distribution import flags


def _params(**kw) -> Params:
    return replace(Params.from_config(load_config()), **kw)


@pytest.fixture(scope="module")
def market():
    return loader.load_market("^IXIC", 20, Params.from_config().exogenous,
                              source="synthetic", use_cache=False)


@pytest.fixture(scope="module")
def built(market):
    p = Params.from_config()
    return market, p, build_features(market, p)


# ---------------- data / alignment ----------------

def test_synthetic_series_is_deterministic():
    a = sources.synthetic_prices("^IXIC", "2010-01-01", "2020-01-01")
    b = sources.synthetic_prices("^IXIC", "2010-01-01", "2020-01-01")
    pd.testing.assert_frame_equal(a, b)
    assert 245 < len(a) / ((a.index.max() - a.index.min()).days / 365.25) < 258


def test_align_forward_fills_only_and_never_backfills():
    cal = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    exog = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-03", "2020-01-06"]))
    out = align_series(cal, exog)
    assert np.isnan(out.iloc[0])          # 첫날 이전 값은 미래에서 끌어오지 않는다
    assert out.loc["2020-01-03"] == 1.0
    assert out.loc["2020-01-06"] == 2.0
    assert out.loc["2020-01-07"] == 2.0   # 직전 값 유지 (forward fill)


def test_align_drops_stale_values_beyond_limit():
    cal = pd.to_datetime(["2020-01-02", "2020-03-02"])
    exog = pd.Series([1.0], index=pd.to_datetime(["2020-01-02"]))
    out = align_series(cal, exog, max_stale_days=5)
    assert out.iloc[0] == 1.0 and np.isnan(out.iloc[1])
    assert stale_days(cal, exog) == 60


def test_loader_reports_last_update_per_series(market):
    assert not market.empty
    series = market.meta["series"]
    assert series["^IXIC"]["last_date"] == str(market.last_date.date())
    assert series["^TNX"]["coverage"] > 0.9


# ---------------- features ----------------

def test_trend_and_momentum_math_on_known_series():
    idx = pd.bdate_range("2015-01-01", periods=400)
    close = pd.Series(np.linspace(100, 200, 400), index=idx)
    px = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": 1e6}, index=idx)
    md = loader.MarketData("TEST", px, pd.DataFrame(index=idx), {"series": {}})
    p = _params(features=FeatureParams(sma_windows=(20,), slope_smas=(20,), slope_window=10,
                                       return_windows=(5,), high_window=60))
    fs = build_features(md, p)
    last = fs.values.iloc[-1]
    sma20 = close.rolling(20).mean().iloc[-1]
    assert last["px_vs_sma20"] == pytest.approx((close.iloc[-1] / sma20 - 1) * 100)
    assert last["ret_5"] == pytest.approx((close.iloc[-1] / close.iloc[-6] - 1) * 100)
    # 단조 상승이면 항상 신고가 → 낙폭 0, 기울기는 양수
    assert last["dd_52w"] == pytest.approx(0.0)
    assert last["sma20_slope"] > 0


def test_distribution_day_requires_all_three_conditions():
    idx = pd.bdate_range("2020-01-01", periods=5)
    # day1 기준: 종가 -1%, 거래량 2배, 저가 근처 마감 → 분산일
    px = pd.DataFrame({
        "open":  [100, 100, 100, 100, 100],
        "high":  [101, 101, 101, 101, 101],
        "low":   [99,   98,  98,  98,  98],
        "close": [100,  99, 100,  99,  99],
        "volume": [1e6, 2e6, 2e6, 1e6, 2e6],
    }, index=idx, dtype=float)
    px.loc[idx[4], "close"] = 100.9          # 하락폭은 크지만 고가 근처 마감 → CLV 탈락
    px.loc[idx[4], "low"] = 98.0
    md = loader.MarketData("TEST", px, pd.DataFrame(index=idx), {"series": {}})
    p = _params(distribution=DistributionParams(lookback=3, drop_pct=0.5,
                                                volume_bump_pct=0.0, clv_max=0.5))
    f = flags(md, p)
    assert bool(f["dd_flag"].iloc[1]) is True          # 세 조건 모두 충족
    assert bool(f["dd_flag"].iloc[2]) is False         # 상승일
    assert bool(f["dd_flag"].iloc[3]) is False         # 거래량 감소
    assert bool(f["dd_flag"].iloc[4]) is False         # CLV 높음(고가 근처 마감)

    fs = build_features(md, p)
    assert fs.values["dd_count"].iloc[-1] == 0.0       # 최근 3일 안에는 분산일 없음
    assert fs.values["dd_days_since"].iloc[-1] == 3.0


def test_distribution_thresholds_are_user_tunable():
    idx = pd.bdate_range("2020-01-01", periods=3)
    px = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                       "close": [100.0, 99.7, 99.4], "volume": [1e6, 1.05e6, 1.2e6]}, index=idx)
    md = loader.MarketData("TEST", px, pd.DataFrame(index=idx), {"series": {}})
    loose = flags(md, _params(distribution=DistributionParams(lookback=2, drop_pct=0.2,
                                                              volume_bump_pct=0.0, clv_max=0.9)))
    tight = flags(md, _params(distribution=DistributionParams(lookback=2, drop_pct=1.0,
                                                              volume_bump_pct=50.0, clv_max=0.1)))
    assert loose["dd_flag"].sum() == 2
    assert tight["dd_flag"].sum() == 0


def test_features_have_no_look_ahead(built):
    """Truncating the future must not change any feature value at date t."""
    market, p, fs = built
    idx = market.calendar
    cut = idx[len(idx) - 300]
    trimmed = loader.MarketData(market.ticker, market.prices.loc[:cut],
                                market.exog.loc[:cut], market.meta)
    fs_cut = build_features(trimmed, p)
    a = fs.values.loc[:cut].tail(200)
    b = fs_cut.values.loc[:cut].tail(200)
    pd.testing.assert_frame_equal(a[sorted(a.columns)], b[sorted(b.columns)])


# ---------------- similarity ----------------

def test_normalization_uses_only_history_up_to_asof(built):
    market, p, fs = built
    idx = fs.values.index
    asof = idx[len(idx) - 400]
    z_full, info_full = similarity.normalize_asof(fs.values, asof, mode="robust")
    z_cut, info_cut = similarity.normalize_asof(fs.values.loc[:asof], asof, mode="robust")
    pd.testing.assert_series_equal(info_full.center, info_cut.center)
    pd.testing.assert_series_equal(info_full.scale, info_cut.scale)
    pd.testing.assert_frame_equal(z_full.loc[:asof], z_cut)


def test_identical_state_scores_100(built):
    market, p, fs = built
    values = fs.values[fs.valid_mask()]
    asof = values.index[-1]
    # 기준일 벡터를 과거 어느 날짜에 그대로 복사해 두면 거리 0 이어야 한다.
    twin_date = values.index[len(values) // 2]
    patched = values.copy()
    patched.loc[twin_date] = values.loc[asof]
    scored, _ = similarity.score_days(patched, asof, p.similarity.weights)
    assert scored.loc[twin_date, "distance"] == pytest.approx(0.0, abs=1e-9)
    assert scored.loc[twin_date, "score"] == pytest.approx(100.0)
    assert scored["score"].max() == pytest.approx(100.0)


def test_candidate_mask_excludes_recent_and_unfinished_horizon(built):
    market, p, fs = built
    idx = fs.values.index
    asof = idx[-1]
    valid = fs.valid_mask()
    mask = similarity.candidate_mask(idx, asof, valid=valid, exclude_recent=30,
                                     require_full_horizon=True, max_horizon=120)
    chosen = idx[mask]
    assert chosen.max() <= idx[-31]
    assert chosen.max() <= idx[-121]


def test_decluster_enforces_min_gap_and_pick_mode():
    idx = pd.bdate_range("2020-01-01", periods=100)
    scored = pd.DataFrame({"distance": np.linspace(0.1, 1.0, 100),
                           "score": np.linspace(100, 1, 100)}, index=idx)
    best = similarity.decluster(scored, idx, min_gap=10, pick="best", top_n=5)
    pos = [idx.get_loc(d) for d in best.index]
    assert len(best) == 5
    assert min(abs(a - b) for i, a in enumerate(pos) for b in pos[i + 1:]) >= 10
    # 점수가 앞쪽일수록 높으므로 best 는 가장 이른 날짜들을 고른다
    assert best["score"].iloc[0] == pytest.approx(100.0)
    first = similarity.decluster(scored, idx, min_gap=10, pick="first", top_n=5)
    assert len(first) == 5


def test_strict_match_is_an_and_of_conditions(built):
    market, p, fs = built
    conds = [matching.Condition("dd_52w", "<=", -5.0), matching.Condition("dd_count", ">=", 3.0)]
    mask = matching.apply_conditions(fs.values, conds)
    sub = fs.values[mask]
    assert (sub["dd_52w"] <= -5.0).all() and (sub["dd_count"] >= 3.0).all()
    sim = replace(p.similarity, min_gap=20, exclude_recent=60)
    hits, _ = matching.strict_match(fs.values, conds, market.last_date, sim,
                                    weights=p.similarity.weights, max_horizon=120)
    assert len(hits) > 0
    assert mask.reindex(hits.index).all()


def test_between_condition():
    idx = pd.bdate_range("2020-01-01", periods=5)
    values = pd.DataFrame({"x": [-5.0, 0.0, 3.0, 7.0, 12.0]}, index=idx)
    cond = matching.Condition("x", "between", 0.0, 7.0)
    assert list(cond.mask(values)) == [False, True, True, True, False]


# ---------------- forward returns ----------------

def test_forward_returns_and_max_drawdown():
    close = pd.Series([100.0, 110.0, 90.0, 95.0, 120.0],
                      index=pd.bdate_range("2020-01-01", periods=5))
    fwd = forward.forward_returns(close, [2])
    assert fwd["fwd_2"].iloc[0] == pytest.approx(-10.0)
    mdd = forward.forward_max_drawdown(close, [2, 4])
    assert mdd["mdd_2"].iloc[0] == pytest.approx((90 / 110 - 1) * 100)
    assert mdd["mdd_4"].iloc[0] == pytest.approx((90 / 110 - 1) * 100)
    assert np.isnan(mdd["mdd_4"].iloc[1])


def test_summarize_matches_numpy_and_bootstrap_is_reproducible():
    rng = np.random.default_rng(7)
    sample = rng.normal(1.0, 3.0, 400)
    s1 = forward.summarize(sample, n_boot=500, seed=11)
    s2 = forward.summarize(sample, n_boot=500, seed=11)
    assert s1["n"] == 400
    assert s1["mean"] == pytest.approx(float(np.mean(sample)))
    assert s1["median"] == pytest.approx(float(np.median(sample)))
    assert s1["win_rate"] == pytest.approx(float((sample > 0).mean() * 100))
    assert s1["ci_mean"] == s2["ci_mean"]
    lo, hi = s1["ci_mean"]
    assert lo < s1["mean"] < hi


def test_block_bootstrap_widens_interval_on_autocorrelated_data():
    # 겹치는 forward 구간처럼 강하게 자기상관된 시계열
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(0, 1, 2000)).rolling(60).mean().dropna().to_numpy()
    iid = forward.bootstrap_ci(x, n_boot=400, seed=5, block=1)["mean"]
    blocked = forward.bootstrap_ci(x, n_boot=400, seed=5, block=60)["mean"]
    assert (blocked[1] - blocked[0]) > (iid[1] - iid[0])


def test_analyze_compares_with_baseline_and_warns_on_small_sample(built):
    market, p, fs = built
    valid = fs.valid_mask()
    dates = fs.values.dropna().index[:3]
    fwd_params = ForwardParams(horizons=(5, 20), bootstrap_samples=200, min_sample_warn=10)
    res = forward.analyze(market.prices["close"], dates, fwd_params,
                          baseline_mask=valid, min_gap=5)
    assert set(res) == {5, 20}
    assert res[5].matched["n"] == 3
    assert res[5].baseline["n"] > 1000
    assert any("표본이" in w for w in res[5].warnings)
    assert any("겹칩니다" in w for w in res[20].warnings)
    assert res[5].diff_mean == pytest.approx(res[5].matched["mean"] - res[5].baseline["mean"])


# ---------------- validation ----------------

def test_fold_layout_fixed_and_expanding(built):
    market, p, fs = built
    idx = fs.values.index
    fixed = validation.make_folds(idx, _params(validation=ValidationParams(
        mode="fixed", train_end="2015-12-31", validation_end="2020-12-31")))
    assert [f.kind for f in fixed] == ["in_sample", "out_of_sample", "out_of_sample"]
    assert fixed[0].end < fixed[1].start < fixed[1].end < fixed[2].start
    exp = validation.make_folds(idx, _params(validation=ValidationParams(
        mode="expanding", expanding_start="2016-01-01")))
    assert exp[0].kind == "in_sample"
    assert all(f.kind == "out_of_sample" for f in exp[1:])
    assert len(exp) >= 5


def test_walk_forward_never_uses_unfinished_forward_windows(built):
    """Every candidate that votes at t must have closed its own horizon before t."""
    market, p, fs = built
    horizon = 20
    fold = validation.Fold("test", "out_of_sample", pd.Timestamp("2018-01-01"),
                           pd.Timestamp("2018-12-31"))
    sim = replace(p.similarity, top_n=10, min_gap=20, exclude_recent=60)
    res = validation.run_fold(fs.values, market.prices["close"], p.similarity.weights,
                              sim, fold, horizon=horizon, step=20)
    assert len(res.trials) > 5
    assert res.trials["realized"].notna().all()
    assert np.isfinite(res.metrics["sign_hit_rate"])

    # 후보 제한을 직접 재현해 검증: t 시점 후보는 모두 t-horizon 이전이어야 한다.
    idx = pd.DatetimeIndex(fs.values.index)
    pos = pd.Series(np.arange(len(idx)), index=idx)
    t = res.trials.index[0]
    mask = (pos <= int(pos.loc[t]) - horizon) & (pos <= int(pos.loc[t]) - sim.exclude_recent)
    mask &= fs.valid_mask()
    scored, _ = similarity.score_days(fs.values.loc[idx <= t], t, p.similarity.weights,
                                      mask=mask.loc[idx <= t])
    matches = similarity.decluster(scored, idx, sim.min_gap, pick=sim.episode_pick, top_n=sim.top_n)
    assert (pos.reindex(matches.index) + horizon <= int(pos.loc[t])).all()
    assert res.trials.loc[t, "n_matches"] == len(matches)


def test_summary_table_separates_in_and_out_of_sample(built):
    market, p, fs = built
    params = _params(validation=ValidationParams(mode="fixed", train_end="2012-12-31",
                                                 validation_end="2016-12-31", step=40, horizon=20))
    sim = replace(p.similarity, top_n=10)
    res = validation.walk_forward(fs.values, market.prices["close"], p.similarity.weights,
                                  sim, params)
    table = validation.summary_table(res)
    assert set(table["구분"]) == {"In-Sample", "Out-of-Sample"}
    assert (table["평가 횟수"] > 0).all()
