"""미장 마켓 브레스: 구간 판정 · 채점 · 다이버전스 · 시계열 병합 테스트.

값 자체(시장 데이터)는 검증할 수 없으니, 값을 해석하는 규칙만 고정한다.
여기가 깨지면 화면의 색·점수·경고 문구가 조용히 바뀐 것이다.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app import breadth

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load_fetcher():
    """tools/ 는 패키지가 아니므로 경로로 직접 읽어 온다."""
    spec = importlib.util.spec_from_file_location("breadth_us", TOOLS / "breadth_us.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ 구간 판정
@pytest.mark.parametrize("value,expected", [
    (0, "극단 침체"), (19.9, "극단 침체"),
    (20, "약세"), (39.9, "약세"),
    (40, "중립"), (59.9, "중립"),
    (60, "양호"), (79.9, "양호"),
    (80, "과열"), (100, "과열"),
])
def test_pct_zone_boundaries(value, expected):
    """%>이평선 계열은 20/40/60/80 을 경계로 다섯 구간."""
    label, tone = breadth.zone_of(breadth.BY_KEY["S5FI"], value)
    assert label == expected
    assert tone  # 색키는 항상 따라온다


def test_zone_of_missing_value():
    assert breadth.zone_of(breadth.BY_KEY["S5FI"], None) == (None, None)


def test_every_scored_metric_has_zones():
    """점수에 들어가는 지표는 화면에서 구간 색도 나와야 한다."""
    for m in breadth.METRICS:
        if m.weight > 0:
            assert m.zones, f"{m.key} has weight but no zones"
            assert m.score_at, f"{m.key} has weight but no score_at"


def test_zone_tables_are_ascending_and_open_ended():
    for m in breadth.METRICS:
        if not m.zones:
            continue
        uppers = [u for u, _, _ in m.zones]
        assert uppers[-1] is None, f"{m.key}: 마지막 구간은 무한대여야 한다"
        finite = [u for u in uppers if u is not None]
        assert finite == sorted(finite), f"{m.key}: 구간 상한이 오름차순이 아니다"


# ------------------------------------------------------------ 정규화 채점
def test_sub_score_linear():
    m = breadth.BY_KEY["S5FI"]           # score_at=(0, 100)
    assert breadth.sub_score(m, 0) == 0
    assert breadth.sub_score(m, 50) == 50
    assert breadth.sub_score(m, 100) == 100


def test_sub_score_clamps_outside_range():
    m = breadth.BY_KEY["ADDN"]           # score_at=(-1500, 1500)
    assert breadth.sub_score(m, -9000) == 0
    assert breadth.sub_score(m, 9000) == 100
    assert breadth.sub_score(m, 0) == 50


def test_sub_score_inverted_metric():
    """하이일드 스프레드는 낮을수록 좋다 — score_at 을 (높음, 낮음)으로 뒤집어 표현."""
    m = breadth.BY_KEY["HY_OAS"]         # score_at=(6.0, 2.8)
    assert breadth.sub_score(m, 2.8) == 100
    assert breadth.sub_score(m, 6.0) == 0
    assert breadth.sub_score(m, 2.0) == 100   # 더 낮아도 100 에서 잘린다
    assert 40 < breadth.sub_score(m, 4.4) < 60


def test_sub_score_none_without_scoring_range():
    assert breadth.sub_score(breadth.BY_KEY["NYSI"], 500) is None
    assert breadth.sub_score(breadth.BY_KEY["S5FI"], None) is None


# ------------------------------------------------------------ 종합점수
def test_composite_all_perfect_and_all_zero():
    best = {m.key: m.score_at[1] for m in breadth.METRICS if m.score_at}
    worst = {m.key: m.score_at[0] for m in breadth.METRICS if m.score_at}
    assert breadth.composite(best)["score"] == 100
    assert breadth.composite(worst)["score"] == 0


def test_composite_redistributes_missing_weights():
    """지표 하나만 있어도 그 지표의 점수가 그대로 종합점수가 된다(가중치 재분배)."""
    c = breadth.composite({"S5FI": 70})
    assert c["score"] == 70
    assert c["coverage"] < 100          # 커버리지로 신뢰도를 알린다
    assert [p["key"] for p in c["parts"]] == ["S5FI"]


def test_composite_weighting_favours_s5fi():
    """S5FI 가 가장 무거운 지표 — 같은 점수 차이라도 종합점수를 더 크게 움직인다."""
    base = {"S5FI": 50, "S5TW": 50}
    up_mid = breadth.composite({**base, "S5FI": 90})["score"]
    up_short = breadth.composite({**base, "S5TW": 90})["score"]
    assert up_mid > up_short


def test_composite_empty_is_not_an_error():
    c = breadth.composite({})
    assert c["score"] is None and c["parts"] == [] and c["note"]


@pytest.mark.parametrize("score,regime", [
    (0, "위험"), (29.9, "위험"), (30, "주의"), (44.9, "주의"),
    (45, "중립"), (59.9, "중립"), (60, "양호"), (79.9, "양호"), (80, "과열"),
])
def test_regime_thresholds(score, regime):
    # S5FI 하나만 넣으면 종합점수 == 그 값이므로 경계를 직접 태울 수 있다.
    assert breadth.composite({"S5FI": score})["regime"] == regime


# ------------------------------------------------------------ 다이버전스
def test_bearish_divergence_detected():
    rows = [("2026-01-02", {"SPY_VS_200": 6.0, "S5FI": 38.0})]
    titles = [a["title"] for a in breadth.divergences(rows)]
    assert any("베어리시" in t for t in titles)


def test_no_divergence_when_breadth_confirms():
    rows = [("2026-01-02", {"SPY_VS_200": 6.0, "S5FI": 72.0, "NHNL": 120})]
    assert breadth.divergences(rows) == []


def test_new_low_divergence():
    rows = [("2026-01-02", {"SPY_VS_200": 3.0, "S5FI": 70.0, "NHNL": -80})]
    assert any("신저가" in a["title"] for a in breadth.divergences(rows))


def test_rapid_deterioration_uses_20day_trend():
    rows = [(f"2026-01-{d:02d}", {"S5FI": 70.0 - d, "SPY_VS_200": 2.0})
            for d in range(1, 25)]
    assert any("급속 악화" in a["title"] for a in breadth.divergences(rows))


def test_bottom_reversal_is_flagged_as_good():
    rows = [(f"2026-01-{d:02d}", {"S5TH": 20.0, "S5FI": 20.0 + d})
            for d in range(1, 25)]
    alerts = breadth.divergences(rows)
    assert any(a["level"] == "good" for a in alerts)


def test_divergences_on_empty_series():
    assert breadth.divergences([]) == []


# ------------------------------------------------------------ 뷰 구성
@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    """3일짜리 최소 스냅샷을 파일로 깔고 breadth 가 그걸 읽게 한다."""
    series = {
        "2026-01-05": {"S5FI": 60.0, "S5TH": 55.0, "HY_OAS": 3.0},
        "2026-01-06": {"S5FI": 58.0, "S5TH": 54.0, "HY_OAS": 3.1},
        "2026-01-07": {"S5FI": 52.5, "S5TH": 53.0, "HY_OAS": 3.2},
    }
    path = tmp_path / "breadth_us.json"
    path.write_text(json.dumps({
        "updated": "2026-01-07T21:10:00+00:00",
        "series": series,
        "sources": {"S5FI": "tradingview", "HY_OAS": "fred"},
    }), encoding="utf-8")
    monkeypatch.setattr(breadth, "DATA_FILE", str(path))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    return breadth.get_breadth()


def test_view_reports_latest_session(snapshot):
    assert snapshot["asof"] == "2026-01-07"
    assert snapshot["days"] == 3
    assert snapshot["total"] == len(breadth.METRICS)


def test_view_computes_daily_change(snapshot):
    s5fi = next(m for m in snapshot["metrics"] if m["key"] == "S5FI")
    assert s5fi["value"] == 52.5 and s5fi["prev"] == 58.0
    assert s5fi["change"] == pytest.approx(-5.5)
    assert s5fi["zone"] == "중립"


def test_view_keeps_source_labels(snapshot):
    by = {m["key"]: m for m in snapshot["metrics"]}
    assert by["S5FI"]["source"] == "tradingview"
    assert by["HY_OAS"]["source"] == "fred"
    # 수집되지 않은 지표는 레지스트리의 기본 출처를 그대로 보여준다.
    assert by["VIX"]["source"] == "yahoo"


def test_view_sparkline_skips_missing_values(snapshot):
    vix = next(m for m in snapshot["metrics"] if m["key"] == "VIX")
    assert vix["value"] is None and vix["spark"] == []
    s5fi = next(m for m in snapshot["metrics"] if m["key"] == "S5FI")
    assert [p[0] for p in s5fi["spark"]] == ["2026-01-05", "2026-01-06", "2026-01-07"]


def test_metric_uses_its_own_last_session(tmp_path, monkeypatch):
    """원천마다 마지막 거래일이 다르다 — 하루 늦은 지표를 빈 칸으로 버리지 않는다.

    실제로 ^VIX3M 이 SPY 보다 며칠 일찍 끝나는 바람에 VIX 기간구조가 459일치나
    쌓여 있는데도 카드가 "—" 로 비어 있었다.
    """
    path = tmp_path / "breadth_us.json"
    path.write_text(json.dumps({"series": {
        "2026-01-05": {"S5FI": 60.0, "VIX_TERM": 1.05},
        "2026-01-06": {"S5FI": 58.0, "VIX_TERM": 1.02},
        "2026-01-07": {"S5FI": 52.5},          # VIX_TERM 은 이날 값이 없다
    }}), encoding="utf-8")
    monkeypatch.setattr(breadth, "DATA_FILE", str(path))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    view = breadth.get_breadth()

    by = {m["key"]: m for m in view["metrics"]}
    assert by["VIX_TERM"]["value"] == 1.02            # 마지막으로 있던 값
    assert by["VIX_TERM"]["asof"] == "2026-01-06"     # 그 값이 찍힌 날
    assert by["VIX_TERM"]["stale"] is True            # 기준일보다 오래됐다고 표시
    assert by["VIX_TERM"]["change"] == pytest.approx(-0.03)   # 그 직전 값 대비

    assert by["S5FI"]["asof"] == "2026-01-07" and by["S5FI"]["stale"] is False
    # 뒤처진 지표도 종합점수에 들어간다(빈 칸으로 버리면 커버리지가 깎인다).
    assert "VIX_TERM" in [p["key"] for p in view["composite"]["parts"]]


def test_missing_file_is_a_friendly_empty_view(tmp_path, monkeypatch):
    monkeypatch.setattr(breadth, "DATA_FILE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    view = breadth.get_breadth()
    assert view["count"] == 0
    assert len(view["metrics"]) == len(breadth.METRICS)   # 카드는 자리를 지킨다
    assert view["composite"]["score"] is None
    assert view["notes"]


def test_corrupt_file_does_not_raise(tmp_path, monkeypatch):
    bad = tmp_path / "breadth_us.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(breadth, "DATA_FILE", str(bad))
    monkeypatch.delenv("SUH_DH_DEMO", raising=False)
    assert breadth.get_breadth()["count"] == 0


def test_demo_mode_fills_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(breadth, "DATA_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("SUH_DH_DEMO", "1")
    view = breadth.get_breadth()
    assert view["demo"] is True
    assert view["count"] == len(breadth.METRICS)
    assert view["composite"]["score"] is not None


# ------------------------------------------------------------ 수집기 병합
def test_merge_and_trim():
    breadth_us = load_fetcher()

    series: dict = {}
    breadth_us.merge(series, {"2026-01-05": {"S5FI": 60.0}})
    breadth_us.merge(series, {"2026-01-05": {"S5TH": 55.0}, "2026-01-06": {"S5FI": 58.0}})
    # 같은 날짜에 다른 지표가 들어오면 합쳐지고, 같은 지표는 새 값이 이긴다.
    assert series["2026-01-05"] == {"S5FI": 60.0, "S5TH": 55.0}
    breadth_us.merge(series, {"2026-01-05": {"S5FI": 61.0}})
    assert series["2026-01-05"]["S5FI"] == 61.0

    trimmed = breadth_us.trim({f"2026-{m:02d}-01": {} for m in range(1, 13)}, keep=3)
    assert sorted(trimmed) == ["2026-10-01", "2026-11-01", "2026-12-01"]


def test_merge_ignores_none_values():
    breadth_us = load_fetcher()

    series: dict = {"2026-01-05": {"S5FI": 60.0}}
    breadth_us.merge(series, {"2026-01-05": {"S5FI": None, "S5TH": 50.0}})
    assert series["2026-01-05"] == {"S5FI": 60.0, "S5TH": 50.0}


def test_tv_symbols_cover_the_registry():
    """레지스트리에 TradingView 지표를 추가하면 수집기도 자동으로 따라간다."""
    breadth_us = load_fetcher()

    direct = {m.key: m.symbol for m in breadth.METRICS if m.source == "tradingview"}
    assert "S5FI" in direct and direct["S5FI"] == "INDEX:S5FI"
    # 파생 지표의 원재료는 별도 목록으로 관리된다.
    assert {"MAHN", "MALN", "UVOL", "DVOL"} <= set(breadth_us.TV_RAW)
