"""Browser walk-through of the Market Regime Lab dashboard program (opt-in).

Runs the real thing: uvicorn serves the dashboard, the hub card is clicked, the
program's own UI appears immediately (no external service, no iframe), the
analysis is started from the page and the results, charts, audit and upload flow
are checked. Needs a browser and ~2 minutes, so it only runs when asked:

    SUH_DH_E2E=1 python -m pytest tests/test_regime_dashboard_e2e.py -q

Set ``SUH_DH_CHROMIUM`` if Playwright's bundled browser is not where it expects.
"""

import os
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
    env = {**os.environ, "SUH_DH_DEMO": "1"}          # 네트워크 없이 합성 데이터로
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        assert _wait(base + "/api/health"), "대시보드가 뜨지 않았습니다"
        yield base
    finally:
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


def test_card_opens_instantly_and_runs_the_analysis(server, sample_csv):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1500, "height": 1000})

        # 1) 허브 → 미장 → 기타 → 카드
        page.goto(server + "/", wait_until="networkidle")
        column = page.locator(".market-us .col", has=page.locator("h3", has_text="기타"))
        card = column.locator("a.card", has_text="Market Regime Lab")
        assert card.count() == 1

        started = time.time()
        card.click()
        # 2) UI 가 즉시 뜬다 — 외부 서비스도 iframe 도 없다
        page.wait_for_selector("#run-btn", timeout=5000)
        page.wait_for_selector("#params details", timeout=5000)
        elapsed = time.time() - started
        assert elapsed < 5, f"UI 가 뜨는 데 {elapsed:.1f}초 걸렸습니다"
        assert page.locator("iframe").count() == 0
        page.wait_for_function("document.querySelectorAll('#weights input.w').length > 5", timeout=15000)

        # 3) 분석 실행 → 결과
        page.click("#run-btn")
        page.wait_for_selector("#tabs:not(.hidden)", timeout=180_000)
        page.wait_for_selector("#panel-state table.data, #panel-state .metric", timeout=30_000)
        body = page.locator("#panel-state").inner_text()
        assert "시장 상태" in body and "분산일" in body

        page.click('.tab[data-tab="matches"]')
        # 차트 CDN 이 막힌 환경에서는 안내 문구로 대체된다 — 둘 중 하나는 있어야 한다
        page.wait_for_selector("#chart-price .plot-container, #chart-price .note", timeout=30_000)
        assert page.locator("#match-table table.data tbody tr").count() > 0

        page.click('.tab[data-tab="forward"]')
        page.wait_for_selector("#chart-forward .plot-container, #chart-forward .note", timeout=30_000)
        text = page.locator("#forward-tables").inner_text()
        assert "Horizon" in text and "n_eff" in text

        # 4) 계산 감사
        page.click('.tab[data-tab="audit"]')
        page.click("#audit-btn")
        page.wait_for_selector("#audit-body table.data", timeout=60_000)
        audit = page.locator("#audit-body").inner_text()
        assert "원본 OHLCV" in audit and "거리" in audit

        # 5) 업로드 경로 — 같은 화면 안에서 파일을 올려 다시 분석
        page.evaluate("document.querySelector('#params details').open = true")  # 데이터 섹션 펼치기
        page.check('input[name="dmode"][value="manual"]')
        page.set_input_files('.file[data-kind="price"]', str(sample_csv))
        page.wait_for_selector('.map[data-kind="price"] select', timeout=60_000)
        page.click("#run-btn")
        page.wait_for_function(
            "document.querySelector('#sources') && document.querySelector('#sources').innerText.includes('Manual Upload')",
            timeout=180_000)
        assert "my_ixic_20y.csv" in page.locator("#sources").inner_text()

        # 6) 다시 열어도 올린 데이터가 그대로 — 파일을 또 고를 필요가 없다
        page.reload(wait_until="networkidle")
        page.wait_for_selector('.map[data-kind="price"] select', timeout=60_000)
        assert page.is_checked('input[name="dmode"][value="manual"]')
        assert "my_ixic_20y.csv" in page.locator("#saved-box").inner_text()
        page.click("#run-btn")
        page.wait_for_function(
            "document.querySelector('#sources') && document.querySelector('#sources').innerText.includes('my_ixic_20y.csv')",
            timeout=180_000)

        # 저장 데이터 지우기도 동작한다
        page.click("#saved-clear")
        page.wait_for_selector("#saved-box", state="hidden", timeout=15_000)
        browser.close()
