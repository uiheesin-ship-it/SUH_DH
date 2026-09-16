"""Browser walk-through of the dashboard → Regime Lab flow (opt-in).

Runs the real thing: uvicorn serves the dashboard, the hub card is clicked, the
lab starts inside the iframe, a CSV is uploaded, the quality summary appears and
the analysis is started from the button. It needs a browser and ~2 minutes, so
it only runs when asked:

    SUH_DH_E2E=1 python -m pytest tests/test_regime_dashboard_e2e.py -q

Set ``SUH_DH_CHROMIUM`` if Playwright's bundled browser is not where it expects.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    os.environ.get("SUH_DH_E2E", "") not in ("1", "true", "True"),
    reason="브라우저 E2E 는 SUH_DH_E2E=1 일 때만 실행합니다.")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(url: str, timeout: float = 60) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = {**os.environ, "SUH_DH_REGIME_PORT": str(_free_port())}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        assert _wait(base + "/api/health"), "대시보드가 뜨지 않았습니다"
        yield base
    finally:
        import urllib.request

        try:  # 실행 중인 Streamlit 자식 프로세스까지 정리
            urllib.request.urlopen(urllib.request.Request(base + "/api/regime/stop", method="POST"),
                                   timeout=10)
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=20)


@pytest.fixture(scope="module")
def sample_csv(tmp_path_factory):
    from app.regime.data.sources import synthetic_prices

    path = tmp_path_factory.mktemp("e2e") / "my_ixic_20y.csv"
    out = synthetic_prices("^IXIC", "2006-01-01").reset_index()
    out.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    out.to_csv(path, index=False)
    return path


def _launch(pw):
    exe = os.environ.get("SUH_DH_CHROMIUM")
    if not exe:
        for candidate in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
            exe = str(candidate)
            break
    kwargs = {"args": ["--no-sandbox"]}
    if exe:
        kwargs["executable_path"] = exe
    return pw.chromium.launch(**kwargs)


def test_dashboard_card_to_analysis(server, sample_csv):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})

        # 1) 허브(미장 → 기타)에 카드가 있고 클릭하면 랩 페이지로 간다
        page.goto(server + "/", wait_until="networkidle")
        column = page.locator(".market-us .col", has=page.locator("h3", has_text="기타"))
        card = column.locator("a.card", has_text="Market Regime Lab")
        assert card.count() == 1, "미장 > 기타 에 Market Regime Lab 카드가 없습니다"
        card.click()
        page.wait_for_load_state("networkidle")
        assert page.url.rstrip("/").endswith("/regime")

        # 2) 대시보드 안(iframe)에서 Streamlit 이 열린다
        start = page.get_by_role("button", name="분석 화면 열기")
        if start.count():
            start.click()
        frame = page.frame_locator("#lab")
        frame.get_by_text("Market Regime Lab").first.wait_for(timeout=180_000)
        page.wait_for_timeout(3000)

        # 3) Manual Upload → 업로더가 바로 나타나고 CSV 를 올린다
        frame.locator("label").filter(has_text="Manual Upload").first.click(force=True)
        page.wait_for_timeout(2500)
        uploads = frame.locator('input[type="file"]')
        assert uploads.count() >= 1, "업로더가 보이지 않습니다"
        uploads.nth(0).set_input_files(str(sample_csv))
        page.wait_for_timeout(9000)

        body = frame.locator("body").inner_text()
        assert "② 데이터 확인" in body                       # 업로드 → 매핑 → 품질 확인
        assert sample_csv.name in body                        # 파일명 노출
        assert "Manual Upload" in body                        # 사용 중인 소스 표기
        assert "분석 실행" in body

        # 4) 분석 실행 → 결과 탭이 나온다
        run = frame.locator("button").filter(has_text="분석 실행").first
        if not run.is_enabled():
            frame.locator("label").filter(has_text="문제를 확인했고 그대로 진행").first.click(force=True)
            page.wait_for_timeout(2000)
            run = frame.locator("button").filter(has_text="분석 실행").first
        run.click()
        frame.get_by_text("① 현재 시장 상태").first.wait_for(timeout=300_000)
        page.wait_for_timeout(4000)

        body = frame.locator("body").inner_text()
        for tab in ("① 현재 시장 상태", "② 과거 유사 국면", "③ Forward Return",
                    "④ 계산 감사", "⑤ 통계적 검증", "⑥ 데이터 품질"):
            assert tab in body, f"{tab} 탭이 없습니다"
        browser.close()


# --------------------------------------------------------------------------
# 정적 호스팅(GitHub Pages) + 원격 Streamlit — 백엔드 없이 카드 화면 안에서 끝나는지
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def streamlit_server():
    """Render 와 같은 플래그로 Streamlit 을 띄운다 (다른 오리진 역할)."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app/regime/streamlit_app.py",
         "--server.port", str(port), "--server.address", "127.0.0.1",
         "--server.headless", "true", "--browser.gatherUsageStats", "false",
         "--server.enableCORS", "false", "--server.enableXsrfProtection", "false",
         "--server.fileWatcherType", "none"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        assert _wait(url + "/_stcore/health", timeout=120), "Streamlit 이 뜨지 않았습니다"
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=20)


@pytest.fixture(scope="module")
def static_site(tmp_path_factory, streamlit_server):
    """app/static 을 그대로 복사해 정적 호스팅처럼 서빙 — 백엔드 API 는 없다."""
    site = tmp_path_factory.mktemp("site")
    shutil.copytree(ROOT / "app" / "static", site, dirs_exist_ok=True)
    (site / "regime" / "config.js").write_text(
        "window.SUH_DH_STATIC = true;\n"
        f'window.SUH_DH_REGIME_URL = "{streamlit_server}";\n', encoding="utf-8")

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
         "--directory", str(site)],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    base = f"http://localhost:{port}"        # 호스트가 달라 Streamlit 과 다른 오리진
    try:
        assert _wait(base + "/regime/", timeout=30), "정적 사이트가 뜨지 않았습니다"
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=20)


def test_pages_card_embeds_remote_lab_and_runs_analysis(static_site, sample_csv):
    """공개 사이트 기준 완료 조건: 미장>기타 카드 → 업로드 → 품질 → 분석 실행."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})

        page.goto(static_site + "/", wait_until="networkidle")
        column = page.locator(".market-us .col", has=page.locator("h3", has_text="기타"))
        card = column.locator("a.card", has_text="Market Regime Lab")
        assert card.count() == 1
        card.click()
        page.wait_for_load_state("networkidle")
        landing = page.url

        # 로컬 실행 안내가 아니라 앱 자체가 이 화면 안에 떠야 한다
        assert "로컬 대시보드에서 실행" not in page.locator("body").inner_text()
        frame = page.frame_locator("#lab")
        frame.get_by_text("Market Regime Lab").first.wait_for(timeout=180_000)

        frame.locator("label").filter(has_text="Manual Upload").first.click(force=True)
        page.wait_for_timeout(2500)
        uploads = frame.locator('input[type="file"]')
        assert uploads.count() >= 1
        uploads.nth(0).set_input_files(str(sample_csv))       # 다른 오리진으로의 업로드
        page.wait_for_timeout(9000)

        body = frame.locator("body").inner_text()
        assert "② 데이터 확인" in body and sample_csv.name in body

        run = frame.locator("button").filter(has_text="분석 실행").first
        if not run.is_enabled():
            frame.locator("label").filter(has_text="문제를 확인했고 그대로 진행").first.click(force=True)
            page.wait_for_timeout(2000)
            run = frame.locator("button").filter(has_text="분석 실행").first
        run.click()
        frame.get_by_text("① 현재 시장 상태").first.wait_for(timeout=300_000)
        page.wait_for_timeout(4000)

        body = frame.locator("body").inner_text()
        for tab in ("① 현재 시장 상태", "② 과거 유사 국면", "③ Forward Return", "⑥ 데이터 품질"):
            assert tab in body
        assert page.url == landing, "분석 중 다른 사이트로 이동하면 안 됩니다"
        browser.close()
