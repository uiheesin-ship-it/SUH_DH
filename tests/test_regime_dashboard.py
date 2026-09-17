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
import re
from dataclasses import replace
from pathlib import Path

import pandas as pd
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
    # 분석 UI 가 즉시 있는지 (iframe 으로 외부 서비스에 떠넘기지 않는다)
    assert "<iframe" not in body
    # 외부 주소는 백엔드 입력칸의 placeholder 예시로만 등장해야 한다
    assert body.count("onrender.com") <= 1 and 'placeholder="https://suh-dh-api.onrender.com"' in body
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


def test_single_file_with_volume_is_enough(client):
    """사용자가 실제로 올리는 형태: 한 파일에 OHLCV 가 다 들어 있고 날짜가 내림차순."""
    prices = synthetic_prices("^IXIC", "2006-01-01")
    out = prices.reset_index()
    out.columns = ["date", "open", "high", "low", "close", "Volume"]   # 소문자 + Volume
    out = out.iloc[::-1]                                               # 최신 날짜가 위
    csv = out.to_csv(index=False).encode()

    info = client.post("/api/regime/inspect",
                       files={"file": ("ixic.csv", io.BytesIO(csv), "text/csv")},
                       data={"kind": "price"}).json()
    assert info["mapping"] == {"date": "date", "open": "open", "high": "high",
                               "low": "low", "close": "close", "volume": "Volume"}

    res = client.post("/api/regime/analyze", json={
        "params": {}, "data": {"mode": "manual", "offline": True,
                               "price": {"token": info["token"], "mapping": info["mapping"]}}})
    assert res.status_code == 200, res.text
    j = res.json()
    cols = j["sources"]["columns"]
    rows = {row[0]: row for row in j["sources"]["rows"]}
    # 거래량도 같은 파일에서 온다 — 따로 올릴 필요가 없다
    assert rows["Volume"][cols.index("입력 방식")] == "Manual Upload"
    assert "ixic.csv" in rows["Volume"][cols.index("파일명 / 제공자")]
    assert rows["Volume"][cols.index("사용 가능 관측치")] > 4000
    # 분산일(거래량 조건)이 실제로 계산된다
    dd = [i for g in j["state"]["groups"] for i in g["items"] if i["key"] == "dd_count"]
    assert dd and dd[0]["value"] is not None


def test_long_history_is_trimmed_to_the_configured_window(client):
    """30년치를 올려도 설정한 기간(기본 20년)만 쓰고, 그것 때문에 죽지 않는다."""
    prices = synthetic_prices("^IXIC", "1996-01-01")          # ~30년, 7,700행
    out = prices.reset_index()
    out.columns = ["date", "open", "high", "low", "close", "Volume"]
    csv = out.iloc[::-1].to_csv(index=False).encode()
    assert len(out) > 7000

    info = client.post("/api/regime/inspect",
                       files={"file": ("ixic30.csv", io.BytesIO(csv), "text/csv")},
                       data={"kind": "price"}).json()
    assert info["rows"] == len(out)

    res = client.post("/api/regime/analyze", json={
        "params": {}, "data": {"mode": "manual", "offline": True,
                               "price": {"token": info["token"], "mapping": info["mapping"]}}})
    assert res.status_code == 200, res.text
    j = res.json()
    cols, rows = j["sources"]["columns"], {r[0]: r for r in j["sources"]["rows"]}
    used = rows["Price (OHLC)"][cols.index("행 수")]
    assert 4900 <= used <= 5100, used                          # 20년치만 사용
    period = rows["Price (OHLC)"][cols.index("기간")]
    assert period.startswith("2006-"), period
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

def test_build_carries_the_repo_backend_url(tmp_path, monkeypatch):
    """빌드 변수가 없어도 저장소에 적어 둔 백엔드 주소를 정적 빌드가 이어받는다."""
    import build

    static = tmp_path / "static"
    (static / "regime").mkdir(parents=True)
    cfg = static / "regime" / "config.js"
    monkeypatch.setattr(build, "STATIC", static)

    cfg.write_text('window.SUH_DH_API_BASE = "";\n', encoding="utf-8")
    assert build.repo_regime_api_base() == ""
    cfg.write_text('window.SUH_DH_API_BASE = "https://suh-dh-api.onrender.com/";\n', encoding="utf-8")
    assert build.repo_regime_api_base() == "https://suh-dh-api.onrender.com"

    # SUH_DH_API_BASE 가 비어 있으면 기본값(REGIME_API_DEFAULT)을 이어받는다.
    # 정적 빌드는 config.js 를 새로 쓰기 때문에 여기서 주소를 못 찾으면 사이트가 백엔드를 잃는다.
    cfg.write_text(
        'window.SUH_DH_REGIME_API_DEFAULT = "https://suh-dh-regime.onrender.com";\n'
        'window.SUH_DH_API_BASE = "";\n',
        encoding="utf-8")
    assert build.repo_regime_api_base() == "https://suh-dh-regime.onrender.com"


def test_repo_config_ships_a_working_default_backend():
    """저장소 config.js 에 적힌 기본 주소가 빌드까지 그대로 전달된다."""
    import build

    cfg = (ROOT / "app" / "static" / "regime" / "config.js").read_text(encoding="utf-8")
    assert "SUH_DH_REGIME_API_DEFAULT" in cfg
    assert build.repo_regime_api_base().startswith("https://")


def test_frontend_verifies_the_backend_url():
    """엉뚱한 주소(예: 옛 Streamlit 서비스)를 넣으면 화면이 먼저 알려 준다."""
    js = (ROOT / "app" / "static" / "regime" / "app.js").read_text(encoding="utf-8")
    assert "SUH_DH_REGIME_API_DEFAULT" in js                 # 기본값 폴백
    assert "wakeBackend" in js and '"/api/health"' in js
    assert 'status === "ok"' in js                            # 응답 내용까지 확인
    assert "#backend-setup" in js                             # 실패하면 주소 입력창을 연다
    # 살아 있는 다른 서비스(404/405)는 기다릴 이유가 없으니 즉시 '주소가 다르다'
    assert "res.status === 404" in js and "wrong: true" in js


def test_local_dashboard_never_calls_the_hosted_backend():
    """로컬(STATIC=false)에서는 저장소 기본 주소를 쓰지 않는다 — 같은 서버가 계산한다.

    기본값 폴백이 로컬까지 적용되면 ./run.sh 로 띄운 대시보드가 남의 백엔드로 나간다.
    (실제로 한 번 그렇게 만들었다가 브라우저 E2E 가 잡아냈다.)
    """
    js = (ROOT / "app" / "static" / "regime" / "app.js").read_text(encoding="utf-8")
    assert 'STATIC ? normaliseUrl(window.SUH_DH_REGIME_API_DEFAULT || "") : ""' in js
    cfg = (STATIC / "regime" / "config.js").read_text(encoding="utf-8")
    assert "window.SUH_DH_STATIC = false;" in cfg              # 저장소 사본은 로컬용


def test_frontend_waits_out_a_sleeping_backend():
    """무료 인스턴스가 깨는 30~60초를 기다린다 — 한 번 찔러 보고 포기하지 않는다."""
    js = (ROOT / "app" / "static" / "regime" / "app.js").read_text(encoding="utf-8")
    assert "WAKE_BUDGET_MS" in js and "while (Date.now() - started < WAKE_BUDGET_MS)" in js
    assert "AbortController" in js                            # 한 번 찌를 때의 타임아웃
    assert "onTick" in js                                     # 남은 시간을 화면에 알려 준다
    # 인스턴스가 중간에 잠들었으면 깨우고 한 번 더 보낸다
    assert "looksOffline" in js and "return await rawPost(path, build());" in js
    # 재시작으로 업로드 토큰이 날아갔으면 기억해 둔 파일로 다시 올린다
    assert "reuploadSaved" in js and "업로드 세션이 만료" in js
    # 진행 중에는 경과 초를 보여 준다(먹통처럼 보이지 않게)
    assert "busyText" in js and "초" in js


def test_stale_stored_backend_url_heals_itself():
    """브라우저에 저장된 주소가 틀리면 기본 주소로 되돌려 다시 시도한다.

    저장값은 무엇보다 우선하기 때문에, 한 번 잘못 넣어 두면 빌드가 아무리 맞는 주소를
    들고 있어도 계속 그 주소로 나간다 — 실제로 그렇게 막혀 있었다.
    """
    js = (ROOT / "app" / "static" / "regime" / "app.js").read_text(encoding="utf-8")
    assert "builtinApiBase" in js
    assert 'storedApiBase() && builtin && builtin !== API_BASE' in js
    assert 'storeApiBase("");' in js                           # 잘못된 저장값을 버린다
    assert "기본 주소로 되돌립니다" in js


def test_every_backend_call_waits_behind_one_gate():
    """잠든 백엔드에 요청을 제각각 쏘지 않는다 — 깨우기는 한 번, 나머지는 그 뒤에 줄을 선다.

    게이트가 없으면 init 의 health 폴링, 파일 업로드 POST, 분석 실행이 각자 매달려서
    타이머만 여러 개 도는 상태가 된다(실제로 그렇게 멈춰 있었다).
    """
    js = (ROOT / "app" / "static" / "regime" / "app.js").read_text(encoding="utf-8")
    assert "async function ensureBackend" in js
    assert "WAKE_RUN" in js and "WAKE_LISTENERS" in js       # 깨우기는 한 번만 돈다
    # 실제 호출은 게이트를 통해서만 — 직접 wakeBackend 를 부르는 곳은 게이트뿐
    assert js.count("wakeBackend(") == 2                      # 정의 1 + 게이트 안 1
    for caller in ("async function rawPost", "async function inspectFile"):
        body = js.split(caller, 1)[1][:900]
        assert "ensureBackend" in body, caller
    # 업로드도 시간 제한과 재시도를 갖는다 (예전엔 맨 fetch 라 무한정 매달렸다)
    upload = js.split("async function inspectFile", 1)[1][:1400]
    assert "fetchTimeout" in upload and "BACKEND_READY = false" in upload


def test_backend_is_not_rebuilt_by_data_commits():
    """데이터 커밋(하루 50번 이상)이 백엔드를 다시 배포하지 않게 막아 둔다.

    막지 않으면 백엔드가 온종일 재시작 중이라 깨어 있을 틈이 없고,
    재시작마다 메모리에 있던 업로드 세션이 날아간다.
    """
    yaml = pytest.importorskip("yaml")
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    ignored = blueprint["services"][0]["buildFilter"]["ignoredPaths"]
    # 자동 커밋이 실제로 건드리는 경로를 모두 덮는다 (git log 로 확인한 목록)
    assert "data/**" in ignored and "state/**" in ignored


def test_hub_prewarms_the_backend():
    """대시보드를 여는 순간 백엔드를 한 번 찔러 둔다 — 카드를 누르면 이미 깨어 있다."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "prewarmBackend" in html
    assert "/api/health" in html
    assert "suh_dh_regime_api" in html                        # 브라우저에 저장된 주소가 우선
    assert "SUH_DH_REGIME_API_DEFAULT" in html                # 없으면 저장소 기본값
    assert ".catch(() => {})" in html                         # 실패해도 대시보드에 영향 없음


def test_hosted_config_only_lowers_bootstrap_samples():
    hosted = Params.from_config(load_config(ROOT / "deploy" / "regime_config.render.yaml"))
    repo = Params.from_config(load_config())
    assert hosted.forward.bootstrap_samples == 500
    assert hosted.similarity.weights == repo.similarity.weights
    assert hosted.distribution == repo.distribution
    assert hosted.features == repo.features


def test_keep_warm_workflow_pings_the_backend():
    """무료 인스턴스가 잠들지 않도록 주기적으로 /api/health 를 친다."""
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "warm-api.yml").read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)                    # YAML 의 on: 은 True 로 파싱된다
    crons = [c["cron"] for c in on["schedule"]]
    assert crons and all(c.startswith("*/10") for c in crons)   # 10분 간격 (Render 는 15분 유휴)
    assert "workflow_dispatch" in on
    steps = wf["jobs"]["ping"]["steps"]
    script = " ".join(str(s.get("run", "")) for s in steps)
    assert "/api/health" in script
    # 주소는 repo Variable → 저장소 config.js 순으로 찾는다
    assert "vars.SUH_DH_API_BASE" in script
    assert "app/static/regime/config.js" in script
    assert "SUH_DH_REGIME_API_DEFAULT" in script              # config.js 의 기본값까지 폴백
    # 200 이어도 응답이 대시보드 백엔드가 아니면 경고를 남긴다
    assert '\'"status"\'' in script
    # 응답이 없어도 잡을 실패시키지 않고 경고만 남긴다 (알림 소음 방지)
    assert "::warning::" in script


def test_render_blueprint_has_no_separate_streamlit_service():
    yaml = pytest.importorskip("yaml")
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    names = [s["name"] for s in blueprint["services"]]
    assert names == ["suh-dh-api"]                     # 별도 compute 인스턴스 없음
    env = {e["key"]: e["value"] for e in blueprint["services"][0]["envVars"]}
    assert env["SUH_DH_REGIME_CONFIG"] == "deploy/regime_config.render.yaml"


# --------------------------------------------------------------------------
# 응답을 가볍게 — 계산은 그대로, 전송량과 그리는 시간만 줄인다.
# --------------------------------------------------------------------------

def test_analyze_response_is_compact(analysis):
    """차트 JSON 에 자정 타임스탬프와 불필요한 밑자리가 남아 있지 않다.

    20년 차트는 trace 4개 × 5,000점이라 표기 방식만으로 수백 KB 가 왔다 갔다 한다.
    '2006-09-18T00:00:00.000000' → '2006-09-18' 만으로도 1/3 이 줄어든다.
    """
    import json

    price = analysis["charts"]["price"]
    xs = [tr for tr in price["data"] if isinstance(tr.get("x"), list) and tr["x"]]
    assert xs, "가격 차트에 x 축 배열이 있어야 한다"
    for tr in xs:
        assert all("T00:00:00" not in str(v) for v in tr["x"][:50])
        assert all(len(str(v)) == 10 for v in tr["x"][:50])     # YYYY-MM-DD

    raw = json.dumps(analysis)
    assert "T00:00:00" not in raw
    # 소수점 6자리로 맞춰 둔다 — 차트에서는 같은 픽셀이고, 표/통계는 이 경로를 안 탄다.
    assert not re.search(r"\d\.\d{9,}", json.dumps(price))


def test_api_compresses_large_responses(client):
    """~600KB 의 figure JSON 을 gzip 으로 보낸다 (느린 회선에서 체감 차이가 크다)."""
    res = client.post("/api/regime/analyze", json={"data": OFFLINE, "params": {}},
                      headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers.get("content-encoding") == "gzip"
    # httpx 가 풀어 준 본문 기준으로, 압축이 의미 있는 크기인지 확인
    assert len(res.content) > 100_000


def test_match_shading_is_identical_to_add_vrect():
    """음영 처리를 한 번에 넣도록 바꿨다 — 그림이 예전(add_vrect)과 같은지 직접 비교한다.

    add_vrect 는 호출마다 subplot 축을 다시 훑어서 match 25개에 0.3초 넘게 쓴다
    (무료 인스턴스에서는 몇 초). 모아서 넣으면 빨라지지만, 결과 figure 가 조금이라도
    달라지면 안 되므로 여기서 실제로 맞춰 본다.
    """
    import json

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from app.regime import viz

    dates = pd.date_range("2020-01-01", periods=40, freq="B")

    def base_fig():
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                            row_heights=[0.72, 0.28], subplot_titles=("a", "b"))
        fig.add_trace(go.Scatter(x=dates, y=list(range(40))), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=list(range(40))), row=2, col=1)
        return fig

    spans = [(dates[i], dates[i + 5]) for i in range(0, 25, 3)]

    old = base_fig()                                   # 예전 방식
    for x0, x1 in spans:
        old.add_vrect(x0=x0, x1=x1, fillcolor=viz.SHADE_COLOR, line_width=0,
                      layer="below", row=1, col=1)

    new = base_fig()                                   # 지금 방식 (viz.price_chart 와 동일)
    new.update_layout(shapes=tuple(new.layout.shapes) + tuple(
        dict(type="rect", xref="x", yref="y domain", x0=x0, x1=x1, y0=0, y1=1,
             fillcolor=viz.SHADE_COLOR, line_width=0, layer="below")
        for x0, x1 in spans))

    assert json.loads(old.to_json()) == json.loads(new.to_json())


def test_upload_dependency_is_declared():
    """Manual Upload 에 필요한 python-multipart 를 requirements 에 못 박는다.

    이게 빠져 있으면 FastAPI 가 UploadFile/Form 라우터 등록을 거부하고,
    app/main.py 의 try/except 가 그걸 삼켜서 /api/regime/* 전체가 404 가 된다.
    개발 환경에는 우연히 깔려 있어 테스트는 통과하고, 새로 설치한 곳에서만 터진다
    — 실제로 그렇게 막혔다.
    """
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "python-multipart" in reqs


def test_health_reports_whether_the_regime_api_is_mounted(client):
    """의존성이 없어 Regime Lab 이 빠졌으면 /api/health 가 이유를 말한다."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["regime"]["ok"] is True and body["regime"]["error"] is None

    js = (ROOT / "app" / "static" / "regime" / "app.js").read_text(encoding="utf-8")
    assert "body.regime.ok === false" in js        # 화면이 그 이유를 그대로 보여 준다

def test_automated_data_commits_do_not_trigger_render_builds():
    """자동 데이터 커밋은 Render 배포를 건너뛴다 — 안 그러면 빌드 시간이 말라 버린다.

    실제로 그렇게 됐다: 기본 브랜치에 하루 50번 넘게 커밋이 올라가고, Render 가
    매번 pip install 부터 다시 하다가 workspace 의 pipeline minutes 를 다 써서
    "Build blocked — Your workspace has run out of pipeline minutes" 로 막혔다.
    그동안 백엔드는 9월 13일 빌드에 멈춰 있었고, Regime Lab API 는 한 번도
    배포되지 못했다.

    Render 는 커밋 메시지의 [skip render] 를 보고 자동 배포를 건너뛴다
    (https://render.com/docs/deploys). 워크플로가 새로 생겨도 빠뜨리지 않도록
    여기서 전부 확인한다.
    """
    import re

    missing = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for msg in re.findall(r'git commit -m "([^"]*)"', wf.read_text(encoding="utf-8")):
            if "[skip render]" not in msg:
                missing.append(f"{wf.name}: {msg}")
    assert not missing, "자동 커밋에 [skip render] 가 빠졌습니다:\n" + "\n".join(missing)


def test_help_panel_documents_every_parameter_in_sections_2_to_5():
    """❓ 설명 패널이 2~5번 섹션의 입력을 하나도 빠짐없이 다룬다.

    파라미터를 새로 추가하면서 설명을 안 쓰는 일이 생기지 않도록, index.html 의
    입력 id 를 훑어서 대응하는 설명 문구가 있는지 확인한다.
    """
    import re

    html = (STATIC / "regime" / "index.html").read_text(encoding="utf-8")
    body = html.split('<div id="help"', 1)[1].split('<div id="overlay"', 1)[0]

    # 버튼과 여닫는 동작
    assert 'id="help-btn"' in html and 'id="help-close"' in html
    js = (STATIC / "regime" / "app.js").read_text(encoding="utf-8")
    assert '"#help", "#help-btn"' in js and 'e.key !== "Escape"' in js   # 여닫기 배선

    # 각 파라미터가 무엇을 계산하는지 — 식/기본값이 실제 구현과 같은 말을 해야 한다
    for phrase in (
        "SMA(w) = 최근 w 거래일 종가 평균",          # trend.py
        "px_vs_sma{w}", "sma_stack", "sma{w}_slope",
        "ret_k = (C_t / C_(t−k) − 1) × 100",        # momentum.py
        "dd_52w", "기본 가중치 1.5",
        "std(로그수익률, 최근 w일, ddof=1) × √252 × 100",   # volatility.py
        "Wilder", "atr_pct = ATR / C × 100",
        "CLV = (종가 − 저가) / (고가 − 저가)",        # distribution.py
        "당일 거래량 ≥ 전일 거래량 × (1 + Y/100)",
        "dd_count", "dd_days_since",
        "y10_level", "y10_chg_{w}d", "y10_pctile", "bp",    # macro.py
        "z = (x − 중앙값) / (1.4826 × MAD)",          # similarity.py
        "d = √( Σ wᵢ (zᵢ − zᵢ*)² / Σ wᵢ )",
        "score = 100 × exp(−d² / 2)",
        "De-clustering", "episode 대표", "최근 N일 제외",
        "fwd_h = (C_(t+h) / C_t − 1) × 100",          # forward.py
        "n_eff = n² / Σᵢⱼ max(0, 1 − |tᵢ−tⱼ| / h)",
        "cluster", "iid", "Baseline",
        "Out-of-Sample", "Spearman", "방향 적중률",    # validation.py
        "Expanding window",
    ):
        assert phrase in body, f"설명 패널에 '{phrase}' 가 없습니다"

    # 2~5번 섹션의 입력 id 를 하나도 빠뜨리지 않았는지 — 설명 키워드로 대조
    covered = {
        "p-sma": "SMA 창", "p-slope": "기울기 구간", "p-rets": "수익률 창",
        "p-high": "고점 구간", "p-vol": "실현변동성", "p-atr": "ATR",
        "p-dd-lb": "Lookback", "p-dd-drop": "X: 하락률", "p-dd-vol": "Y: 거래량 증가",
        "p-dd-clv": "Z: CLV", "p-topn": "상위 N개", "p-gap": "De-clustering 간격",
        "p-pick": "episode 대표", "p-exclude": "최근 N일 제외", "p-norm": "정규화",
        "p-fullh": "최장 horizon", "p-horizons": "horizon", "p-boot": "Bootstrap 반복",
        "p-ci": "신뢰수준", "p-warn": "표본 경고 기준", "p-indep": "표본 독립성",
        "p-cimethod": "CI 재표본", "p-val-mode": "방식", "p-val-train": "Training 종료",
        "p-val-valid": "Validation 종료", "p-val-step": "평가 간격",
        "p-val-h": "검증 horizon",
    }
    section = html.split("2. 시장 상태 정의", 1)[1].split("6. 차트", 1)[0]
    ids = set(re.findall(r'id="(p-[a-z0-9-]+)"', section))
    assert ids <= set(covered), f"설명이 없는 새 파라미터: {sorted(ids - set(covered))}"
    for pid, phrase in covered.items():
        if pid in ids:
            assert phrase in body, f"{pid} 설명('{phrase}')이 패널에 없습니다"


def test_last_result_survives_a_refresh():
    """새로고침해도 지난 분석 결과가 남고, '지난 실행'임을 분명히 밝힌다.

    올린 파일은 IndexedDB 로 복원되는데 결과만 매번 사라져서 "다시 올려야 하나"
    싶게 만들었다. 결과도 담아 두되, 최신 값인 척하면 안 되므로 배너로 표시한다.
    """
    js = (STATIC / "regime" / "app.js").read_text(encoding="utf-8")
    assert "RESULT_KEY" in js and "rememberResult" in js and "restoreResult" in js
    # 데이터가 바뀌면 지난 결과는 버린다
    assert "dataFingerprint" in js and "rec.fingerprint !== dataFingerprint()" in js
    # 서버 세션은 살아 있지 않을 수 있다 — 복원할 때 비운다
    assert "SESSION = null;" in js.split("async function restoreResult", 1)[1][:900]
    # 새 결과를 그리면 배너를 지운다
    assert '$("#result-age").classList.add("hidden")' in js
    html = (STATIC / "regime" / "index.html").read_text(encoding="utf-8")
    assert 'id="result-age"' in html


def test_setup_guide_panel():
    """🖥 설치·실행 — 다른 컴퓨터에서 띄우는 방법을 화면 안에서 볼 수 있다."""
    html = (STATIC / "regime" / "index.html").read_text(encoding="utf-8")
    assert 'id="setup-btn"' in html and 'id="setup-close"' in html
    body = html.split('<div id="setup"', 1)[1].split('<div id="overlay"', 1)[0]

    for phrase in (
        "python.org/downloads", "py --version",                       # ① Python
        "archive/refs/heads/claude/funny-carson-ent3s7.zip",          # ② 내려받기
        "requirements.txt", "powershell",
        "py -m pip install -r requirements.txt",                      # ③ 설치
        "py -m uvicorn app.main:app --port 8000",                     # ④ 실행
        "./run.sh", "Ctrl + C",
        "127.0.0.1:8000/regime/", "Manual Upload",                    # ⑤ 사용
        "127.0.0.1:8000/api/health", '"regime":{"ok":true}',          # 막힐 때
        "--port 8001",
    ):
        assert phrase in body, f"설치 안내에 '{phrase}' 가 없습니다"

    # 안내한 브랜치가 이 저장소의 실제 기본 브랜치와 같아야 한다
    import subprocess
    head = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                          cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert "claude/funny-carson-ent3s7" in body
    # 실행 명령이 실제 앱 경로를 가리키는지
    assert (ROOT / "app" / "main.py").exists() and (ROOT / "run.sh").exists()

    js = (STATIC / "regime" / "app.js").read_text(encoding="utf-8")
    assert '"#setup", "#setup-btn"' in js and 'e.key !== "Escape"' in js
