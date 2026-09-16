"""Dashboard integration for the Market Regime Lab.

The lab is an ordinary dashboard program now: a static page under
``app/static/regime/`` plus ``/api/regime/*`` endpoints that call the existing
analysis functions. These tests cover the wiring **and** the thing that matters
most — that going through HTTP produces exactly the numbers the analysis
engine produces when called directly.

Run with:  python -m pytest tests/test_regime_dashboard.py -q
"""

import io
import os
from dataclasses import replace
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("plotly")
from fastapi.testclient import TestClient  # noqa: E402

os.environ.setdefault("SUH_DH_DEMO", "1")          # 합성 데이터로 오프라인 실행

from app.main import app  # noqa: E402
from app.regime import similarity  # noqa: E402
from app.regime.config import Params, load_config  # noqa: E402
from app.regime.data import load_market  # noqa: E402
from app.regime.data.sources import synthetic_prices  # noqa: E402
from app.regime.features import build_features  # noqa: E402
from app.regime.forward import analyze as forward_analyze  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
OFFLINE = {"mode": "auto", "offline": True}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def analysis(client):
    res = client.post("/api/regime/analyze", json={"data": OFFLINE, "params": {}})
    assert res.status_code == 200, res.text
    return res.json()


# ---------------- hub + static page (다른 프로그램과 같은 구조) ----------------

def test_hub_card_points_at_the_internal_program():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    card = html[html.index('name: "Market Regime Lab"'):]
    card = card[:card.index("},")]
    assert 'market: "us"' in card and 'group: "other"' in card
    assert 'href: "regime/"' in card          # 내부 경로 (외부 URL 아님)
    assert "onrender.com" not in card


def test_static_program_has_the_dashboard_shape(client):
    body = client.get("/regime/").text
    assert 'class="topbar"' in body and 'href="../"' in body     # 공통 헤더
    assert "cdn.plot.ly" in body                                  # 다른 프로그램과 같은 차트 라이브러리
    for asset in ("style.css", "app.js", "config.js"):
        assert client.get(f"/regime/{asset}").status_code == 200
    # 분석 UI 가 즉시 있는지 (iframe/외부 서비스로 넘기지 않는다)
    assert "<iframe" not in body
    assert "onrender.com" not in body
    for marker in ('id="run-btn"', 'id="params"', 'id="tabs"', 'data-tab="state"',
                   'data-tab="audit"', 'data-tab="validation"', 'class="file"'):
        assert marker in body, marker

    js = client.get("/regime/app.js").text
    assert "/api/regime/analyze" in js and "SUH_DH_API_BASE" in js
    # 외부 서비스로 나가거나 iframe 으로 떠넘기지 않는다
    assert "onrender" not in js.lower() and "<iframe" not in js.lower()


def test_no_streamlit_proxy_endpoints_remain(client):
    assert client.get("/api/regime/status").status_code == 404
    assert not (ROOT / "app" / "regime_host.py").exists()


# ---------------- API ----------------

def test_defaults_exposes_config_and_feature_descriptors(client):
    body = client.get("/api/regime/defaults").json()
    assert body["config"]["market"]["ticker"] == "^IXIC"
    keys = {f["key"] for f in body["features"]}
    assert {"px_vs_sma50", "dd_52w", "dd_count", "vol_realized"} <= keys
    groups = {f["group"] for f in body["features"]}
    assert {"Trend", "Momentum", "Volatility", "Distribution"} <= groups


def test_analyze_returns_everything_the_page_needs(analysis):
    j = analysis
    assert j["ticker"] == "^IXIC"
    assert j["matches"]["rows"] and j["match_dates"]
    assert j["sources"]["rows"] and j["quality"]["status"] in ("ok", "warn", "fail")
    assert [g["group"] for g in j["state"]["groups"]][:2] == ["Trend", "Momentum"]
    assert j["forward"]["horizons"] == [5, 20, 60, 120]
    for name in ("price", "forward_bar", "distribution"):
        fig = j["charts"][name]
        assert fig["data"] and "layout" in fig          # Plotly figure JSON


# ---------------- regression: HTTP == 엔진 직접 호출 ----------------

def test_api_numbers_match_the_engine_called_directly(analysis):
    """같은 입력 → 같은 결과. 어댑터가 숫자를 바꾸지 않는지 확인한다."""
    params = Params.from_config(load_config())
    market = load_market(params.ticker, params.years, params.exogenous,
                         source="synthetic", use_cache=False)
    fs = build_features(market, params)
    valid = fs.valid_mask()
    anchor = market.calendar[valid.reindex(market.calendar).fillna(False)].max()
    scored, info = similarity.candidate_scores(fs.values, anchor, params.similarity.weights,
                                               params.similarity, valid=valid, max_horizon=120)
    matches = similarity.decluster(scored, market.calendar, params.similarity.min_gap,
                                   pick=params.similarity.episode_pick,
                                   top_n=params.similarity.top_n)
    results = forward_analyze(market.prices["close"], matches, params.forward,
                              baseline_mask=valid, min_gap=params.similarity.min_gap,
                              index=market.calendar, episode_pick=params.similarity.episode_pick)

    assert analysis["anchor"] == str(anchor.date())
    assert analysis["candidates"] == len(scored)
    assert analysis["used_features"] == info.used_keys
    assert analysis["match_dates"] == [str(d.date()) for d in matches.index]

    by_h = {row["horizon"]: row for row in analysis["forward"]["rows"]}
    for h, res in results.items():
        api_m, api_b = by_h[h]["matched"], by_h[h]["baseline"]
        for field in ("n", "mean", "median", "win_rate", "p25", "p75", "min", "max", "std", "mdd_mean"):
            assert api_m[field] == pytest.approx(res.matched[field], rel=1e-12), f"matched {field} h={h}"
            assert api_b[field] == pytest.approx(res.baseline[field], rel=1e-12), f"baseline {field} h={h}"
        assert api_m["ci_mean"] == pytest.approx(list(res.matched["ci_mean"]), rel=1e-12)
        assert api_b["ci_mean"] == pytest.approx(list(res.baseline["ci_mean"]), rel=1e-12)
        assert by_h[h]["ess"] == pytest.approx(res.ess, rel=1e-12)
        assert by_h[h]["n_episodes"] == res.matched["n_episodes"]
        assert by_h[h]["warnings"] == res.warnings

    # 매칭 표의 유사도도 그대로 (표시용 반올림만 적용)
    score_col = analysis["matches"]["columns"].index("유사도")
    api_scores = [row[score_col] for row in analysis["matches"]["rows"]]
    assert api_scores == pytest.approx(list(matches["score"].round(4)), rel=1e-9)


def test_audit_matches_the_engine(analysis, client):
    from app.regime import audit as audit_mod

    date = analysis["match_dates"][0]
    res = client.post("/api/regime/audit",
                      json={"data": {"session": analysis["session"]}, "params": {}, "date": date})
    assert res.status_code == 200, res.text
    j = res.json()

    params = Params.from_config(load_config())
    market = load_market(params.ticker, params.years, params.exogenous,
                         source="synthetic", use_cache=False)
    fs = build_features(market, params)
    valid = fs.valid_mask()
    anchor = market.calendar[valid.reindex(market.calendar).fillna(False)].max()
    scored, _ = similarity.candidate_scores(fs.values, anchor, params.similarity.weights,
                                            params.similarity, valid=valid, max_horizon=120)
    matches = similarity.decluster(scored, market.calendar, params.similarity.min_gap,
                                   pick=params.similarity.episode_pick, top_n=params.similarity.top_n)
    expected = audit_mod.audit_match(market, fs, params, anchor, date,
                                     weights=params.similarity.weights,
                                     scored=scored, matches=matches,
                                     horizons=params.forward.horizons)
    assert j["date"] == str(expected.date.date())
    assert j["summary"]["거리 d = √(Σw·Δz²/Σw)"] == pytest.approx(
        expected.distance["거리 d = √(Σw·Δz²/Σw)"], rel=1e-6)
    assert j["summary"]["점수 100·exp(−d²/2)"] == pytest.approx(
        expected.distance["점수 100·exp(−d²/2)"], rel=1e-6)
    assert len(j["features"]["rows"]) == len(expected.features)
    assert j["forward"]["rows"][0][1] == str(expected.date.date())   # 시작일


def test_validation_runs_and_separates_in_and_out_of_sample(analysis, client):
    res = client.post("/api/regime/validation", json={
        "data": {"session": analysis["session"]},
        "params": {"validation": {"mode": "fixed", "train_end": "2012-12-31",
                                  "validation_end": "2016-12-31", "step": 60, "horizon": 20}},
    })
    assert res.status_code == 200, res.text
    j = res.json()
    kinds = {row[j["table"]["columns"].index("구분")] for row in j["table"]["rows"]}
    assert kinds == {"In-Sample", "Out-of-Sample"}
    assert j["chart"]["data"]


# ---------------- 업로드 경로 ----------------

def test_upload_flow_end_to_end(client):
    prices = synthetic_prices("^IXIC", "2006-01-01")
    out = prices.reset_index()
    out.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    csv = out.to_csv(index=False).encode()

    res = client.post("/api/regime/inspect",
                      files={"file": ("my_ixic.csv", io.BytesIO(csv), "text/csv")},
                      data={"kind": "price"})
    assert res.status_code == 200, res.text
    info = res.json()
    assert info["mapping"]["close"] == "Close" and info["rows"] == len(out)

    res = client.post("/api/regime/analyze", json={
        "params": {},
        "data": {"mode": "manual", "offline": True,
                 "price": {"token": info["token"], "mapping": info["mapping"]}},
    })
    assert res.status_code == 200, res.text
    j = res.json()
    source_col = j["sources"]["columns"].index("입력 방식")
    name_col = j["sources"]["columns"].index("파일명 / 제공자")
    assert j["sources"]["rows"][0][source_col] == "Manual Upload"
    assert j["sources"]["rows"][0][name_col] == "my_ixic.csv"
    assert j["matches"]["rows"]


def test_bad_mapping_is_reported_not_crashed(client):
    csv = b"A,B\n1,2\n"
    info = client.post("/api/regime/inspect",
                       files={"file": ("junk.csv", io.BytesIO(csv), "text/csv")},
                       data={"kind": "price"}).json()
    res = client.post("/api/regime/analyze", json={
        "params": {}, "data": {"mode": "manual", "price": {"token": info["token"], "mapping": {}}}})
    assert res.status_code == 400
    assert "Date" in res.json()["detail"] or "데이터" in res.json()["error"]


# ---------------- 호스팅 설정 ----------------

def test_hosted_config_only_lowers_bootstrap_samples():
    hosted = Params.from_config(load_config(ROOT / "deploy" / "regime_config.render.yaml"))
    repo = Params.from_config(load_config())
    assert hosted.forward.bootstrap_samples == 500
    assert hosted.similarity.weights == repo.similarity.weights
    assert hosted.distribution == repo.distribution
    assert hosted.features == repo.features


def test_render_blueprint_has_no_separate_streamlit_service():
    yaml = pytest.importorskip("yaml")
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    names = [s["name"] for s in blueprint["services"]]
    assert names == ["suh-dh-api"]                     # 별도 compute 인스턴스 없음
    env = {e["key"]: e["value"] for e in blueprint["services"][0]["envVars"]}
    assert env["SUH_DH_REGIME_CONFIG"] == "deploy/regime_config.render.yaml"
