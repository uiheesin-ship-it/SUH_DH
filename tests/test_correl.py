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


def _crowded_world(seed=21, N=300, T=260):
    """주인공 하나 + 진짜 테마 동료 4 + 정반대 1 + 무관한 잡음 다수.

    무관한 종목을 많이 깔아 두는 게 핵심이다 — 한 기간만 보고 고르면 그중
    누군가가 우연히 상위권에 앉는다(실제 스냅샷에서 NVDA 의 50일 잔차 상위가
    유조선·석유주로 찼다). 세 기간을 모두 요구하면 그 우연이 걸러져야 한다.
    """
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0, 0.01, T)
    theme = rng.normal(0, 0.012, T)
    rows = [1.5 * mkt + 1.0 * theme + rng.normal(0, 0.008, T)]
    rows += [1.2 * mkt + 0.9 * theme + rng.normal(0, 0.012, T) for _ in range(4)]
    rows += [-1.2 * mkt - 0.9 * theme + rng.normal(0, 0.008, T)]
    rows += [rng.normal(0, 0.02, T) for _ in range(N - 6)]
    return np.vstack(rows), mkt


def test_neighbors_reserve_room_for_hedges():
    """동행 후보가 넘쳐도 헤지 자리는 남아 있어야 한다.

    첫 스냅샷은 후보를 잔차 내림차순으로 한 번에 잘라서, 이웃이 꽉 찬 종목의
    68%가 음의 상관 이웃을 하나도 갖지 못했다 — 헤지 탭이 통째로 죽은 셈이다.
    """
    cu = load_builder()
    R, mkt = _crowded_world()
    pairs = cu.build_pairs([f"T{i}" for i in range(len(R))], R,
                           correl.residualize(R, mkt))
    row = pairs[0]
    assert len(row) == cu.MAX_NEIGHBORS
    negatives = [p for p in row if p[2] is not None and p[2] < 0]
    assert negatives, "동행 후보에 밀려 음의 상관 이웃이 전부 잘렸다"
    assert 5 in {p[0] for p in row}, "정반대로 움직이는 종목이 헤지 자리에 없다"


def test_theme_mates_beat_lucky_strangers_across_windows():
    """세 기간 잔차의 최솟값(동행 점수)으로 줄을 세우면 진짜 동료가 위로 온다.

    상위권이 무관한 종목에게 넘어가지 않는 것이 요점이다. 대신 세 기간 중
    하나라도 흔들린 동료는 같이 내려간다(엄격한 기준의 대가) — 그 종목은
    화면에서 해당 기간 열로 정렬하면 여전히 찾을 수 있다.
    """
    cu = load_builder()
    MATES = {1, 2, 3, 4}
    R, mkt = _crowded_world()
    pairs = cu.build_pairs([f"T{i}" for i in range(len(R))], R,
                           correl.residualize(R, mkt))

    def score(p):
        v = p[4:4 + len(correl.WINDOWS)]
        return -999 if any(x is None for x in v) else min(v)

    ranked = sorted(pairs[0], key=score, reverse=True)
    top3 = {p[0] for p in ranked[:3]}
    assert top3 <= MATES, f"상위권에 무관한 종목 {top3 - MATES} 가 끼었다"

    # 남은 무관한 종목 중 가장 운 좋은 것보다, 살아남은 동료가 확실히 위에 있어야.
    best_stranger = max(score(p) for p in pairs[0] if p[0] not in MATES)
    assert min(score(p) for p in ranked[:3]) > best_stranger + 20, (
        f"동료와 무관한 종목의 간격이 너무 좁다 (무관 최고 {best_stranger})")


def _sector_world(seed=3, N=600, T=260, n_sectors=4):
    """섹터 4개가 각각 강하게 동행하는 세계 — 진짜 구조가 잔뜩 있는 유니버스."""
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0, 0.01, T)
    secs = [rng.normal(0, 0.012, T) for _ in range(n_sectors)]
    R = np.vstack([1.1 * mkt + 0.9 * secs[i % n_sectors] + rng.normal(0, 0.012, T)
                   for i in range(N)])
    return R, mkt


def test_noise_line_measures_luck_not_real_structure():
    """잡음선은 '진짜 쌍의 상위권'이 아니라 '우연의 상한'이어야 한다.

    처음엔 무작위 쌍의 상관을 그냥 쟀는데, 무작위로 고른 두 종목도 같은 섹터면
    진짜로 같이 움직인다 — 그래서 50일 선이 +0.58 로 나왔고 JPM 의 은행 동료가
    전부 잡음으로 찍혔다. 시간축을 어긋나게 돌려서 재야 우연만 남는다.
    """
    cu = load_builder()
    R, mkt = _sector_world()
    E = correl.residualize(R, mkt)
    Z, ok = correl.standardized(E, window=50)

    line = cu.noise_line(Z, ok, universe=len(R), seed=1)
    M = Z @ Z.T
    np.fill_diagonal(M, np.nan)
    real_top = float(np.nanquantile(np.abs(M), 0.99))
    assert line is not None
    assert line < real_top * 0.9, (
        f"잡음선({line})이 진짜 쌍의 상위권({real_top})까지 먹었다")

    # 이론값(독립 두 계열의 상관 표준오차 1/√(T-1) × 다중비교 z≈3.3)과 같은 자리.
    assert 0.5 / np.sqrt(49) < line < 6.0 / np.sqrt(49), line


def test_noise_line_rises_as_the_window_shortens():
    """창이 짧을수록 우연히 큰 값이 나온다 — 선도 같이 올라가야 한다."""
    cu = load_builder()
    R, mkt = _sector_world()
    E = correl.residualize(R, mkt)
    lines = []
    for w in correl.WINDOWS:
        Z, ok = correl.standardized(E, window=w)
        lines.append(cu.noise_line(Z, ok, universe=len(R), seed=1))
    assert lines == sorted(lines, reverse=True), dict(zip(correl.WINDOWS, lines))


def test_meta_row_survives_an_old_snapshot_without_etf_flag():
    """is_etf 가 없던 스냅샷을 읽어도 화면이 깨지지 않아야 한다."""
    old = ["Acme Corp", "Technology", "Semis", 150, 1000, 30]   # 6칸(구 포맷)
    got = correl._meta_at([old], 0)
    assert len(got) == len(correl.META_SCHEMA)
    assert got[:6] == old and got[6] == 0


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
    assert len(correl.META_SCHEMA) == 7
    assert correl.META_SCHEMA[-1] == "is_etf"


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


# --------------------------------------------- 메모리 경로 (standardized)
# 쌍마다 결측을 따지는 corr_matrix 는 중간 행렬을 9개 만들어 결과의 9배를 쓴다
# (3,000종목에서 660MB). 창별로 표준화해 두면 상관이 Z@Z.T 한 번이라 37MB 다.
# 값이 어긋나면 화면 숫자가 조용히 달라지므로 두 경로가 같은지 고정한다.
def test_standardized_path_matches_corrcoef():
    X = np.random.default_rng(21).normal(0, 1, (40, 200))
    Z, ok = correl.standardized(X, window=120)
    assert ok.all()
    assert (Z @ Z.T) == pytest.approx(np.corrcoef(X[:, -120:]), abs=1e-4)


def test_standardized_excludes_rows_with_gaps_in_the_window():
    """창 안에 결측이 있는 종목은 그 창에서 값을 주지 않는다."""
    X = np.random.default_rng(22).normal(0, 1, (5, 200))
    X[2, -5] = np.nan
    Z, ok = correl.standardized(X, window=120)
    assert ok[0] and not ok[2]
    v = correl.corr_rows(Z, ok, 0, np.array([1, 2, 3]))
    assert np.isfinite(v[0]) and np.isnan(v[1]) and np.isfinite(v[2])


def test_corr_rows_needs_no_full_matrix():
    """후보가 정해진 뒤에는 행렬 없이 필요한 쌍만 구한다 — 값은 같아야 한다."""
    X = np.random.default_rng(23).normal(0, 1, (30, 200))
    Z, ok = correl.standardized(X, window=60)
    full = Z @ Z.T
    cols = np.array([3, 7, 11])
    assert correl.corr_rows(Z, ok, 5, cols) == pytest.approx(full[5, cols], abs=1e-5)


def test_build_pairs_survives_a_single_missing_day():
    """하루 결측으로 이웃이 통째로 사라지면 안 된다.

    실측에서 T0 의 최근 창에 하루 NaN 을 넣었더니 이웃이 60개 → 0개가 됐다.
    수집기는 가격 단계에서 ffill 로 메우지만, 그래도 결측이 남은 종목이 다른
    종목들의 이웃 목록까지 망가뜨리지는 않아야 한다.
    """
    cu = load_builder()
    rng = np.random.default_rng(24)
    N, T = 40, 200
    mkt = rng.normal(0, 0.01, T)
    theme = rng.normal(0, 0.015, T)
    R = np.vstack([rng.uniform(.5, 1.5) * mkt + (0.9 if i < 10 else 0.0) * theme
                   + rng.normal(0, 0.012, T) for i in range(N)])
    R[0, -7] = np.nan                      # 0번만 최근 창에 구멍
    pairs = cu.build_pairs([f"T{i}" for i in range(N)], R, correl.residualize(R, mkt))
    assert len(pairs) == N
    # 0번은 그 창에서 빠질 수 있어도, 나머지는 정상적으로 이웃을 갖는다.
    assert all(len(pairs[i]) > 0 for i in range(1, N))


def test_etf_rows_are_labelled_even_in_an_old_snapshot():
    """ETF 는 섹터가 전부 Financial 로 붙어 나온다 — 섹터 자리를 ETF 로 바꿔 준다.

    성장주 ETF 는 그 종목 자체를 담고 있어 상관이 높은 게 당연하다(테마 동료가
    아니라 자기 자신이다). 첫 스냅샷에서 NVDA 의 잔차 상위 3개가 전부 ETF 였다.
    """
    data = {
        "tickers": ["NVDA", "FBCG"],
        # FBCG 는 is_etf 칸이 없던 옛 포맷 — 산업명으로 알아봐야 한다.
        "meta": [["NVIDIA Corp", "Technology", "Semiconductors", 192, 5122890, 27677],
                 ["Fidelity Blue Chip Growth ETF", "Financial",
                  "Exchange Traded Fund", 150, 0, 36]],
        "neighbors": [[[1, 71, 71, 71, 60, 60, 60]], [[0, 71, 71, 71, 60, 60, 60]]],
    }
    view = correl.expand(data, "NVDA")
    assert view["rows"][0]["is_etf"] is True
    assert view["rows"][0]["sector"] == "ETF"
    assert view["self"]["is_etf"] is False
    assert view["self"]["sector"] == "Technology"


# ------------------------------------------- 유니버스에서 종목이 조용히 빠지는 문제
# 평평 스크리너는 Finviz 결과를 3,000종목으로 **솎아내서** 쓴다(시총 구간이 고르게
# 남도록 일정 간격으로 버린다). 평평 쪽은 표본만 있으면 되니 괜찮지만 상관 분석에서는
# 사용자가 찾는 바로 그 종목이 없어진다 — APPS(시총 $1.4B, 거래대금 $29M)가 기준을
# 다 넘고도 이렇게 빠졌다. 여기서는 솎아내기를 끄고 유동성 기준만으로 거른다.
def test_correl_asks_for_an_unsampled_universe():
    cu = load_builder()
    base = {"universe": {"max_candidates": 3000, "max_etf_candidates": 700,
                         "include_etf": True, "include_reit": False},
            "min_market_cap": 300_000_000, "min_price": 1.0}
    cfg = cu.unsampled_flat_config(base)

    assert cfg["universe"]["max_candidates"] == 0, "후보 솎아내기가 여전히 켜져 있다"
    assert cfg["universe"]["max_etf_candidates"] == 0
    # 나머지 설정(품질 기준)은 평평 스크리너 것을 그대로 따라야 한다.
    assert cfg["min_market_cap"] == 300_000_000
    assert cfg["universe"]["include_etf"] is True
    # load() 는 공유 캐시를 돌려주므로 원본을 건드리면 평평 스크리너가 망가진다.
    assert base["universe"]["max_candidates"] == 3000, "원본 설정을 수정해 버렸다"


def test_flat_sampler_is_what_drops_qualifying_names():
    """솎아내기가 실제로 기준 통과 종목을 버린다는 걸 못 박아 둔다.

    이 동작이 사라지거나 바뀌면 위 우회가 필요 없어지므로, 그때 이 테스트가
    먼저 깨져서 알려 준다.
    """
    universe = pytest.importorskip("app.flat.universe")
    rows = [{"ticker": f"T{i}", "market_cap": 1e9 - i} for i in range(100)]
    kept = {r["ticker"] for r in universe._sample(list(rows), 60)}
    assert len(kept) == 60
    assert len(kept) < len(rows), "솎아내기가 아무것도 안 버렸다"
    # 0 을 주면 전부 남는다 — 우리가 쓰는 우회가 이것이다.
    assert len(universe._sample(list(rows), 0)) == 100


def test_flat_and_turnaround_scan_the_whole_universe():
    """평평·턴어라운드는 후보를 솎아내지 않아야 한다(0 = 전수).

    솎아내기는 기준을 다 넘는 종목을 임의로 버린다 — 실측으로 평평은 7,927 중
    4,227개(53%), 턴어라운드는 3,247 중 247개가 그렇게 빠지고 있었다. 상관
    프로그램이 APPS 를 못 찾은 것도 이 때문이었다.
    """
    from app.flat import config as flat_cfg
    from app.turnaround import config as turn_cfg

    flat = flat_cfg.load()["universe"]
    assert flat["max_candidates"] == 0, "평평 유니버스가 다시 솎아내고 있다"
    assert flat["max_etf_candidates"] == 0
    assert turn_cfg.load()["universe"]["max_candidates"] == 0, (
        "턴어라운드 유니버스가 다시 솎아내고 있다")
