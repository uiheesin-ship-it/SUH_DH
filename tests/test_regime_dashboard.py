"""Dashboard integration for the Market Regime Lab.

The lab is reachable from the hub (미장 → 기타) and runs *inside* the dashboard:
FastAPI starts the Streamlit process on demand and proxies it under
``/regime/app/**``. These tests cover the wiring — the card, the landing page,
the control endpoints and the proxy's behaviour when nothing is running — without
actually spawning Streamlit (that is covered by the AppTest suites).

Run with:  python -m pytest tests/test_regime_dashboard.py -q
"""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app import regime_host  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_hub_card_is_registered_under_us_other():
    """허브(미장 → 기타)에 카드가 있고, 정적 페이지로 연결된다."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '"Market Regime Lab"' in html
    card = html[html.index('name: "Market Regime Lab"'):]
    card = card[:card.index("},")]
    assert 'market: "us"' in card and 'group: "other"' in card
    assert 'href: "regime/"' in card
    assert 'status: "ready"' in card


def test_landing_page_is_served_and_dashboard_styled(client):
    res = client.get("/regime/")
    assert res.status_code == 200
    body = res.text
    assert "Market Regime Lab" in body
    assert 'class="topbar"' in body and 'href="../"' in body      # 다른 프로그램과 같은 헤더
    assert 'id="lab"' in body                                      # 대시보드 안에서 여는 iframe
    for asset in ("style.css", "app.js", "config.js"):
        assert client.get(f"/regime/{asset}").status_code == 200


def test_landing_page_embeds_instead_of_telling_users_to_run_locally(client):
    """정적 호스팅에서도 이 화면 안에서 앱이 열려야 한다 — '로컬에서 실행하세요'로
    끝내는 안내 화면은 없어야 한다."""
    body = client.get("/regime/").text
    assert "로컬 대시보드에서 실행하세요" not in body
    assert 'id="setup"' in body and 'id="regime-url"' in body      # 원격 주소 입력
    assert 'id="overlay"' in body                                  # 로딩(깨우는 중) 표시

    js = client.get("/regime/app.js").text
    assert "SUH_DH_REGIME_URL" in js                               # 저장소/빌드 기본 주소
    assert "localStorage" in js                                    # 브라우저에 기억
    assert "?embed=true" in js                                     # Streamlit 임베드 모드
    cfg = client.get("/regime/config.js").text
    assert "window.SUH_DH_REGIME_URL" in cfg


def test_local_backend_wins_over_the_default_remote_url(client):
    """로컬 대시보드에서는 콜드 스타트 없는 자체 인스턴스를 먼저 쓴다.

    사용자가 직접 지정한 주소(?app= / localStorage)만 그보다 우선한다.
    """
    js = client.get("/regime/app.js").text
    chosen = js.index("const chosen = chosenRemote();")
    local = js.index("const local = await localBackend();", chosen)
    fallback = js.index("const fallback = defaultRemote();", chosen)
    assert chosen < local < fallback


def test_status_endpoint_reports_capability(client):
    body = client.get("/api/regime/status").json()
    assert set(body) >= {"available", "missing", "running", "port", "path", "script"}
    assert body["path"] == "/regime/app/"
    assert body["script"].endswith("streamlit_app.py")
    # 이 저장소 환경에는 streamlit 이 설치돼 있으므로 available 이어야 한다
    assert body["available"] is (not regime_host.missing_requirements())


def test_proxy_reports_clearly_when_not_running(client, monkeypatch):
    monkeypatch.setattr(regime_host, "is_running", lambda: False)
    res = client.get("/regime/app/")
    assert res.status_code == 503
    assert "실행 중이 아닙니다" in res.json()["error"]


def test_proxy_route_wins_over_the_static_catch_all(client, monkeypatch):
    """/regime/app/** 는 StaticFiles(catch-all) 가 아니라 프록시가 처리해야 한다.

    정적 마운트가 먼저 잡히면 404(없는 파일)가 오고, 프록시가 잡으면 503(아직 실행 전)
    이 온다 — 상태 코드로 어느 쪽이 처리했는지 알 수 있다.
    """
    monkeypatch.setattr(regime_host, "is_running", lambda: False)
    for path in ("/regime/app/", "/regime/app/_stcore/health", "/regime/app/static/js/x.js"):
        res = client.get(path)
        assert res.status_code == 503, f"{path} → {res.status_code} (정적 마운트가 가로챘습니다)"


def test_landing_page_assets_are_not_shadowed_by_the_proxy(client):
    """랜딩 페이지의 app.js 가 /regime/app** 프록시에 먹히면 안 된다."""
    assert client.get("/regime/app.js").status_code == 200
    assert "Market Regime Lab" in client.get("/regime/app.js").text


def test_start_is_reported_not_crashed_when_dependencies_missing(monkeypatch):
    monkeypatch.setattr(regime_host, "missing_requirements", lambda: ["streamlit"])
    result = regime_host.start(timeout=1)
    assert result["ok"] is False and result["running"] is False
    assert "streamlit" in result["missing"]


def test_build_injects_the_deployed_regime_url(tmp_path):
    """정적 빌드가 배포된 Streamlit 주소를 config.js 에 심어야 카드가 바로 열린다."""
    import build

    (tmp_path / "regime").mkdir()
    cfg = tmp_path / "regime" / "config.js"
    cfg.write_text("window.SUH_DH_STATIC = true;\n", encoding="utf-8")

    assert build.write_regime_url(tmp_path, "https://suh-dh-regime.onrender.com/") == \
        "https://suh-dh-regime.onrender.com"
    assert 'window.SUH_DH_REGIME_URL = "https://suh-dh-regime.onrender.com";' in cfg.read_text()

    before = cfg.read_text()
    assert build.write_regime_url(tmp_path, "   ") == ""            # 값이 없으면 아무것도 안 쓴다
    assert cfg.read_text() == before

    # 빌드 변수가 없으면 저장소에 커밋해 둔 기본값을 쓴다
    assert build.write_regime_url(tmp_path, "", fallback="https://fallback.example/") == \
        "https://fallback.example"
    assert 'window.SUH_DH_REGIME_URL = "https://fallback.example";' in cfg.read_text()
    # 빌드 변수가 있으면 그쪽이 이긴다
    assert build.write_regime_url(tmp_path, "https://env.example",
                                  fallback="https://fallback.example") == "https://env.example"


def test_repo_regime_url_reads_the_committed_default(tmp_path, monkeypatch):
    import build

    static = tmp_path / "static"
    (static / "regime").mkdir(parents=True)
    cfg = static / "regime" / "config.js"
    monkeypatch.setattr(build, "STATIC", static)

    cfg.write_text('window.SUH_DH_REGIME_URL = "";\n', encoding="utf-8")
    assert build.repo_regime_url() == ""
    cfg.write_text('window.SUH_DH_REGIME_URL = "https://lab.example.com/";\n', encoding="utf-8")
    assert build.repo_regime_url() == "https://lab.example.com"


def test_render_blueprint_deploys_the_streamlit_lab():
    """항상 켜져 있는 인스턴스가 있어야 Pages 에서 임베드가 가능하다."""
    yaml = pytest.importorskip("yaml")
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    names = [s["name"] for s in blueprint["services"]]
    assert "suh-dh-regime" in names
    svc = next(s for s in blueprint["services"] if s["name"] == "suh-dh-regime")
    assert "requirements-regime.txt" in svc["buildCommand"]
    start = " ".join(svc["startCommand"].split())
    assert "streamlit run app/regime/streamlit_app.py" in start
    assert "--server.port $PORT" in start and "--server.address 0.0.0.0" in start
    # 다른 오리진의 iframe 안에서 파일 업로드가 막히지 않도록 끈다
    assert "--server.enableXsrfProtection false" in start
    assert "--server.enableCORS false" in start
    assert svc["healthCheckPath"] == "/_stcore/health"
    env = {e["key"]: e["value"] for e in svc["envVars"]}
    assert env["SUH_DH_REGIME_CONFIG"] == "deploy/regime_config.render.yaml"
    assert (ROOT / env["SUH_DH_REGIME_CONFIG"]).exists()


def test_hosted_config_only_lowers_bootstrap_samples():
    """호스팅용 설정은 메모리 때문에 반복수만 낮추고 계산 방법은 그대로여야 한다."""
    from app.regime.config import Params, load_config

    hosted = Params.from_config(load_config(ROOT / "deploy" / "regime_config.render.yaml"))
    repo = Params.from_config(load_config())
    assert hosted.forward.bootstrap_samples == 500
    assert hosted.forward.horizons == repo.forward.horizons
    assert hosted.forward.ci_level == repo.forward.ci_level
    assert hosted.similarity.weights == repo.similarity.weights
    assert hosted.distribution == repo.distribution
    assert hosted.features == repo.features


def test_stop_without_owned_process_is_safe(monkeypatch):
    monkeypatch.setattr(regime_host, "_proc", None)
    out = regime_host.stop()
    assert out["ok"] is True
