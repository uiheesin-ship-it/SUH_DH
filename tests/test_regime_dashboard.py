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


def test_stop_without_owned_process_is_safe(monkeypatch):
    monkeypatch.setattr(regime_host, "_proc", None)
    out = regime_host.stop()
    assert out["ok"] is True
