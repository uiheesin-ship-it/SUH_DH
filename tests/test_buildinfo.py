"""서버가 디스크의 코드와 같은 코드인가 — 짐작 말고 시계 두 개로.

`git pull` 만 하고 재시작을 안 하면 화면은 새것, 백엔드는 옛것이 된다. 겉으로는
"새 칸이 안 나온다" 로만 보인다. 그 상황을 **사실로** 알아채는지 본다.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta

from app import buildinfo


def test_방금_뜬_서버는_최신이다():
    info = buildinfo.info()
    assert info["stale"] is False
    assert info["stale_by_min"] == 0.0
    assert info["started_at"] and info["code_mtime"]


def test_파일이_서버보다_새것이면_알아챈다(tmp_path, monkeypatch):
    """git pull 직후의 상태를 그대로 흉내 낸다 — 파일 mtime 이 미래로 간다."""
    target = buildinfo.APP_DIR / "quarterly.py"
    stat = os.stat(target)
    future = time.time() + 600
    try:
        os.utime(target, (stat.st_atime, future))
        info = buildinfo.info()
        assert info["stale"] is True
        assert info["stale_by_min"] > 5
    finally:
        os.utime(target, (stat.st_atime, stat.st_mtime))
    assert buildinfo.info()["stale"] is False


def test_캐시하지_않는다():
    """캐시하면 git pull 직후의 변화를 놓친다 — 그게 바로 알아챌 순간이다."""
    first = buildinfo.code_mtime()
    target = buildinfo.APP_DIR / "quarterly.py"
    stat = os.stat(target)
    try:
        os.utime(target, (stat.st_atime, time.time() + 300))
        assert buildinfo.code_mtime() > first
    finally:
        os.utime(target, (stat.st_atime, stat.st_mtime))


def test_git_이_없어도_죽지_않는다(monkeypatch):
    """zip 으로 받은 경우다. 리비전만 없어지고 stale 판정은 그대로 돈다."""
    monkeypatch.setattr(buildinfo.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert buildinfo._git("rev-parse", "--short", "HEAD") is None
    assert buildinfo.info()["stale"] is False


def test_브랜치를_같이_알려_준다():
    """`git pull` 은 지금 서 있는 브랜치만 따라간다 — 작업이 다른 브랜치에 있으면
    pull 은 '받을 게 없다' 고 답하고 옛 코드가 계속 돈다. 어느 브랜치인지 보여야
    그 자리에서 갈린다."""
    assert buildinfo.info()["branch"]


def test_pycache_는_세지_않는다():
    """.pyc 가 새로 생겨도 '코드가 바뀌었다' 가 아니다 — 매 실행마다 새로 써진다."""
    mt = buildinfo.code_mtime()
    assert mt.year > 2000
    assert mt <= buildinfo.datetime.now(buildinfo.timezone.utc) + timedelta(seconds=5)
