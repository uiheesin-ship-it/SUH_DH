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


# ------------------------------------------- 핵심 주장: 잔차가 테마를 고른다
def corr_all(M, window=None):
    """실제 코드가 쓰는 경로로 상관행렬을 만든다(standardized + 내적)."""
    Z, ok = correl.standardized(M, window=window or M.shape[1])
    C = np.asarray(Z @ Z.T, dtype=np.float64)
    C[~ok, :] = np.nan
    C[:, ~ok] = np.nan
    return np.clip(C, -1.0, 1.0)


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
    C = corr_all(R)
    assert C[0, 3] > 0.2, "고베타 무관 종목이 원시로는 무시 못 할 상관을 갖는다"


def test_residual_correlation_ranks_theme_mates_first():
    R, mkt = _theme_world()
    E = correl.residualize(R, mkt)
    C = corr_all(E)
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
    raw = corr_all(R)
    res = corr_all(correl.residualize(R, mkt))

    gap = lambda C: min(C[0, 1], C[0, 2]) - max(C[0, 3], C[0, 4])
    assert gap(res) > gap(raw) + 0.15, (
        f"잔차가 테마/무관을 더 벌려 주지 못했다 (원시 {gap(raw):.2f}, 잔차 {gap(res):.2f})")


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


# ------------------------------------------------- ETF 가 이웃 정원을 먹는 문제
def _etf_heavy_world(seed=4, N=300, T=260, n_mates=6, n_etf=40):
    """주인공 + 진짜 동료 몇 + **그 주인공을 담은 ETF** 잔뜩 + 잡음.

    ETF 는 주인공 지분을 들고 있어 상관이 0.9를 넘는 게 당연하다. 실제 스냅샷도
    이렇게 생겼다 — 유니버스 상한을 풀어 ETF 가 105개에서 743개로 늘자 MU 의
    이웃 60개 중 45개가 ETF 가 됐다(실제 종목 15개).
    """
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0, 0.01, T)
    theme = rng.normal(0, 0.012, T)
    hero = 1.5 * mkt + 1.0 * theme + rng.normal(0, 0.008, T)
    rows = [hero]
    rows += [1.2 * mkt + 0.9 * theme + rng.normal(0, 0.012, T) for _ in range(n_mates)]
    rows += [0.9 * hero + rng.normal(0, 0.004, T) for _ in range(n_etf)]
    rows += [rng.normal(0, 0.02, T) for _ in range(N - 1 - n_mates - n_etf)]
    is_etf = [False] * (1 + n_mates) + [True] * n_etf + [False] * (N - 1 - n_mates - n_etf)
    return np.vstack(rows), mkt, is_etf, set(range(1, 1 + n_mates))



# =================================================== 수익률 행렬 저장 포맷
# 예전엔 상관을 미리 구해 종목당 이웃 60개만 저장했다. 그러면 파일이 5.0MB 인데
# 이웃은 60개뿐이고, 정원을 헤지·ETF 로 어떻게 나눌지 계속 손보게 된다 — ETF 가
# 늘자 MU 의 이웃 60개 중 45개가 ETF 로 차서 실제 종목이 15개만 남은 적도 있다.
# 지금은 원본(수익률 130일치, int16)을 싣고 상관은 조회할 때 계산한다: 0.8MB 에
# 이웃은 전부. 아래 테스트는 그 포맷과 계산이 맞는지를 본다.
def _snapshot(R, mkt, is_etf=None, industries=None):
    """합성 수익률로 실제와 같은 모양의 스냅샷을 만든다."""
    beta = correl.market_betas(R, mkt)
    days = min(correl.STORE_DAYS, R.shape[1])
    n = len(R)
    return {
        "tickers": [f"T{i}" for i in range(n)],
        "meta": [["회사" + str(i),
                  "Technology",
                  (industries[i] if industries else "Semis"),
                  int(round(beta[i] * 100)), 1000, 50,
                  int(bool(is_etf[i])) if is_etf else 0] for i in range(n)],
        "windows": list(correl.WINDOWS),
        "days": days, "scale": correl.RETURN_SCALE,
        "market_returns": correl.encode_returns(mkt[None, -days:]),
        "returns": correl.encode_returns(R[:, -days:]),
    }


def test_returns_round_trip_keeps_gaps_and_clips_extremes():
    R = np.array([[0.01, -0.02, np.nan, 3.0, -9.9]])
    back = correl.decode_returns(correl.encode_returns(R), 1, 5)
    assert back[0, 0] == pytest.approx(0.01)
    assert back[0, 1] == pytest.approx(-0.02)
    assert np.isnan(back[0, 2]), "결측이 0으로 바뀌면 그 날 '안 움직였다'가 된다"
    # int16 은 ±3.2767 까지만 담는다. 잘리더라도 결측(NaN)이 되면 안 된다.
    assert np.isfinite(back[0, 3]) and np.isfinite(back[0, 4])


def test_every_ticker_in_the_universe_is_a_neighbour():
    """이웃 수 상한이 없다 — 유니버스 전체가 표에 들어온다."""
    rng = np.random.default_rng(2)
    R = rng.normal(0, 0.02, (120, 150))
    view = correl.expand(_snapshot(R, rng.normal(0, 0.01, 150)), "T0")
    assert view["count"] == len(R) - 1, "이웃이 잘렸다"
    assert all(r["ticker"] != "T0" for r in view["rows"]), "자기 자신이 들어갔다"


def test_correlations_match_numpy():
    """저장·복원·표준화를 거친 값이 numpy 상관과 같아야 한다(양자화 오차 안)."""
    rng = np.random.default_rng(3)
    mkt = rng.normal(0, 0.01, 150)
    R = np.vstack([1.2 * mkt + rng.normal(0, 0.012, 150) for _ in range(40)])
    view = correl.expand(_snapshot(R, mkt), "T0")
    got = {r["ticker"]: r["raw50"] for r in view["rows"]}

    X = R[:, -50:]
    Xc = X - X.mean(axis=1, keepdims=True)
    truth = (Xc @ Xc[0]) / np.sqrt((Xc ** 2).sum(axis=1) * (Xc[0] ** 2).sum())
    worst = max(abs(got[f"T{j}"] - truth[j]) for j in range(1, len(R)))
    # 화면은 소수 2자리로 보여 준다 — 그보다 훨씬 작아야 한다.
    assert worst < 0.005, f"양자화 오차가 표시 자릿수를 흔든다: {worst}"


def test_residual_uses_the_stored_beta():
    """베타는 수집 때 1년치로 구한 값을 쓴다 — 130일로 다시 구하면 답이 달라진다."""
    rng = np.random.default_rng(5)
    mkt = rng.normal(0, 0.01, 150)
    R = np.vstack([2.0 * mkt + rng.normal(0, 0.005, 150) for _ in range(30)])
    snap = _snapshot(R, mkt)
    real_beta = snap["meta"][0][3]
    assert real_beta > 150, f"이 세계의 베타는 2에 가까워야 한다: {real_beta / 100}"

    # 잔차 상관은 **양쪽** 베타에 달려 있다. 두 종목의 베타를 0 으로 두면
    # 잔차 = 원시가 되어야 한다 — 저장된 값을 쓰고 있다는 증거다.
    snap["meta"][0][3] = snap["meta"][1][3] = 0
    row = next(r for r in correl.expand(snap, "T0")["rows"] if r["ticker"] == "T1")
    assert abs(row["res50"] - row["raw50"]) < 1e-6, (
        "베타 0 인데 잔차가 원시와 다르다 — 저장된 베타를 안 쓰고 계산하고 있다")

    # 반대로 진짜 베타를 되돌리면 시장 성분이 빠져 상관이 눈에 띄게 낮아진다.
    snap["meta"][0][3] = snap["meta"][1][3] = real_beta
    row2 = next(r for r in correl.expand(snap, "T0")["rows"] if r["ticker"] == "T1")
    assert row2["res50"] < row2["raw50"] - 0.3, (row2["res50"], row2["raw50"])


def test_hedge_candidates_need_no_reserved_slots():
    """정반대로 움직이는 종목이 그냥 들어 있다 — 자리를 따로 뗄 이유가 없다."""
    rng = np.random.default_rng(7)
    base = rng.normal(0, 0.02, 150)
    R = np.vstack([base, -base + rng.normal(0, 0.002, 150)]
                  + [rng.normal(0, 0.02, 150) for _ in range(50)])
    view = correl.expand(_snapshot(R, np.zeros(150)), "T0")
    opposite = next(r for r in view["rows"] if r["ticker"] == "T1")
    assert opposite["raw50"] < -0.8, opposite["raw50"]


def test_an_etf_flood_cannot_crowd_out_real_mates():
    """ETF 가 아무리 많아도 진짜 동료가 밀려나지 않는다 — 정원이 없으니까.

    이웃 60개 시절엔 ETF 743개가 늘자 MU 의 자리 45개를 먹어 실제 종목이 15개만
    남았다. 정원과 후보 수집을 ETF/실제 종목으로 나눠 막아야 했던 문제다.
    """
    rng = np.random.default_rng(11)
    mkt = rng.normal(0, 0.01, 150)
    theme = rng.normal(0, 0.012, 150)
    hero = 1.5 * mkt + theme + rng.normal(0, 0.008, 150)
    mates = [1.2 * mkt + 0.9 * theme + rng.normal(0, 0.012, 150) for _ in range(6)]
    etfs = [0.9 * hero + rng.normal(0, 0.004, 150) for _ in range(200)]
    R = np.vstack([hero] + mates + etfs)
    is_etf = [0] * 7 + [1] * 200

    view = correl.expand(_snapshot(R, mkt, is_etf=is_etf), "T0")
    names = {r["ticker"] for r in view["rows"]}
    assert {f"T{i}" for i in range(1, 7)} <= names, "진짜 동료가 빠졌다"
    # 화면의 "ETF 제외" 체크를 흉내 내면 동료가 상위를 차지해야 한다.
    stocks = sorted((r for r in view["rows"] if not r["is_etf"]),
                    key=lambda r: -(r["res50"] or -9))
    assert {r["ticker"] for r in stocks[:6]} == {f"T{i}" for i in range(1, 7)}


def test_a_gap_in_the_window_yields_none_not_a_crash():
    """창 안에 결측이 있는 종목은 그 창에서 값을 안 준다. 남은 종목은 멀쩡해야."""
    rng = np.random.default_rng(13)
    R = rng.normal(0, 0.02, (30, 150))
    R[1, -5] = np.nan                      # T1 만 최근 20일 안에 구멍
    view = correl.expand(_snapshot(R, rng.normal(0, 0.01, 150)), "T0")
    holed = next(r for r in view["rows"] if r["ticker"] == "T1")
    assert holed["raw20"] is None and holed["raw120"] is None
    other = next(r for r in view["rows"] if r["ticker"] == "T2")
    assert other["raw20"] is not None and other["raw120"] is not None


def test_etf_rows_are_labelled_even_without_the_flag():
    """is_etf 를 싣기 전 스냅샷도 산업명으로 알아본다(섹터가 Financial 로 붙는다)."""
    rng = np.random.default_rng(17)
    R = rng.normal(0, 0.02, (5, 150))
    snap = _snapshot(R, rng.normal(0, 0.01, 150),
                     industries=["Semis", "Exchange Traded Fund"] + ["Semis"] * 3)
    snap["meta"][1] = snap["meta"][1][:6]          # 구 포맷(6칸)
    view = correl.expand(snap, "T0")
    etf = next(r for r in view["rows"] if r["ticker"] == "T1")
    assert etf["is_etf"] is True and etf["sector"] == "ETF"
    assert view["self"]["is_etf"] is False
