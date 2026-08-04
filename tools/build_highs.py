#!/usr/bin/env python3
"""Fast, standalone US 52-week-high refresh — the LIST (+ top-N reasons) only.

This is the lightweight half of the "highs stays fresh" design:

  * The heavy full build (build.py) rebuilds the whole site and deploys it to
    GitHub Pages — slow, and only a few times a day.
  * THIS script just re-fetches the new-high list from Finviz, enriches the
    biggest names with their "상승 이유" (news/earnings), and writes
    data/highs.json + data/meta.json to the repo. The highs.yml workflow commits
    those files every ~20 min during the US session, and the static page reads
    them via raw.githubusercontent — so the list refreshes frequently and
    INDEPENDENTLY of the heavy build + Pages deploy (and survives GitHub dropping
    scheduled runs).

Per-ticker charts are intentionally NOT built here (they're the slow part and
change slowly); the full daily build still pre-builds them.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))   # so `from app import ...` works when run as a script

from app import charts, screener  # noqa: E402
# How many of the largest new-high names get their reason (news/earnings)
# enriched. Kept modest so a refresh stays fast (~1-2 min).
REASON_LIMIT = int(os.environ.get("SUH_DH_HIGHS_REASON_LIMIT", "60"))


def _all_stocks(dashboard: dict) -> list[dict]:
    out: list[dict] = []
    for sec in dashboard.get("sectors", []):
        for ind in sec.get("industries", []):
            out.extend(ind.get("stocks", []))
        out.extend(sec.get("stocks", []))
    return out


def main() -> None:
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dashboard = screener.get_dashboard()
    dashboard["built"] = built

    stocks = _all_stocks(dashboard)
    stocks.sort(key=lambda s: s.get("market_cap") or 0, reverse=True)
    enriched = 0
    for s in stocks[:REASON_LIMIT]:
        try:
            s["reason"] = charts.get_reason(s["ticker"])
        except Exception as e:
            print(f"  reason {s['ticker']} failed: {e}")
            s["reason"] = {"news": [], "earnings_recent": False, "earnings_date": None}
        enriched += 1
        time.sleep(0.3)  # be gentle with the data source

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "highs.json").write_text(json.dumps(dashboard, ensure_ascii=False), encoding="utf-8")
    (data_dir / "meta.json").write_text(
        json.dumps({"built": built, "count": dashboard.get("count", 0)}, ensure_ascii=False),
        encoding="utf-8")
    print(f"highs refreshed: {dashboard.get('count', 0)} stocks, "
          f"{enriched} reasons, built {built}")


if __name__ == "__main__":
    main()
