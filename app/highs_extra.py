"""Extra enrichment + history for the US 52-week-high dashboard.

Three concerns the plain Finviz list doesn't cover, shared by the live API
(screener.get_dashboard), the heavy build (build.py) and the fast updater
(tools/build_highs.py):

  * 거래대금 (turnover) — Finviz's Overview view carries today's Volume, so
    turnover = price × volume (USD). Annotated onto each row.
  * ATH (사상 최고가) — a 52-week high isn't necessarily an all-time high. The
    heavy build knows each name's all-time high from its max-range chart and
    caches it to data/ath.json; every path then flags a row as ATH when its
    price is at/above that cached peak. Names not yet in the cache simply show
    no badge until the next heavy build.
  * 신고가 추이 (history) — one bucket per US trading day: total count, ATH
    count, average change and the per-sector counts. Upserted on every refresh
    (the last write of the day wins → converges to the end-of-session value),
    kept to the most recent ~120 days. Drives the trend charts on the page.

Everything is best-effort: a read-only FS, a missing cache or a bad row never
raises into the build.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ATH_PATH = DATA_DIR / "ath.json"
HISTORY_PATH = DATA_DIR / "highs_history.json"

# Keep roughly a quarter of trading days so the "최근 60거래일" view always has a
# full window with headroom.
HISTORY_KEEP = 120
# Flag ATH when price is within this fraction of the cached all-time high — a
# tiny tolerance so a cent of rounding doesn't drop the badge.
ATH_EPS = 0.999


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def us_trading_date(now: datetime | None = None) -> str:
    """Calendar date in US/Eastern — the bucket a refresh belongs to."""
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        now = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        pass  # fall back to UTC date if tz data is unavailable
    return now.strftime("%Y-%m-%d")


# ---------- ATH cache ----------
def load_ath() -> dict:
    try:
        return json.loads(ATH_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_ath(mapping: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ATH_PATH.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def ath_from_chart(chart: dict) -> float | None:
    """All-time-high price from a max-range chart (prefer highs, else closes)."""
    series = [v for v in (chart.get("high") or chart.get("close") or []) if v is not None]
    return max(series) if series else None


# ---------- row annotation (turnover + ATH flag) ----------
def annotate_rows(rows: list[dict], ath: dict | None = None, demo: bool = False) -> None:
    """Add `turnover` and `ath` to each row in place."""
    ath = load_ath() if ath is None else ath
    for s in rows:
        price = _num(s.get("price"))
        vol = _num(s.get("volume"))
        if s.get("turnover") is None and price is not None and vol is not None:
            s["turnover"] = price * vol
        peak = _num(ath.get(s.get("ticker")))
        if peak is not None and price is not None:
            s["ath"] = price >= peak * ATH_EPS
        elif demo:
            s["ath"] = True   # demo list has no cache — show the badge style
        else:
            s.setdefault("ath", False)


# ---------- history ----------
def _bucket(rows: list[dict], date: str) -> dict:
    changes = [_num(s.get("change_pct")) for s in rows]
    changes = [c for c in changes if c is not None]
    sectors = Counter((s.get("sector") or "Unknown") for s in rows)
    return {
        "date": date,
        "count": len(rows),
        "ath": sum(1 for s in rows if s.get("ath")),
        "avg_change": round(sum(changes) / len(changes), 2) if changes else None,
        "sectors": dict(sectors),
    }


def load_history() -> list[dict]:
    try:
        payload = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return payload.get("days") or []
    except Exception:
        return []


def update_history(rows: list[dict], date: str | None = None) -> dict:
    """Upsert today's bucket into data/highs_history.json; return the payload.

    An empty list is ignored (a Finviz hiccup shouldn't record a 0-count day).
    """
    if not rows:
        return {"days": load_history()}
    date = date or us_trading_date()
    days = [d for d in load_history() if d.get("date") != date]
    days.append(_bucket(rows, date))
    days.sort(key=lambda d: d.get("date") or "")
    days = days[-HISTORY_KEEP:]
    payload = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "days": days}
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload
