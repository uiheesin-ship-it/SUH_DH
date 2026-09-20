"""Which screeners a build rescans, by event and by manual selection.

Worth pinning because both failure directions are expensive and neither is
loud. Too eager: a manual "just deploy this" run spends hours re-reading the
market while the concurrency group blocks every deploy queued behind it — that
is exactly what happened before the `scan` input existed. Too lazy: the
dashboard quietly stops refreshing and nothing fails.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
build = importlib.import_module("build")

EXISTING = ROOT / "build.py"                 # any path that exists
MISSING = ROOT / "data" / "__absent__.json"


def groups(monkeypatch, event, skip_base=False, scan=None):
    monkeypatch.delenv("SUH_DH_SCAN", raising=False)
    if scan is not None:
        monkeypatch.setenv("SUH_DH_SCAN", scan)
    return set(build.scan_groups(event, skip_base))


# ---------------- manual dispatch ----------------

def test_manual_run_scans_nothing_by_default(monkeypatch):
    """The default has to be deploy-only: a manual run is nearly always
    "publish this again", and scanning by default is what blocked deploys."""
    assert groups(monkeypatch, "workflow_dispatch") == set()
    assert groups(monkeypatch, "workflow_dispatch", scan="none") == set()


def test_manual_run_selects_one_market(monkeypatch):
    assert groups(monkeypatch, "workflow_dispatch", scan="kr-only") == {"kr"}
    assert groups(monkeypatch, "workflow_dispatch", scan="us-only") == {"us"}
    assert groups(monkeypatch, "workflow_dispatch", scan="all") == {"us", "kr"}


def test_manual_input_is_case_and_space_tolerant(monkeypatch):
    assert groups(monkeypatch, "workflow_dispatch", scan=" US-Only ") == {"us"}


def test_unknown_selection_scans_nothing(monkeypatch):
    """An unrecognised value must fall back to the cheap side. Defaulting a typo
    to a full scan would be a two-hour surprise."""
    assert groups(monkeypatch, "workflow_dispatch", scan="everything") == set()


# ---------------- scheduled and push runs are unchanged ----------------

def test_heavy_cron_still_scans_everything(monkeypatch):
    assert groups(monkeypatch, "schedule") == {"us", "kr"}


def test_fast_crons_still_skip(monkeypatch):
    assert groups(monkeypatch, "schedule", skip_base=True) == set()


def test_push_and_local_runs_never_scan(monkeypatch):
    assert groups(monkeypatch, "push") == set()
    assert groups(monkeypatch, "") == set()


# ---------------- per-screener gate ----------------

def test_screener_scans_only_when_its_market_is_selected(monkeypatch):
    monkeypatch.delenv("SUH_DH_FORCE_FLAT", raising=False)
    monkeypatch.delenv("SUH_DH_FORCE_KRHIGHS", raising=False)
    kr_only = frozenset({"kr"})
    assert build.should_scan("us", "SUH_DH_FORCE_FLAT", EXISTING, kr_only) is False
    assert build.should_scan("kr", "SUH_DH_FORCE_KRHIGHS", EXISTING, kr_only) is True


def test_missing_snapshot_bootstraps_regardless_of_selection(monkeypatch):
    """A newly added screener has no committed snapshot; it must build one even
    on a deploy-only run, or its page ships empty forever."""
    monkeypatch.delenv("SUH_DH_FORCE_FLAT", raising=False)
    assert build.should_scan("us", "SUH_DH_FORCE_FLAT", MISSING, frozenset()) is True


def test_per_screener_force_flag_still_wins(monkeypatch):
    monkeypatch.setenv("SUH_DH_FORCE_FLAT", "1")
    assert build.should_scan("us", "SUH_DH_FORCE_FLAT", EXISTING, frozenset()) is True


# ---------------------------------------------------------- 에셋 캐시 무효화
# 페이지를 고쳐 배포해도 화면이 그대로인 일이 실제로 있었다 — GitHub Pages 가
# 에셋에 캐시 헤더를 붙이는데 <script src="app.js"> 에 버전 표시가 없어서
# 브라우저가 옛 파일을 계속 쓴 것. 조용히 되돌아가기 쉬운 부분이라 고정한다.
def _site(tmp_path, html: str):
    page = tmp_path / "prog" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text(html, encoding="utf-8")
    return page


def test_stamp_adds_version_to_local_assets(tmp_path):
    page = _site(tmp_path, '<link rel="stylesheet" href="style.css" />\n'
                           '<script src="app.js"></script>\n'
                           '<script src="../shared/data-source.js"></script>')
    assert build.stamp_assets(tmp_path, "20260913T131500") == 1
    out = page.read_text(encoding="utf-8")
    assert 'href="style.css?v=20260913T131500"' in out
    assert 'src="app.js?v=20260913T131500"' in out
    assert 'src="../shared/data-source.js?v=20260913T131500"' in out


def test_stamp_replaces_an_existing_version(tmp_path):
    """손으로 붙여 둔 ?v=2 같은 건 빌드 스탬프가 대신한다(중복되지 않게)."""
    page = _site(tmp_path, '<link rel="stylesheet" href="hub.css?v=2" />')
    build.stamp_assets(tmp_path, "20260913T131500")
    assert page.read_text(encoding="utf-8") == \
        '<link rel="stylesheet" href="hub.css?v=20260913T131500" />'


def test_stamp_leaves_external_urls_alone(tmp_path):
    """CDN 주소에 우리 스탬프를 붙이면 캐시만 깨고 얻는 게 없다."""
    html = ('<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>\n'
            '<script src="//example.com/x.js"></script>')
    page = _site(tmp_path, html)
    assert build.stamp_assets(tmp_path, "20260913T131500") == 0
    assert page.read_text(encoding="utf-8") == html


def test_stamp_keeps_fragments_and_skips_other_files(tmp_path):
    page = _site(tmp_path, '<link href="a.css#top" rel="stylesheet">'
                           '<img src="logo.png">')
    build.stamp_assets(tmp_path, "S1")
    out = page.read_text(encoding="utf-8")
    assert 'href="a.css?v=S1#top"' in out
    assert 'src="logo.png"' in out          # css/js 만 대상


# ------------------------------- 신고가 재수집 실패가 빌드를 죽이면 안 된다
# 2026-09-15 빌드에서 Finviz 가 러너를 막았다. 빌드 앞부분의 "목록 먼저 발행"
# 단계는 try 로 감싸여 넘어갔는데, 맨 끝의 재수집(종목별 사유·차트를 덧입히는
# 단계)이 안 감싸여 있어 예외가 새고 빌드가 죽었다 — 그 앞에서 끝낸 스캐너 세
# 개(40분치)가 커밋 단계까지 못 가고 통째로 버려졌다.
def test_late_highs_fetch_failure_does_not_kill_the_build(monkeypatch, tmp_path):
    """Finviz 가 막혀도 빌드는 끝까지 가야 한다 — 앞선 스캔 결과를 지키려고."""
    import json as _json

    from app import screener

    monkeypatch.setenv("SUH_DH_DEMO", "1")
    monkeypatch.setenv("SUH_DH_SCAN", "none")
    monkeypatch.setattr(build, "SITE", tmp_path / "site")
    # **저장소 스냅샷 자리도 옮긴다.** 안 옮기면 이 테스트가 데모 데이터로
    # data/highs.json·meta.json·news.json·us_exchanges.json 을 덮어쓴다 —
    # 실제로 신고가 65종목이 데모 17종목으로 바뀐 채 커밋될 뻔했다.
    monkeypatch.setattr(build, "DATA", tmp_path / "repo-data")
    monkeypatch.setattr(build, "LIMIT", 1)

    # 앞부분(목록 발행)은 성공하고, 맨 끝 재수집만 막힌 상황을 만든다.
    real = screener.get_dashboard
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            return real()
        raise RuntimeError("Finviz screener returned no data")

    monkeypatch.setattr(screener, "get_dashboard", flaky)
    # 한국 낮 시간이면 재수집을 건너뛰므로(커밋된 목록 재사용) 시나리오가 안 산다.
    monkeypatch.setattr(screener, "highs_frozen", lambda: False)

    build.main()          # 예외가 새면 여기서 실패한다

    assert calls["n"] >= 2, "맨 끝 재수집이 아예 호출되지 않아 시나리오가 재현되지 않았다"
    published = tmp_path / "site" / "data" / "highs.json"
    assert published.exists(), "빌드가 신고가 목록을 하나도 안 남겼다"
    data = _json.loads(published.read_text(encoding="utf-8"))
    assert data.get("count", 0) > 0, "재수집 실패 후 앞서 발행한 목록으로 되돌아가지 못했다"


def test_the_build_test_never_touches_the_real_snapshots(monkeypatch, tmp_path):
    """빌드 테스트가 **커밋된 데이터**를 덮어쓰면 안 된다.

    build.main() 은 site/ 와 저장소 data/ 양쪽에 쓴다. 테스트가 SITE 만 tmp 로
    돌려 놓으면 데모 데이터가 실제 대시보드 데이터를 덮어쓴다 — 신고가 65종목이
    데모 17종목으로, us_exchanges 7,084종목이 7종목으로 바뀐 채 커밋될 뻔했다.
    조용히 일어나는 데다 diff 한 줄이라 리뷰에서도 안 보인다.
    """
    import json as _json

    from app import screener

    real = ROOT / "data" / "meta.json"
    before = real.read_text(encoding="utf-8") if real.exists() else None

    monkeypatch.setenv("SUH_DH_DEMO", "1")
    monkeypatch.setenv("SUH_DH_SCAN", "none")
    monkeypatch.setattr(build, "SITE", tmp_path / "site")
    monkeypatch.setattr(build, "DATA", tmp_path / "repo-data")
    monkeypatch.setattr(build, "LIMIT", 1)
    monkeypatch.setattr(screener, "highs_frozen", lambda: False)

    build.main()

    after = real.read_text(encoding="utf-8") if real.exists() else None
    assert after == before, "빌드 테스트가 커밋된 data/meta.json 을 덮어썼다"
    # 그러면서도 제 갈 곳에는 썼어야 한다.
    written = tmp_path / "repo-data" / "meta.json"
    assert written.exists(), "옮겨 놓은 자리에도 안 썼다면 상수가 안 먹은 것이다"
    assert _json.loads(written.read_text(encoding="utf-8")).get("built")
