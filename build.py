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

from app import charts, earnings, news, screener

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

    # Flip each program's frontend into static mode.
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    static_cfg = (
        "window.SUH_DH_STATIC = true;\n"
        f'window.SUH_DH_BUILT = "{built}";\n'
    )
    for program in ("highs", "news", "earnings"):
        (SITE / program / "config.js").write_text(static_cfg, encoding="utf-8")

    # Optional: point the static earnings page at an always-on backend so it can
    # fetch *any* ticker (not just the pre-built ones). Set SUH_DH_API_BASE to a
    # hosted FastAPI URL (or your ngrok URL) at build time.
    api_base = os.environ.get("SUH_DH_API_BASE", "").strip()
    if api_base:
        with (SITE / "earnings" / "config.js").open("a", encoding="utf-8") as f:
            f.write(f'window.SUH_DH_API_BASE = "{api_base}";\n')

    # Global news digest (independent of the 52-week-high fetch; never let a
    # news failure abort the highs build or vice versa).
    print("Building global news digest ...")
    try:
        digest = news.get_news()
        write_json(SITE / "data" / "news.json", digest)
        # Also keep a tracked copy at the repo root so the Telegram job can send
        # exactly what the dashboard shows by reading this committed file
        # (no dependency on the published — possibly private — Pages URL).
        write_json(ROOT / "data" / "news.json", digest)
        print(f"  {digest.get('count', 0)} news items selected.")
    except Exception as e:
        print(f"  news digest failed: {e}")
        write_json(
            SITE / "data" / "news.json",
            {"built": built, "count": 0, "items": [], "demo": False,
             "error": "news digest unavailable", "detail": str(e)},
        )

    # Post-earnings drift for the curated watchlist (tickers present in
    # data/guidance.json). Independent of the highs fetch — a failure here must
    # not abort the rest of the build.
    print("Building post-earnings drift for guidance tickers ...")
    try:
        gpath = ROOT / "data" / "guidance.json"
        gdata = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
        guided = [t for t in gdata if not t.startswith("_")] if isinstance(gdata, dict) else []
        # Curated guidance tickers + a default big-tech watchlist so the
        # published site ships with several ready tickers (override with
        # SUH_DH_DRIFT_TICKERS). Drift + EPS-consensus are automatic per ticker;
        # the guidance column fills in only where data/guidance.json has entries.
        default_watch = (
            "MU,NVDA,AAPL,MSFT,GOOGL,GOOG,AMZN,META,AVGO,TSLA,AMD,TSM,ORCL,"
            "NFLX,CRM,QCOM,ASML,ARM,PLTR,SMCI,MRVL,ANET,INTC,ADBE,"
            "COIN,UBER,SHOP,PYPL,DIS,ABNB,PANW,NOW"
        )
        watchlist = [t.strip().upper() for t in
                     os.environ.get("SUH_DH_DRIFT_TICKERS", default_watch).split(",") if t.strip()]
        tickers = list(dict.fromkeys(guided + watchlist))  # de-dupe, keep order
        built_tickers = []
        for t in tickers:
            try:
                write_json(SITE / "data" / "drift" / f"{t}.json", earnings.get_drift(t))
                built_tickers.append(t)
            except Exception as e:
                print(f"  drift {t} failed: {e}")
            time.sleep(0.3)  # be gentle with Yahoo
        write_json(SITE / "data" / "drift" / "_index.json", {"tickers": built_tickers})
        print(f"  {len(built_tickers)} drift tables built.")
    except Exception as e:
        print(f"  drift build failed: {e}")
        write_json(SITE / "data" / "drift" / "_index.json", {"tickers": []})

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
