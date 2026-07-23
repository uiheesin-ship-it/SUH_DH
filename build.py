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

from app import charts, earnings, kr, news, screener

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
    for program in ("highs", "news", "earnings", "kr", "base", "krhighs", "krhighs60", "krbase", "backlog"):
        (SITE / program / "config.js").write_text(static_cfg, encoding="utf-8")

    # Optional: point the static earnings/kr pages at an always-on backend so
    # they can fetch *any* ticker (not just the pre-built ones). Set
    # SUH_DH_API_BASE to a hosted FastAPI URL (or your ngrok URL) at build time.
    api_base = os.environ.get("SUH_DH_API_BASE", "").strip()
    if api_base:
        # highs: real-time refresh. earnings/kr: any-ticker. base: chart fallback
        # for setups whose chart wasn't pre-built on a fast (scan-skipped) build.
        for program in ("earnings", "kr", "highs", "base", "krhighs", "krhighs60", "krbase", "backlog"):
            with (SITE / program / "config.js").open("a", encoding="utf-8") as f:
                f.write(f'window.SUH_DH_API_BASE = "{api_base}";\n')

    # Tickers that have curated guidance data — for the earnings side panel.
    # Grouped by the watchlist's sector order (names omitted in the UI).
    write_json(SITE / "data" / "guidance_tickers.json",
               {"tickers": earnings.guidance_tickers(),
                "groups": earnings.guidance_groups()})

    # Curated Korean tickers (grouped by sector) + their post-earnings drift.
    write_json(SITE / "data" / "kr_tickers.json",
               {"tickers": kr.kr_tickers(), "groups": kr.kr_groups()})
    # Pre-build only the curated-date tickers; the wider registered universe
    # (KOSPI 200 etc.) loads live via the backend (auto-fetches dates from Yahoo).
    print("Building Korean post-earnings drift ...")
    kr_built = []
    for t in kr.kr_prebuild_tickers():
        try:
            write_json(SITE / "data" / "kr" / f"{t}.json", kr.get_kr_drift(t))
            kr_built.append(t)
        except Exception as e:
            print(f"  kr drift {t} failed: {e}")
        time.sleep(0.3)  # be gentle with Yahoo
    write_json(SITE / "data" / "kr" / "_index.json", {"tickers": kr_built})
    print(f"  {len(kr_built)} Korean drift tables built (of {len(kr.kr_tickers())} registered).")

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
        # The full curated watchlist (semiconductors, big tech, optical, AI,
        # health, software, finance/consumer, defense, power, space). Pre-built
        # here so the published site ships these ready-to-load; the Stooq/NASDAQ
        # fallbacks in app/charts.py + app/earnings.py cover any other ticker.
        default_watch = (
            "MU,NVDA,AAPL,MSFT,GOOGL,GOOG,AMZN,META,AVGO,TSLA,AMD,TSM,ORCL,"
            "NFLX,CRM,QCOM,ASML,ARM,PLTR,SMCI,MRVL,ANET,INTC,ADBE,COIN,UBER,"
            "SHOP,PYPL,DIS,ABNB,PANW,NOW,SNDK,WDC,STX,AMAT,LRCX,KLAC,FORM,TER,"
            "TTMI,LITE,COHR,CIEN,AAOI,SITM,RMBS,AXTI,TSEM,ADI,TXN,MPWR,ON,WULF,"
            "NVTS,VICR,DELL,UMICY,ABBV,WMT,COST,ULTA,AAL,CRCL,SNOW,TEAM,CRWD,"
            "TWLO,APP,RDDT,INOD,POWL,HUBB,TLN,CEG,BWXT,OKLO,FSLR,NXT,ENPH,SEDG,"
            "ASTS,RKLB,LUNR,BKSY,DXYZ,ARBE,RR,SERV,RGTI,IONQ"
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

    # Base screener. The scan is HEAVY (2y OHLCV for the whole candidate
    # universe) and Yahoo throttling makes its runtime unpredictable, so we only
    # run it on scheduled/manual builds (or the very first time). Ordinary code
    # pushes reuse the committed data/base.json so they deploy in a couple of
    # minutes instead of waiting 10-15 min for a rescan. Force with
    # SUH_DH_FORCE_BASE=1.
    repo_base = ROOT / "data" / "base.json"
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    # SUH_DH_SKIP_BASE=1 forces reuse of the committed base.json even on a
    # scheduled run. The frequent intraday cron sets this so those builds stay
    # fast (the base scan is the single heaviest step, ~10-20 min); the 6-hourly
    # cron and manual dispatch leave it unset, so the base screen still refreshes.
    skip_base = os.environ.get("SUH_DH_SKIP_BASE", "") == "1"
    scan_base = (
        os.environ.get("SUH_DH_FORCE_BASE", "") == "1"
        or (not skip_base and event in ("schedule", "workflow_dispatch"))
        or not repo_base.exists()
    )
    if scan_base:
        print("Building base screener (full scan) ...")
        try:
            from app import base as base_screener

            payload = base_screener.run_scan(progress=True)
            write_json(SITE / "data" / "base.json", payload)
            write_json(repo_base, payload)  # persist so push builds can reuse it
            chart_limit = int(os.environ.get("SUH_DH_BASE_CHART_LIMIT", "60"))
            for s in payload.get("stocks", [])[:chart_limit]:
                t = s["ticker"]
                cp = SITE / "data" / "chart" / f"{t}.json"
                if cp.exists():
                    continue
                try:
                    write_json(cp, charts.get_chart(t, "max"))
                except Exception as e:
                    print(f"  base chart {t} failed: {e}")
                time.sleep(0.3)
            print(f"  base screen: {payload.get('count')} setups "
                  f"(universe {payload.get('universe_size')}).")
        except Exception as e:
            print(f"  base screen failed: {e}")
            if repo_base.exists():
                shutil.copyfile(repo_base, SITE / "data" / "base.json")
            else:
                write_json(SITE / "data" / "base.json",
                           {"built": built, "count": 0, "universe_size": 0, "stocks": [],
                            "demo": False, "error": "base screen unavailable", "detail": str(e)})
    elif repo_base.exists():
        print("Reusing committed data/base.json (skipping base scan on push) ...")
        shutil.copyfile(repo_base, SITE / "data" / "base.json")

    # Korean 52-week highs (KOSPI+KOSDAQ). Also heavy (per-ticker OHLCV), so it
    # follows the same cadence as the base screen: full scan on the 6-hourly cron
    # / manual dispatch, reuse the committed snapshot on pushes and intraday crons.
    repo_krh = ROOT / "data" / "krhighs.json"
    scan_krh = (
        os.environ.get("SUH_DH_FORCE_KRHIGHS", "") == "1"
        or (not skip_base and event in ("schedule", "workflow_dispatch"))
        or not repo_krh.exists()
    )
    if scan_krh:
        print("Building Korean 52-week highs (full scan) ...")
        try:
            from app import krhighs

            kr_dash = krhighs.get_dashboard()
            write_json(SITE / "data" / "krhighs.json", kr_dash)
            write_json(repo_krh, kr_dash)
            # Pre-build charts for the biggest new-high names via FDR (same-day),
            # keyed by 6-digit code (matches the frontend's /api/krchart lookup).
            from app import krdata
            kr_stocks = _all_stocks(kr_dash)
            kr_stocks.sort(key=lambda s: s.get("market_cap") or 0, reverse=True)
            for s in kr_stocks[:int(os.environ.get("SUH_DH_KRHIGHS_CHART_LIMIT", "40"))]:
                code = s.get("ticker")
                if not code:
                    continue
                cp = SITE / "data" / "chart" / f"{code}.json"
                if cp.exists():
                    continue
                try:
                    write_json(cp, krdata.kr_chart(code, s.get("market")))
                except Exception as e:
                    print(f"  kr chart {code} failed: {e}")
                time.sleep(0.2)
            print(f"  KR highs: {kr_dash.get('count')} stocks.")
        except Exception as e:
            print(f"  KR highs failed: {e}")
            if repo_krh.exists():
                shutil.copyfile(repo_krh, SITE / "data" / "krhighs.json")
            else:
                write_json(SITE / "data" / "krhighs.json",
                           {"count": 0, "sectors": [], "demo": False,
                            "error": "KR highs unavailable", "detail": str(e)})
    elif repo_krh.exists():
        print("Reusing committed data/krhighs.json (skipping KR scan on push) ...")
        shutil.copyfile(repo_krh, SITE / "data" / "krhighs.json")

    # Korean 60-trading-day highs — same universe/cadence as krhighs above, just a
    # shorter look-back window. Same full-scan-on-cron / reuse-on-push pattern.
    repo_krh60 = ROOT / "data" / "krhighs60.json"
    scan_krh60 = (
        os.environ.get("SUH_DH_FORCE_KRHIGHS60", "") == "1"
        or (not skip_base and event in ("schedule", "workflow_dispatch"))
        or not repo_krh60.exists()
    )
    if scan_krh60:
        print("Building Korean 60-day highs (full scan) ...")
        try:
            from app import krhighs60

            kr60_dash = krhighs60.get_dashboard()
            write_json(SITE / "data" / "krhighs60.json", kr60_dash)
            write_json(repo_krh60, kr60_dash)
            # Pre-build charts for the biggest new-high names (Yahoo .KS/.KQ).
            kr60_stocks = _all_stocks(kr60_dash)
            kr60_stocks.sort(key=lambda s: s.get("market_cap") or 0, reverse=True)
            for s in kr60_stocks[:int(os.environ.get("SUH_DH_KRHIGHS60_CHART_LIMIT", "40"))]:
                sym = s.get("yahoo")
                if not sym:
                    continue
                cp = SITE / "data" / "chart" / f"{sym}.json"
                if cp.exists():
                    continue
                try:
                    write_json(cp, charts.get_chart(sym, "max"))
                except Exception as e:
                    print(f"  kr60 chart {sym} failed: {e}")
                time.sleep(0.3)
            print(f"  KR 60d highs: {kr60_dash.get('count')} stocks.")
        except Exception as e:
            print(f"  KR 60d highs failed: {e}")
            if repo_krh60.exists():
                shutil.copyfile(repo_krh60, SITE / "data" / "krhighs60.json")
            else:
                write_json(SITE / "data" / "krhighs60.json",
                           {"count": 0, "sectors": [], "demo": False,
                            "error": "KR 60d highs unavailable", "detail": str(e)})
    elif repo_krh60.exists():
        print("Reusing committed data/krhighs60.json (skipping KR scan on push) ...")
        shutil.copyfile(repo_krh60, SITE / "data" / "krhighs60.json")

    # Korean base screener (same heavy cadence as the US base screen).
    repo_krb = ROOT / "data" / "krbase.json"
    scan_krb = (
        os.environ.get("SUH_DH_FORCE_KRBASE", "") == "1"
        or (not skip_base and event in ("schedule", "workflow_dispatch"))
        or not repo_krb.exists()
    )
    if scan_krb:
        print("Building Korean base screener (full scan) ...")
        try:
            from app import base as base_screener

            payload = base_screener.run_scan_kr(progress=True)
            write_json(SITE / "data" / "krbase.json", payload)
            write_json(repo_krb, payload)
            from app import krdata
            for s in payload.get("stocks", [])[:int(os.environ.get("SUH_DH_KRBASE_CHART_LIMIT", "40"))]:
                code = s.get("ticker")
                if not code:
                    continue
                cp = SITE / "data" / "chart" / f"{code}.json"
                if cp.exists():
                    continue
                try:
                    write_json(cp, krdata.kr_chart(code, s.get("market")))
                except Exception as e:
                    print(f"  krbase chart {code} failed: {e}")
                time.sleep(0.2)
            print(f"  KR base screen: {payload.get('count')} setups "
                  f"(universe {payload.get('universe_size')}).")
        except Exception as e:
            print(f"  KR base screen failed: {e}")
            if repo_krb.exists():
                shutil.copyfile(repo_krb, SITE / "data" / "krbase.json")
            else:
                write_json(SITE / "data" / "krbase.json",
                           {"built": built, "count": 0, "universe_size": 0, "stocks": [],
                            "demo": False, "error": "KR base screen unavailable", "detail": str(e)})
    elif repo_krb.exists():
        print("Reusing committed data/krbase.json (skipping KR base scan on push) ...")
        shutil.copyfile(repo_krb, SITE / "data" / "krbase.json")

    # Ensure EVERY build (including fast reuse builds that don't rescan) ships
    # same-day KR charts, so the KR pages never depend on the possibly-stale
    # hosted backend. Charts already written by the scan blocks above are skipped
    # via cp.exists(); reuse builds fill them in fresh via FDR (same-day, Naver).
    # Code-keyed to match the KR frontends' /api/krchart lookup.
    try:
        from app import krdata

        seen, picks = set(), []
        for fn in ("krbase.json", "krhighs.json", "krhighs60.json"):
            fp = SITE / "data" / fn
            if not fp.exists():
                continue
            try:
                snap = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows = snap.get("stocks") if snap.get("stocks") else (
                _all_stocks(snap) if snap.get("sectors") else [])
            for s in rows:
                code = s.get("ticker")
                if code and code not in seen:
                    seen.add(code)
                    picks.append((s.get("market_cap") or 0, code, s.get("market")))
        picks.sort(key=lambda p: p[0], reverse=True)
        limit = int(os.environ.get("SUH_DH_KR_CHART_LIMIT", "60"))
        fresh = 0
        for _, code, market in picks[:limit]:
            cp = SITE / "data" / "chart" / f"{code}.json"
            if cp.exists():
                continue
            try:
                write_json(cp, krdata.kr_chart(code, market))
                fresh += 1
            except Exception as e:
                print(f"  kr chart {code} failed: {e}")
            time.sleep(0.15)
        print(f"  KR charts ensured ({fresh} freshly built of top {min(limit, len(picks))}).")
    except Exception as e:
        print(f"  KR chart prebuild step failed: {e}")

    # Korean order backlog (수주잔고). Unlike the scans above this is NOT built
    # here: tools/kr_dart_backlog.py (the kr-backlog workflow) fetches it from
    # DART and commits data/kr_backlog.json. The dashboard build just publishes
    # the committed snapshot so GitHub Pages can read it statically.
    repo_bl = ROOT / "data" / "kr_backlog.json"
    try:
        from app import backlog as backlog_mod

        # get_dashboard() reshapes the stored map into the list view + QoQ/YoY the
        # frontend reads (no network — it just reads the committed file).
        write_json(SITE / "data" / "kr_backlog.json", backlog_mod.get_dashboard())
        print(f"Publishing kr_backlog ({'present' if repo_bl.exists() else 'empty'}) ...")
    except Exception as e:
        print(f"  kr_backlog publish failed: {e}")
        write_json(SITE / "data" / "kr_backlog.json",
                   {"updated": None, "count": 0, "companies": [], "demo": False,
                    "note": "아직 수주잔고 데이터가 없습니다. kr-backlog 워크플로를 실행하세요."})

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
