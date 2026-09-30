"""Last-good candidate-universe snapshots for the US Finviz screeners.

Finviz occasionally throttles/403s the datacenter (GitHub Actions) IP for the
heavy stock-pass query, so the live universe comes back a fraction of its normal
size (e.g. 222 vs the usual ~1,700) and the screener would shrink to a handful of
names. This mirrors the KR listing fallback in app/krhighs.py: whenever a live
fetch is healthy we persist it as the last-good snapshot; when a fetch collapses
we reuse that snapshot so the scan still runs on a full universe (fresh per-ticker
bars are fetched downstream, so prices stay current — only the ticker LIST is
reused). The scan self-heals to a fresh universe the moment Finviz recovers.
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data"


def _path(name: str) -> Path:
    return _DATA / f"{name}_universe.json"


def _save(name: str, rows: list[dict]) -> None:
    """Persist a last-good universe (best-effort; a read-only FS is fine)."""
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        _path(name).write_text(
            json.dumps({"count": len(rows), "rows": rows}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def _load(name: str) -> list[dict]:
    try:
        return json.loads(_path(name).read_text(encoding="utf-8")).get("rows") or []
    except Exception:
        return []


def reconcile(name: str, fresh: list[dict], *,
              min_frac: float = 0.5, min_floor: int = 300) -> list[dict]:
    """Decide the candidate list to actually scan.

    If ``fresh`` looks healthy (at least ``min_floor`` names AND at least
    ``min_frac`` of the last-good snapshot), persist it as the new snapshot and
    use it. If it collapsed, reuse the last-good snapshot instead so the scan
    still covers a full universe. Falls back to ``fresh`` only when there is no
    usable snapshot.
    """
    fresh = fresh or []
    snap = _load(name)
    snap_n = len(snap)
    collapsed = (len(fresh) < int(min_floor)
                 or (snap_n > 0 and len(fresh) < snap_n * float(min_frac)))
    if fresh and not collapsed:
        _save(name, fresh)
        return fresh
    if snap:
        print(f"  {name} universe: live fetch collapsed ({len(fresh)}) — "
              f"reusing last-good snapshot ({snap_n} names)")
        return snap
    return fresh  # nothing better available
