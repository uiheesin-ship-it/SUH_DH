"""지금 도는 서버가 **디스크의 코드와 같은 코드인가.**

같은 함정에 세 번 걸렸다. `git pull` 로 파일은 새것이 되는데, 이미 떠 있는
서버는 **뜰 때 메모리에 올린 옛 파이썬**을 계속 쓴다. 화면에는 "새 칸이 안
보인다" 로만 보여서 원인을 찾는 데 매번 한참 걸렸다.

추측할 필요가 없는 사실이 둘 있다.

    STARTED      이 모듈을 import 한 시각 = 서버가 코드를 읽어 들인 시각
    code_mtime   app/ 아래 .py 중 가장 최근에 바뀐 파일의 수정 시각

``code_mtime > STARTED`` 면 **파일이 서버보다 새것**이다. 그건 짐작이 아니라
시계 두 개의 비교다. 그때 화면이 "서버를 다시 띄우세요" 라고 말할 수 있다.

git 리비전도 같이 싣는다 — 있으면 어느 커밋인지 바로 보이고, 없어도(zip 으로
받은 경우) 위 비교는 그대로 동작한다.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STARTED = datetime.now(timezone.utc)


def _git(*args: str) -> str | None:
    """git 한 줄. git 이 없거나 zip 배포면 그냥 없다."""
    try:
        out = subprocess.run(["git", "-C", str(APP_DIR.parent), *args],
                             capture_output=True, text=True, timeout=2)
    except Exception:  # noqa: BLE001
        return None
    val = (out.stdout or "").strip()
    return val or None


REV = _git("rev-parse", "--short", "HEAD")
# **브랜치가 진짜 함정이었다.** `git pull` 은 지금 체크아웃된 브랜치를 따라간다.
# 작업이 다른 브랜치에 있으면 pull 은 "Already up to date" 라고 답하고 아무것도
# 안 바뀐다 — 재시작을 아무리 해도 옛 코드가 돈다. 어느 브랜치에 서 있는지
# 화면이 말해 주면 그 자리에서 갈린다.
BRANCH = _git("rev-parse", "--abbrev-ref", "HEAD")


def code_mtime() -> datetime:
    """app/ 아래 .py 중 가장 최근 수정 시각.

    매 요청마다 부르지만 파일 수십 개 stat 이라 비용이 없다. 캐시하면 오히려
    `git pull` 직후의 변화를 놓친다 — 그게 바로 알아채야 할 순간이다.
    """
    newest = 0.0
    for root, dirs, files in os.walk(APP_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                try:
                    newest = max(newest, os.stat(Path(root) / name).st_mtime)
                except OSError:
                    continue
    return datetime.fromtimestamp(newest, timezone.utc)


def info() -> dict:
    """화면이 "서버가 옛 코드로 돈다" 를 **알 수 있게** 하는 최소한의 사실."""
    mtime = code_mtime()
    return {
        "rev": REV,
        "branch": BRANCH,
        "started_at": STARTED.isoformat(timespec="seconds"),
        "code_mtime": mtime.isoformat(timespec="seconds"),
        # 파일이 서버보다 새것 = 받아만 놓고 다시 안 띄웠다.
        "stale": mtime > STARTED,
        "stale_by_min": round(max(0.0, (mtime - STARTED).total_seconds()) / 60, 1),
    }
