#!/usr/bin/env python3
"""Generate the static dashboard into ./site for GitHub Pages.

Run daily by .github/workflows/daily.yml. It fetches the 52-week-high list
(with reasons embedded) and per-ticker chart data, then copies the frontend.
The same frontend also runs against the live FastAPI backend locally; a
generated config.js flips it into "static" mode here.

Env:
  SUH_DH_BUILD_LIMIT  max tickers to fetch charts/reasons for (default 150)
  SUH_DH_DEMO=1       use sample data (for testing the build offline)
"""

from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app import charts, screener

ROOT = Path(__file__).parent
SITE = ROOT / "site"
STATIC = ROOT / "app" / "static"
LIMIT = int(os.environ.get("SUH_DH_BUILD_LIMIT", "150"))


def _all_stocks(dashboard: dict) -> list[dict]:
    out = []
    for sec in dashboard["sectors"]:
        for ind in sec["industries"]:
            out.extend(ind["stocks"])
        out.extend(sec["stocks"])
    return out


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    # Copy frontend (hub + highs program) into the site root.
    shutil.copytree(STATIC, SITE)

    # Flip the frontend into static mode.
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (SITE / "highs" / "config.js").write_text(
        "window.SUH_DH_STATIC = true;\n"
        f'window.SUH_DH_BUILT = "{built}";\n',
        encoding="utf-8",
    )

    print(f"Fetching 52-week highs (limit={LIMIT}) ...")
    dashboard = screener.get_dashboard()
    stocks = _all_stocks(dashboard)
    # Most important (largest) names first so we never run out of budget on them.
    stocks.sort(key=lambda s: s.get("market_cap") or 0, reverse=True)
    print(f"  {len(stocks)} tickers found.")

    fetched = 0
    for s in stocks[:LIMIT]:
        ticker = s["ticker"]
        try:
            s["reason"] = charts.get_reason(ticker)
        except Exception as e:
            print(f"  reason {ticker} failed: {e}")
            s["reason"] = {"news": [], "earnings_recent": False, "earnings_date": None}
        try:
            chart = charts.get_chart(ticker, "max")
            write_json(SITE / "data" / "chart" / f"{ticker}.json", chart)
        except Exception as e:
            print(f"  chart {ticker} failed: {e}")
        fetched += 1
        if fetched % 20 == 0:
            print(f"  ... {fetched} processed")
        time.sleep(0.3)  # be gentle with Yahoo

    # Stocks beyond the limit still appear in the list (without reason/chart).
    write_json(SITE / "data" / "highs.json", dashboard)
    write_json(
        SITE / "data" / "meta.json",
        {"built": built, "count": dashboard["count"], "charts": fetched},
    )
    print(f"Done. Built {built}, {fetched} charts, site -> {SITE}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
