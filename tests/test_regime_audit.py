"""Audit / data-quality / sample-independence tests for the Market Regime Lab.

The point of this file is *independent* recomputation: the expected values are
built here with plain pandas/numpy from the raw OHLCV, never by calling the
function under test. Five fixed historical dates are audited end to end —
SMA and 이격률, trailing returns, 52주 낙폭, realized volatility, the three
distribution-day conditions, the robust z-scores, the weighted distance and
similarity score, and the start/end prices behind every forward return — and
each is compared with what the audit screen would show.

Run with:  python -m pytest tests/test_regime_audit.py -q
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from app.regime import audit, forward, quality, similarity
from app.regime.config import ForwardParams, Params, load_config
from app.regime.data import loader
from app.regime.features import build_features

MAD_TO_SIGMA = 1.4826


@pytest.fixture(scope="module")
def setup():
    params = Params.from_config(load_config())
    market = loader.load_market(params.ticker, params.years, params.exogenous,
                                source="synthetic", use_cache=False)
    fs = build_features(market, params)
    return market, params, fs


@pytest.fixture(scope="module")
def anchor(setup):
    market, params, fs = setup
    return market.calendar[fs.valid_mask().reindex(market.calendar).fillna(False)].max()


@pytest.fixture(scope="module")
def sample_dates(setup, anchor):
    """Five spread-out past dates with a full 120-day forward window."""
    market, params, fs = setup
    usable = fs.values[fs.valid_mask()].index
    cal = market.calendar
    cutoff = cal[len(cal) - 1 - 120]
    usable = usable[usable <= cutoff]
    picks = [usable[int(len(usable) * f)] for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
    return pd.DatetimeIndex(picks)


# ---------------- audit vs independent recomputation ----------------

def test_audit_ohlcv_and_trend_match_raw_data(setup, anchor, sample_dates):
    market, params, fs = setup
    close = market.prices["close"]
    for date in sample_dates:
        res = audit.audit_match(market, fs, params, anchor, date)

        today = res.ohlcv[res.ohlcv["구분"] == "당일"].iloc[0]
        for col in ("open", "high", "low", "close", "volume"):
            assert today[col] == pytest.approx(float(market.prices.loc[date, col]))

        for _, row in res.trend.iterrows():
            w = int(row["이동평균"].replace("SMA", ""))
            expected_sma = float(close.loc[:date].iloc[-w:].mean())     # 독립 재계산
            expected_gap = (float(close.loc[date]) / expected_sma - 1.0) * 100.0
            assert row["재계산 SMA"] == pytest.approx(expected_sma)
            assert row["저장된 SMA"] == pytest.approx(expected_sma)
            assert row["이격률 재계산 (%)"] == pytest.approx(expected_gap)
            assert row["이격률 feature (%)"] == pytest.approx(expected_gap)


def test_audit_momentum_and_volatility_features(setup, sample_dates):
    market, params, fs = setup
    close = market.prices["close"].astype(float)
    pos_of = pd.Series(np.arange(len(close)), index=close.index)
    for date in sample_dates:
        p = int(pos_of.loc[date])
        for k in params.features.return_windows:
            expected = (close.iloc[p] / close.iloc[p - int(k)] - 1.0) * 100.0
            assert fs.values.loc[date, f"ret_{int(k)}"] == pytest.approx(expected)

        hw = int(params.features.high_window)
        expected_dd = (close.iloc[p] / close.iloc[p - hw + 1: p + 1].max() - 1.0) * 100.0
        assert fs.values.loc[date, "dd_52w"] == pytest.approx(expected_dd)

        w = int(params.features.vol_window)
        logret = np.log(close / close.shift(1))
        expected_vol = float(logret.iloc[p - w + 1: p + 1].std(ddof=1) * np.sqrt(252) * 100)
        assert fs.values.loc[date, "vol_realized"] == pytest.approx(expected_vol)


def test_audit_distribution_day_conditions(setup, anchor, sample_dates):
    market, params, fs = setup
    px = market.prices
    dp = params.distribution
    pos_of = pd.Series(np.arange(len(px)), index=px.index)
    for date in sample_dates:
        res = audit.audit_match(market, fs, params, anchor, date)
        p = int(pos_of.loc[date])
        c, c1 = float(px["close"].iloc[p]), float(px["close"].iloc[p - 1])
        h, l = float(px["high"].iloc[p]), float(px["low"].iloc[p])
        v, v1 = float(px["volume"].iloc[p]), float(px["volume"].iloc[p - 1])

        exp_ret = (c / c1 - 1.0) * 100.0
        exp_ratio = v / v1
        exp_clv = (c - l) / (h - l) if h > l else 0.5
        rows = {r["조건"][0]: r for _, r in res.distribution.iterrows()}
        assert rows["①"]["값"] == pytest.approx(exp_ret)
        assert rows["②"]["값"] == pytest.approx(exp_ratio)
        assert rows["③"]["값"] == pytest.approx(exp_clv)
        assert bool(rows["①"]["통과"]) == (exp_ret <= -dp.drop_pct)
        assert bool(rows["②"]["통과"]) == (exp_ratio >= 1 + dp.volume_bump_pct / 100)
        assert bool(rows["③"]["통과"]) == (exp_clv <= dp.clv_max)

        # lookback 안의 분산일 개수 = dd_count feature
        flags = []
        for j in range(p - int(dp.lookback) + 1, p + 1):
            cj, cj1 = float(px["close"].iloc[j]), float(px["close"].iloc[j - 1])
            hj, lj = float(px["high"].iloc[j]), float(px["low"].iloc[j])
            vj, vj1 = float(px["volume"].iloc[j]), float(px["volume"].iloc[j - 1])
            clv = (cj - lj) / (hj - lj) if hj > lj else 0.5
            flags.append((cj / cj1 - 1) * 100 <= -dp.drop_pct
                         and vj >= vj1 * (1 + dp.volume_bump_pct / 100)
                         and clv <= dp.clv_max)
        assert len(res.dd_days) == sum(flags)
        assert fs.values.loc[date, "dd_count"] == pytest.approx(float(sum(flags)))


def test_audit_standardization_and_distance_recomputed_by_hand(setup, anchor, sample_dates):
    market, params, fs = setup
    weights = params.similarity.weights
    for date in sample_dates:
        res = audit.audit_match(market, fs, params, anchor, date, weights=weights)
        contrib_sum, w_sum = 0.0, 0.0
        for _, row in res.features.iterrows():
            key = row["key"]
            col = fs.values.loc[fs.values.index <= anchor, key].dropna()
            center = float(col.median())                       # 독립 재계산 (robust)
            scale = float((col - center).abs().median()) * MAD_TO_SIGMA
            z_date = (float(fs.values.loc[date, key]) - center) / scale
            z_anchor = (float(fs.values.loc[anchor, key]) - center) / scale
            w = float(weights[key])

            assert row["center"] == pytest.approx(center)
            assert row["scale"] == pytest.approx(scale)
            assert row["z (과거일)"] == pytest.approx(z_date)
            assert row["z (기준일)"] == pytest.approx(z_anchor)
            assert row["z 차이"] == pytest.approx(z_date - z_anchor)
            assert row["가중 기여 w·Δz²"] == pytest.approx(w * (z_date - z_anchor) ** 2)
            contrib_sum += w * (z_date - z_anchor) ** 2
            w_sum += w

        expected_d = float(np.sqrt(contrib_sum / w_sum))
        expected_score = float(100 * np.exp(-0.5 * expected_d ** 2))
        assert res.distance["거리 d = √(Σw·Δz²/Σw)"] == pytest.approx(expected_d)
        assert res.distance["점수 100·exp(−d²/2)"] == pytest.approx(expected_score)

        # 엔진이 내놓는 값과도 같아야 한다
        scored, _ = similarity.score_days(fs.values, anchor, weights)
        assert float(scored.loc[date, "distance"]) == pytest.approx(expected_d)
        assert float(scored.loc[date, "score"]) == pytest.approx(expected_score)


def test_audit_forward_prices_and_returns(setup, anchor, sample_dates):
    market, params, fs = setup
    close = market.prices["close"].astype(float)
    pos_of = pd.Series(np.arange(len(close)), index=close.index)
    for date in sample_dates:
        res = audit.audit_match(market, fs, params, anchor, date)
        p = int(pos_of.loc[date])
        for _, row in res.forward.iterrows():
            h = int(row["Horizon"].replace("+", "").replace("일", ""))
            start_px, end_px = float(close.iloc[p]), float(close.iloc[p + h])
            assert row["시작 종가"] == pytest.approx(start_px)
            assert row["종료 종가"] == pytest.approx(end_px)
            assert row["종료일"] == str(close.index[p + h].date())
            expected = (end_px / start_px - 1.0) * 100.0
            assert row["수익률 재계산 (%)"] == pytest.approx(expected)
            assert row["수익률 feature (%)"] == pytest.approx(expected)

            path = close.iloc[p: p + h + 1]
            expected_mdd = float((path / path.cummax() - 1).min() * 100)
            assert row["구간 최대낙폭 (%)"] == pytest.approx(expected_mdd)


def test_audit_declustering_status_is_consistent(setup, anchor):
    market, params, fs = setup
    sim = replace(params.similarity, top_n=15, min_gap=20)
    scored, _ = similarity.candidate_scores(fs.values, anchor, sim.weights, sim,
                                            valid=fs.valid_mask(), max_horizon=120)
    matches = similarity.decluster(scored, market.calendar, sim.min_gap,
                                   pick=sim.episode_pick, top_n=sim.top_n)
    p = replace(params, similarity=sim)

    picked = matches.index[0]
    res = audit.audit_match(market, fs, p, anchor, picked, scored=scored, matches=matches)
    assert res.declustering["최종 선택"] is True
    assert res.declustering["de-clustering 전 순위"] == 1      # 최고 점수가 먼저 선택된다

    suppressed = [d for d in scored.index if d not in matches.index
                  and abs(int(market.calendar.get_loc(d)) - int(market.calendar.get_loc(picked))) < sim.min_gap]
    if suppressed:
        res2 = audit.audit_match(market, fs, p, anchor, suppressed[0],
                                 scored=scored, matches=matches)
        assert res2.declustering["최종 선택"] is False
        assert "탈락 사유" in res2.declustering


# ---------------- sample independence ----------------

def test_episode_clusters_chain_within_horizon():
    assert list(forward.episode_clusters([0, 15, 30, 100], 20)) == [0, 0, 0, 1]
    assert list(forward.episode_clusters([0, 25, 50], 20)) == [0, 1, 2]
    assert list(forward.episode_clusters([], 20)) == []


def test_effective_sample_size_discounts_overlap():
    # 완전히 떨어진 표본 → n_eff == n
    assert forward.effective_sample_size([0, 500, 1000], 120) == pytest.approx(3.0)
    # 같은 날 3개 → 사실상 1개
    assert forward.effective_sample_size([0, 0, 0], 120) == pytest.approx(1.0)
    # 절반씩 겹치는 두 개 → 1 < n_eff < 2
    ess = forward.effective_sample_size([0, 60], 120)
    assert 1.2 < ess < 1.9


def test_cluster_bootstrap_is_wider_than_iid_on_overlapping_sample(setup):
    market, params, fs = setup
    close = market.prices["close"]
    cal = market.calendar
    # 같은 국면에 몰린 날짜들: 3개 episode × 5일
    dates = pd.DatetimeIndex([cal[p] for base in (800, 2000, 3200) for p in range(base, base + 5)])
    scored = pd.DataFrame({"distance": 0.5, "score": 80.0}, index=dates)
    fp = ForwardParams(horizons=(120,), bootstrap_samples=600, seed=5)

    cluster = forward.analyze(close, scored, replace(fp, ci_method="cluster"),
                              baseline_mask=fs.valid_mask(), index=cal)[120]
    iid = forward.analyze(close, scored, replace(fp, ci_method="iid"),
                          baseline_mask=fs.valid_mask(), index=cal)[120]
    assert cluster.matched["n"] == iid.matched["n"] == 15
    assert cluster.matched["n_episodes"] == 3
    assert cluster.ess < 5.0                       # 15개처럼 보이지만 실제 정보량은 3 에피소드
    assert cluster.ci_width > iid.ci_width         # i.i.d. 는 구간을 좁게 만든다
    assert any("유효 표본" in w for w in cluster.warnings)


def test_horizon_independence_mode_gives_non_overlapping_sample(setup):
    market, params, fs = setup
    close = market.prices["close"]
    cal = market.calendar
    dates = pd.DatetimeIndex([cal[p] for base in (800, 2000, 3200) for p in range(base, base + 5)])
    scored = pd.DataFrame({"distance": 0.5, "score": np.linspace(90, 80, len(dates))}, index=dates)
    fp = ForwardParams(horizons=(20, 120), bootstrap_samples=300, independence="horizon")
    res = forward.analyze(close, scored, fp, baseline_mask=fs.valid_mask(), index=cal, min_gap=1)

    pos = pd.Series(np.arange(len(cal)), index=cal)
    for h in (20, 120):
        used = pos.reindex(res[h].dates).to_numpy()
        gaps = np.diff(np.sort(used))
        assert (gaps >= h).all(), f"h={h} 표본이 아직 겹칩니다"
        assert res[h].matched["n"] == 3            # episode 당 하나씩만 남는다
        assert res[h].dropped == 12
        assert res[h].ess == pytest.approx(3.0)


# ---------------- data quality ----------------

def _frame(close, volume=None, start="2015-01-02", periods=None):
    idx = pd.bdate_range(start, periods=periods or len(close))
    n = len(idx)
    close = pd.Series(close, index=idx, dtype=float)
    vol = pd.Series(volume if volume is not None else np.full(n, 1e6), index=idx, dtype=float)
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": vol}, index=idx)


def test_quality_detects_duplicates_and_gaps():
    df = _frame(np.linspace(100, 120, 300))
    dup = pd.concat([df, df.iloc[[10]]]).sort_index()
    checks = {c.key: c for c in quality.check_calendar("T", dup, years=1)}
    assert checks["duplicates"].status == "fail"

    holed = df.drop(df.index[100:130])
    checks = {c.key: c for c in quality.check_calendar("T", holed, years=1)}
    assert checks["gaps"].status == "warn"


def test_quality_detects_stale_last_bar():
    df = _frame(np.linspace(100, 120, 300), start="2015-01-02")
    checks = {c.key: c for c in quality.check_calendar("T", df, years=1)}
    assert checks["stale"].status == "fail"        # 몇 년 전 데이터


def test_quality_volume_checks_flag_missing_zero_and_unit_breaks():
    n = 600
    good = _frame(np.linspace(100, 130, n))
    checks = {c.key: c for c in quality.check_volume(good, "AAPL")}
    assert checks["volume_usable"].status == "ok"
    assert checks["volume_usable"].suggestion == ""

    vol = np.full(n, 1e6)
    vol[::3] = 0.0                                  # 3일 중 1일이 0
    bad = _frame(np.linspace(100, 130, n), volume=vol)
    checks = {c.key: c for c in quality.check_volume(bad, "^IXIC")}
    assert checks["volume_usable"].status == "fail"
    assert "QQQ" in checks["volume_usable"].suggestion       # 대체 소스 제안
    assert checks["volume_definition"].status == "info"      # 지수 거래량 정의 안내

    unit = np.concatenate([np.full(n // 2, 1e6), np.full(n - n // 2, 1e9)])
    shifted = _frame(np.linspace(100, 130, n), volume=unit)
    checks = {c.key: c for c in quality.check_volume(shifted, "^IXIC")}
    assert checks["volume_unit"].status == "warn"


@pytest.mark.parametrize("scale,expected,status", [
    (1.0, "percent", "ok"),        # 4.28
    (10.0, "tenths", "warn"),      # 42.8
    (100.0, "basis", "fail"),      # 428
    (0.01, "decimal", "fail"),     # 0.0428
])
def test_quality_infers_yield_unit(scale, expected, status):
    idx = pd.bdate_range("2015-01-02", periods=500)
    s = pd.Series(np.linspace(2.0, 4.5, 500) * scale, index=idx)
    checks = {c.key: c for c in quality.check_yield(s, "^TNX", "10Y", "percent")}
    assert expected in checks["yield_unit"].detail
    assert checks["yield_unit"].status == status


def test_quality_flags_non_yield_series():
    idx = pd.bdate_range("2015-01-02", periods=500)
    prices = pd.Series(np.linspace(95, 130, 500), index=idx)      # 채권 '가격'을 받은 경우
    checks = {c.key: c for c in quality.check_yield(prices, "^TNX", "10Y", "percent")}
    assert checks["yield_range"].status == "fail"


def test_quality_report_runs_end_to_end_and_flags_synthetic(setup):
    market, params, fs = setup
    reports = quality.run_checks(market, params)
    frame = quality.summary_frame(reports)
    assert {"시리즈", "항목", "값", "판정"} <= set(frame.columns)
    assert len(frame) > 10
    # 합성 데이터는 실데이터가 아니라는 경고가 반드시 있어야 한다
    assert any("synthetic" in c.detail for r in reports for c in r.checks)
    assert quality.overall_status(reports) in ("ok", "warn", "fail")
