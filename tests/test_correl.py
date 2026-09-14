"""티커 상관관계: 수익률·베타·잔차·상관행렬과 이웃 추리기 테스트.

실제 시세는 샌드박스에서 못 받지만 **계산은 전부 검증할 수 있다** — 참값을 아는
합성 데이터를 넣고 되찾아지는지 본다. 이 파일이 지키는 핵심 주장은 하나다:
"시장 성분을 빼면 테마 동료가 상위로 올라오고, 고베타 무관 종목은 내려간다."
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from app import correl

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load_builder():
    """tools/ 는 패키지가 아니므로 경로로 직접 읽어 온다."""
    spec = importlib.util.spec_from_file_location("correl_us", TOOLS / "correl_us.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ 수익률
def test_daily_returns_basic():
    close = np.array([[100.0, 110.0, 99.0], [50.0, 50.0, 25.0]])
    out = correl.daily_returns(close)
    assert out == pytest.approx(np.array([[0.1, -0.1], [0.0, -0.5]]))


def test_daily_returns_marks_gaps_not_zero():
    """상장 전·거래정지는 수익률 0 이 아니라 결측이어야 한다.

    0 으로 채우면 "그날 안 움직였다"가 되어 상관이 엉뚱하게 낮아진다.
    """
    close = np.array([[np.nan, np.nan, 10.0, 11.0]])
    out = correl.daily_returns(close)
    assert np.isnan(out[0, 0]) and np.isnan(out[0, 1])
    assert out[0, 2] == pytest.approx(0.1)


def test_daily_returns_ignores_nonpositive_price():
    close = np.array([[0.0, 5.0, 6.0]])
    out = correl.daily_returns(close)
    assert np.isnan(out[0, 0]) and out[0, 1] == pytest.approx(0.2)


# -------------------------------------------------------------------- 베타
def test_market_beta_is_recovered():
    rng = np.random.default_rng(0)
    mkt = rng.normal(0, 0.01, 800)
    true_b = np.array([0.4, 1.0, 1.9])
    R = true_b[:, None] * mkt[None, :] + rng.normal(0, 0.003, (3, 800))
    assert correl.market_betas(R, mkt) == pytest.approx(true_b, abs=0.05)


def test_market_beta_uses_only_overlapping_days():
    """결측이 있는 종목도 자기가 값을 가진 날만으로 베타가 잡혀야 한다."""
    rng = np.random.default_rng(1)
    mkt = rng.normal(0, 0.01, 400)
    R = np.vstack([1.5 * mkt + rng.normal(0, 0.002, 400)])
    R[0, :200] = np.nan
    assert correl.market_betas(R, mkt)[0] == pytest.approx(1.5, abs=0.1)


def test_beta_is_zero_without_enough_data():
    assert correl.market_betas(np.array([[np.nan, np.nan]]), np.array([0.01, -0.01]))[0] == 0.0


# -------------------------------------------------------------------- 잔차
def test_residual_has_no_market_component_left():
    rng = np.random.default_rng(2)
    mkt = rng.normal(0, 0.01, 600)
    R = np.array([0.5, 1.8])[:, None] * mkt[None, :] + rng.normal(0, 0.004, (2, 600))
    E = correl.residualize(R, mkt)
    for row in E:
        assert abs(np.corrcoef(row, mkt)[0, 1]) < 1e-8


# ---------------------------------------------------------------- 상관행렬
def test_corr_matrix_matches_numpy():
    X = np.random.default_rng(3).normal(0, 1, (6, 200))
    assert correl.corr_matrix(X) == pytest.approx(np.corrcoef(X), abs=1e-9)


def test_corr_matrix_window_uses_only_recent_days():
    """창을 줄이면 옛날 구간은 안 봐야 한다 — 앞뒤 관계가 정반대인 데이터로 확인."""
    a = np.concatenate([np.linspace(-1, 1, 100), np.linspace(-1, 1, 100)])
    b = np.concatenate([np.linspace(1, -1, 100), np.linspace(-1, 1, 100)])
    X = np.vstack([a, b])
    assert correl.corr_matrix(X, window=100)[0, 1] == pytest.approx(1.0, abs=1e-6)
    assert correl.corr_matrix(X)[0, 1] < 0.6      # 전체 구간은 앞쪽이 상쇄한다


def test_corr_matrix_nans_out_thin_pairs():
    """관측이 며칠뿐인 쌍은 값을 주면 안 된다 — 5일치로 구한 0.98 은 의미가 없다."""
    X = np.random.default_rng(4).normal(0, 1, (3, 200))
    X[0, :195] = np.nan
    C = correl.corr_matrix(X, min_obs=50)
    assert np.isnan(C[0, 1]) and np.isnan(C[0, 2])
    assert np.isfinite(C[1, 2])


def test_corr_matrix_stays_in_range():
    X = np.random.default_rng(5).normal(0, 1, (8, 60))
    C = correl.corr_matrix(X)
    assert np.nanmin(C) >= -1.0 and np.nanmax(C) <= 1.0


# ------------------------------------------- 핵심 주장: 잔차가 테마를 고른다
def _theme_world(seed=7, T=260):
    """시장 + 테마 + 고유잡음으로 이루어진 합성 시장.

    0번이 입력 종목(테마 핵심), 1~2번이 같은 테마, 3~4번은 테마와 무관하지만
    베타가 높다 — 원시 상관만 보면 이 둘이 끼어드는 상황을 재현한다.
    """
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0, 0.010, T)
    theme = rng.normal(0, 0.016, T)

    def mk(beta, th, idio=0.012):
        return beta * mkt + th * theme + rng.normal(0, idio, T)

    R = np.vstack([
        mk(0.9, 1.0),     # 0 입력 종목
        mk(0.5, 0.9),     # 1 같은 테마 · 저베타
        mk(1.0, 0.8),     # 2 같은 테마 · 보통 베타
        mk(2.0, 0.0),     # 3 테마 무관 · 초고베타
        mk(1.6, 0.0),     # 4 테마 무관 · 고베타
    ])
    return R, mkt


def test_raw_correlation_lets_high_beta_strangers_in():
    """원시 상관에서는 테마 무관 고베타 종목도 꽤 높게 나온다(= 이 페이지의 문제의식)."""
    R, _ = _theme_world()
    C = correl.corr_matrix(R)
    assert C[0, 3] > 0.2, "고베타 무관 종목이 원시로는 무시 못 할 상관을 갖는다"


def test_residual_correlation_ranks_theme_mates_first():
    R, mkt = _theme_world()
    E = correl.residualize(R, mkt)
    C = correl.corr_matrix(E)
    order = np.argsort(-np.where(np.arange(5) == 0, -9, C[0]))
    assert set(order[:2]) == {1, 2}, f"잔차 상위 2개가 테마 동료가 아니다: {order[:3]}"
    # 무관 종목은 잔차에서 0 부근으로 내려앉는다.
    assert abs(C[0, 3]) < 0.15 and abs(C[0, 4]) < 0.15


def test_residual_widens_the_gap_between_theme_mates_and_strangers():
    """잔차가 하는 일은 테마 동료의 값을 올리는 게 아니라, 무관 종목을 떨어뜨리는 것.

    시장 성분은 테마 동료에게도 들어 있어서 그걸 빼면 동료의 절대값도 조금
    내려간다(0.69 → 0.67). 요점은 **격차**다 — 테마 동료 중 가장 낮은 값과
    무관 종목 중 가장 높은 값의 차이가 벌어져야 정렬했을 때 섞이지 않는다.
    """
    R, mkt = _theme_world()
    raw = correl.corr_matrix(R)
    res = correl.corr_matrix(correl.residualize(R, mkt))

    gap = lambda C: min(C[0, 1], C[0, 2]) - max(C[0, 3], C[0, 4])
    assert gap(res) > gap(raw) + 0.15, (
        f"잔차가 테마/무관을 더 벌려 주지 못했다 (원시 {gap(raw):.2f}, 잔차 {gap(res):.2f})")


# ------------------------------------------------------------ 이웃 추리기
def test_build_pairs_shape_and_self_exclusion():
    cu = load_builder()
    R, mkt = _theme_world(seed=9, T=300)
    E = correl.residualize(R, mkt)
    pairs = cu.build_pairs(["A", "B", "C", "D", "E"], R, E)

    assert len(pairs) == 5
    for i, row in enumerate(pairs):
        assert all(p[0] != i for p in row), "자기 자신은 이웃에 들어가면 안 된다"
        for p in row:
            assert len(p) == 1 + 2 * len(correl.WINDOWS)   # [j] + 원시3 + 잔차3
            for v in p[1:]:
                assert v is None or -100 <= v <= 100        # ×100 정수로 저장


def test_build_pairs_orders_theme_mates_first():
    cu = load_builder()
    R, mkt = _theme_world(seed=11, T=300)
    pairs = cu.build_pairs(list("ABCDE"), R, correl.residualize(R, mkt))
    assert {p[0] for p in pairs[0][:2]} == {1, 2}


def test_build_pairs_keeps_hedge_candidates():
    """음의 상관(헤지 후보)도 이웃에 남아야 정렬로 찾을 수 있다."""
    cu = load_builder()
    rng = np.random.default_rng(13)
    T = 300
    base = rng.normal(0, 0.02, T)
    R = np.vstack([base, -base + rng.normal(0, 0.002, T)] +
                  [rng.normal(0, 0.02, T) for _ in range(4)])
    mkt = np.zeros(T)
    pairs = cu.build_pairs(list("ABCDEF"), R, R)
    assert 1 in {p[0] for p in pairs[0]}, "정반대로 움직이는 종목이 빠졌다"


# ---------------------------------------------------------------- 유동성
def test_liquid_columns_filters_thin_and_cheap_names():
    cu = load_builder()
    pd = pytest.importorskip("pandas")
    idx = pd.bdate_range("2026-01-01", periods=200)
    close = pd.DataFrame({
        "GOOD": np.linspace(50, 60, 200),
        "CHEAP": np.linspace(1, 2, 200),          # 가격 미달
        "THIN": np.linspace(50, 60, 200),         # 거래대금 미달
        "NEW": [np.nan] * 150 + list(np.linspace(50, 55, 50)),   # 관측일 부족
    }, index=idx)
    vol = pd.DataFrame({"GOOD": 1e6, "CHEAP": 1e7, "THIN": 1e3, "NEW": 1e6}, index=idx)
    keep = cu.liquid_columns(close, close * vol, min_dollar_vol_m=10.0)
    assert keep == ["GOOD"]


# ------------------------------------------------------------------ 뷰
@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    path = tmp_path / "correl.json"
    path.write_text(json.dumps({
        "updated": "2026-09-13T21:40:00+00:00", "asof": "2026-09-11",
        "windows": list(correl.WINDOWS),
        "tickers": ["AAA", "BBB", "CCC"],
        "meta": [["A Corp", "Technology", "Software", 120, 50000, 300],
                 ["B Inc", "Utilities", "Power", 80, 12000, 90],
                 ["C Ltd", "Energy", "Oil", 150, 8000, 45]],
        "neighbors": [[[1, 70, 65, 60, 55, 50, 45], [2, -30, -25, -20, -40, -35, -30]],
                      [], []],
    }), encoding="utf-8")
    monkeypatch.setattr(correl, "DATA_FILE", str(path))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    return path


def test_expand_reads_the_compact_format(snapshot):
    v = correl.get_correl("aaa")          # 소문자도 받아야 한다
    assert v["ticker"] == "AAA" and v["count"] == 2
    first = v["rows"][0]
    assert first["ticker"] == "BBB" and first["sector"] == "Utilities"
    assert first["raw20"] == pytest.approx(0.70)
    assert first["res120"] == pytest.approx(0.45)
    assert first["beta"] == pytest.approx(0.80)
    assert first["market_cap"] == pytest.approx(12000e6)
    # 헤지 후보(음수)도 그대로 실린다.
    assert v["rows"][1]["raw20"] == pytest.approx(-0.30)


def test_unknown_ticker_is_a_clear_message(snapshot):
    v = correl.get_correl("ZZZZ")
    assert v["rows"] == [] and "유니버스" in v["error"]


def test_missing_file_is_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(correl, "DATA_FILE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    assert correl.get_correl("AAA")["rows"] == []
    assert correl.get_universe()["count"] == 0


def test_corrupt_file_is_not_an_exception(tmp_path, monkeypatch):
    bad = tmp_path / "correl.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(correl, "DATA_FILE", str(bad))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    assert correl.get_correl("AAA")["rows"] == []


def test_universe_lists_tickers_and_names(snapshot):
    u = correl.get_universe()
    assert u["count"] == 3 and u["tickers"][0] == "AAA" and u["names"][1] == "B Inc"


def test_schema_matches_window_count():
    """저장 포맷의 열 수와 WINDOWS 가 어긋나면 화면이 조용히 엉뚱한 값을 읽는다."""
    assert correl.PAIR_SCHEMA == ["j", "raw20", "raw50", "raw120",
                                  "res20", "res50", "res120"]
    assert len(correl.PAIR_SCHEMA) == 1 + 2 * len(correl.WINDOWS)
    assert len(correl.META_SCHEMA) == 6


# ------------------------------------------- 반쪽 스냅샷 방지 (레이트 리밋)
# 첫 실전 실행에서 Yahoo 가 YFRateLimitError 를 뿌려 NVDA·MSFT·TSLA 를 포함해
# 수천 종목이 빠졌는데도 1,441종목짜리 결과가 조용히 커밋됐다. 사용자는
# "NVDA 가 왜 없지?"만 보게 된다. 그 조용한 실패를 여기서 막는다.
def test_anchor_check_flags_a_rate_limited_download():
    cu = load_builder()
    pd = pytest.importorskip("pandas")
    idx = pd.bdate_range("2026-01-01", periods=200)

    full = pd.DataFrame({t: np.linspace(10, 20, 200) for t in cu.ANCHORS}, index=idx)
    assert cu.missing_anchors(full) == []

    # 대형주 절반이 빠진 상황 — 레이트 리밋의 전형적인 모습
    half = full[cu.ANCHORS[:len(cu.ANCHORS) // 2]]
    assert len(cu.missing_anchors(half)) > cu.MAX_MISSING_ANCHORS


def test_anchor_check_treats_all_nan_column_as_missing():
    """yfinance 는 실패해도 예외 대신 빈 열을 준다 — 열이 있다고 받은 게 아니다."""
    cu = load_builder()
    pd = pytest.importorskip("pandas")
    idx = pd.bdate_range("2026-01-01", periods=50)
    df = pd.DataFrame({t: np.full(50, np.nan) for t in cu.ANCHORS}, index=idx)
    df["SPY"] = np.linspace(10, 20, 50)
    gone = cu.missing_anchors(df)
    assert "SPY" not in gone and "NVDA" in gone


def test_batch_settings_stay_conservative():
    """배치를 다시 키우면 같은 사고가 난다 — 값 자체를 고정해 둔다."""
    cu = load_builder()
    assert cu.BATCH <= 200, "Yahoo 레이트 리밋에 걸린 크기(400)로 되돌아갔다"
    assert cu.BATCH_SLEEP > 0 and cu.RETRY_ROUNDS >= 2
