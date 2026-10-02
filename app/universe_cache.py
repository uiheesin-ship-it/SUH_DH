"""Dual-sourced candidate universes for the US Finviz screeners.

Finviz throttles/403s the datacenter (GitHub Actions) IP for the heavy stock-pass
query, so the live universe comes back a fraction of its normal size (e.g. 222 vs
the usual ~1,700) and the screener would shrink to a handful of names. To stop the
screeners depending on a single source, get_candidates() runs through three tiers:

  1. live    — the fresh Finviz fetch, when it looks healthy.
  2. snapshot — the last-good universe we persisted from a healthy fetch, reused
                when the live fetch collapses.
  3. bootstrap— when there is no snapshot yet (Finviz has never succeeded since the
                feature shipped), seed one from the last-good committed screener
                results (data/<name>.json) so the fallback is armed even before a
                single healthy Finviz fetch — breaking the chicken-and-egg.

Only the ticker LIST is reused; fresh per-ticker bars are fetched downstream, so a
fallback scan still produces TODAY's prices. The scan self-heals to a full, fresh
universe the moment Finviz recovers (a healthy fetch overwrites the snapshot).

`last_source(name)` reports which tier produced the most recent universe so the
payload/UI can show "running on a cached universe" when Finviz is down.
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data"
_LAST_SOURCE: dict[str, str] = {}


def _path(name: str) -> Path:
    return _DATA / f"{name}_universe.json"


def _save(name: str, rows: list[dict]) -> None:
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


def _bootstrap_from_results(name: str) -> list[dict]:
    """Derive a candidate list from the last-good committed screener results
    (data/<name>.json). Those are POST-analysis survivors (a subset of the full
    candidate universe), but they're real, liquid tickers — a solid seed to keep
    the screener producing fresh-priced results while Finviz is unreachable."""
    try:
        d = json.loads((_DATA / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for s in d.get("stocks") or []:
        t = s.get("ticker")
        if not t:
            continue
        out.append({
            "ticker": t,
            "company": s.get("company_name") or s.get("company"),
            "sector": s.get("sector"),
            "industry": s.get("industry"),
            "market_cap": s.get("market_cap"),
            "price": s.get("current_price"),
            "country": "USA",
            "from_ipo_pass": bool(s.get("is_ipo")),
            "is_etf": bool(s.get("is_etf")),
        })
    return out


def last_source(name: str) -> str:
    """'live' | 'snapshot' | 'bootstrap' for the most recent reconcile(name)."""
    return _LAST_SOURCE.get(name, "live")


def reconcile(name: str, fresh: list[dict], *,
              min_frac: float = 0.5, min_floor: int = 300) -> list[dict]:
    """Pick the candidate list to scan from the live fetch + persisted fallbacks.

    Healthy live fetch (≥ min_floor AND ≥ min_frac of the last-good snapshot) is
    used and persisted. A collapsed fetch falls back to the snapshot, or — if none
    exists yet — bootstraps a seed from the last-good committed results and
    persists that. Returns ``fresh`` only when there is nothing better at all.
    """
    fresh = fresh or []
    snap = _load(name)
    snap_n = len(snap)
    collapsed = (len(fresh) < int(min_floor)
                 or (snap_n > 0 and len(fresh) < snap_n * float(min_frac)))
    if fresh and not collapsed:
        _save(name, fresh)
        _LAST_SOURCE[name] = "live"
        return fresh
    if snap:
        print(f"  {name} universe: live fetch collapsed ({len(fresh)}) — "
              f"reusing last-good snapshot ({snap_n} names)")
        _LAST_SOURCE[name] = "snapshot"
        return snap
    boot = _bootstrap_from_results(name)
    if boot:
        print(f"  {name} universe: live fetch collapsed ({len(fresh)}) and no "
              f"snapshot — bootstrapping seed from last-good results ({len(boot)} names)")
        _save(name, boot)
        _LAST_SOURCE[name] = "bootstrap"
        return boot
    _LAST_SOURCE[name] = "live"
    return fresh
