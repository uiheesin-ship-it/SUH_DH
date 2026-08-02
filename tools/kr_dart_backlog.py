#!/usr/bin/env python3
"""Build/refresh data/kr_backlog.json — Korean quarterly 수주잔고 from DART.

Order backlog (수주잔고) is disclosed only inside a company's *periodic report*
(분기/반기/사업보고서), and only by firms that carry a backlog (건설·조선·방산·
기계·플랜트·SI 등). It therefore changes for a company only when that company
files a periodic report — so we never poll the whole ~2,600-name market daily.

Two modes:

  --backfill        One-time sweep. For every ticker (or a candidate seed list),
                    pull ~15 months of periodic filings, parse each report's
                    수주잔고 table, and keep the companies that actually disclose
                    it. Heavy but run once (and re-runnable). ~30–60 min on CI.

  (default)         Daily incremental. ONE market-wide list.json sweep over a
                    small date window returns just the companies that filed a
                    periodic report in that window; parse only those and merge.
                    This is the cheap job the daily workflow runs.

Runs where opendart.fss.or.kr is reachable (GitHub Actions), with a free key in
the DART_API_KEY env var (register at https://opendart.fss.or.kr).

  DART_API_KEY=xxx python tools/kr_dart_backlog.py --backfill
  DART_API_KEY=xxx python tools/kr_dart_backlog.py            # daily, last 2 days
  DART_API_KEY=xxx python tools/kr_dart_backlog.py --days 7   # catch-up window
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import dartdoc  # noqa: E402

OUT = ROOT / "data" / "kr_backlog.json"
MAX_QUARTERS = 8              # keep ~2 years so YoY is computable
BACKFILL_DAYS = 470          # ~15.5 months of filings for the one-time sweep
MARKET = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}
WORKERS = 5                  # concurrent DART document downloads (rate-limit safe)


def _col(df, *names):
    for n in names:
        if n in getattr(df, "columns", []):
            return n
    return None


def load_sector_map() -> dict[str, tuple]:
    """6-digit code -> (sector, industry) from FinanceDataReader's KRX listing.

    Uses the *descriptive* listing ("KRX-DESC"): only that variant carries the
    업종(Sector)/주요제품(Industry) columns. Plain "KRX" is a price snapshot with
    no sector, so it silently mapped every company to 기타. Returns {} on any
    failure so it never blocks the DART run.
    """
    try:
        import FinanceDataReader as fdr
        krx = fdr.StockListing("KRX-DESC")
    except Exception as e:
        print(f"sector map unavailable ({e}); companies will be grouped as 기타")
        return {}
    c_code = _col(krx, "Code", "Symbol")
    c_sec = _col(krx, "Sector")
    c_ind = _col(krx, "Industry")
    out: dict[str, tuple] = {}
    if c_code:
        for _, r in krx.iterrows():
            out[str(r[c_code]).zfill(6)] = (
                (r[c_sec] if c_sec else None), (r[c_ind] if c_ind else None))
    print(f"sector map: {len(out)} codes ({sum(1 for v in out.values() if v[0])} with sector)")
    return out


def _apply_sector(comp: dict, sectors: dict[str, tuple]) -> None:
    sec, ind = sectors.get(comp.get("stock_code", ""), (None, None))
    if sec:
        comp["sector"] = str(sec)
    if ind:
        comp["industry"] = str(ind)


def load_out() -> dict:
    if OUT.exists():
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("companies", {})
                data.setdefault("_meta", {})
                return data
        except Exception:
            pass
    return {"_meta": {}, "companies": {}}


def save_out(data: dict) -> None:
    data["_meta"]["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["_meta"].setdefault(
        "note",
        "수주잔고는 정기보고서 본문 '수주상황' 표에서 추출한 근사치입니다. "
        "표 양식이 회사마다 달라 오차가 있을 수 있으니 각 행의 출처(DART) 링크로 확인하세요.",
    )
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _quarter_entry(f: dict, bl: dict) -> dict:
    period = dartdoc.report_period(f["report_nm"])
    return {
        "period": period,
        "quarter": dartdoc.period_to_quarter(period),
        "rcept_dt": f["rcept_dt"],
        "rcept_no": f["rcept_no"],
        "report_nm": f["report_nm"],
        "source": dartdoc.viewer_url(f["rcept_no"]),
        "backlog_krw": bl.get("backlog_krw"),
        "backlog_raw": bl.get("backlog_raw"),
        "unit": bl.get("unit"),
        "currency": bl.get("currency"),
        "method": bl.get("method"),
        "header": bl.get("header"),
    }


def merge(data: dict, f: dict, entry: dict) -> None:
    """Upsert a company + one quarter (newest amended filing wins per period)."""
    code = f.get("stock_code") or ""
    if not code:
        return
    comp = data["companies"].setdefault(code, {
        "stock_code": code,
        "corp_code": f.get("corp_code", ""),
        "name": f.get("corp_name", ""),
        "market": MARKET.get(f.get("corp_cls", ""), ""),
        "sector": "",
        "quarters": [],
    })
    comp["name"] = f.get("corp_name") or comp.get("name") or code
    if f.get("corp_cls"):
        comp["market"] = MARKET.get(f["corp_cls"], comp.get("market", ""))

    qs = [q for q in comp["quarters"] if q.get("period") != entry["period"]]
    # if same period already present, keep whichever was filed later (amendment)
    prev = next((q for q in comp["quarters"] if q.get("period") == entry["period"]), None)
    if prev and prev.get("rcept_dt", "") > entry.get("rcept_dt", ""):
        return
    qs.append(entry)
    qs.sort(key=lambda q: (q.get("period", ""), q.get("rcept_dt", "")), reverse=True)
    comp["quarters"] = qs[:MAX_QUARTERS]


def process(f: dict, data: dict, verbose: bool = False) -> bool:
    """Fetch one filing's document, extract backlog, merge. True if backlog found."""
    try:
        body = dartdoc.fetch_document(f["rcept_no"])
        bl = dartdoc.extract_backlog(body)
    except Exception as e:
        if verbose:
            print(f"    {f.get('corp_name')} {f['rcept_no']} fetch/parse failed: {e}")
        return False
    if not bl:
        return False
    merge(data, f, _quarter_entry(f, bl))
    if verbose:
        print(f"    + {f.get('corp_name')} {f['report_nm']} "
              f"= {bl.get('backlog_raw')} {bl.get('unit') or ''} ({bl.get('method')})")
    return True


# --------------------------------------------------------------------------- #
SEEN_CAP = 8000              # keep only the most recent rcept_no's (bounds file size)


def run_incremental(days: int, max_docs: int) -> None:
    """Process the window's periodic filings, but bounded so a report-deadline
    day (e.g. mid-Aug 반기보고서) never explodes into an hours-long download.

    We remember every rcept_no already fetched (``_meta.seen``) so nothing is
    re-downloaded, cap document fetches per run at ``max_docs``, and fetch
    already-tracked companies first — so on a heavy day the run stays short and
    simply resumes the leftover the next night(s). A wide window keeps the
    backlog of unprocessed filings in range until it's fully chewed through.
    """
    end = date.today()
    bgn = end - timedelta(days=days)
    filings = dartdoc.market_periodic_filings(
        bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    data = load_out()
    seen = set(data["_meta"].get("seen", []))
    known = data["companies"]
    sectors = load_sector_map()

    todo = [f for f in filings if f.get("stock_code") and f["rcept_no"] not in seen]
    # already-tracked companies first (keep them fresh), then discover new ones.
    todo.sort(key=lambda f: f["stock_code"] not in known)
    print(f"incremental: {len(filings)} filings in last {days}d; "
          f"{len(todo)} new to check (cap {max_docs}/run)")

    hits = processed = 0
    for f in todo:
        if processed >= max_docs:
            print(f"  reached max-docs cap ({max_docs}); "
                  f"{len(todo) - processed} filings will continue next run")
            break
        if process(f, data, verbose=True):
            hits += 1
            _apply_sector(data["companies"][f["stock_code"]], sectors)
        seen.add(f["rcept_no"])            # mark processed (backlog or not)
        processed += 1
        if processed % 20 == 0:
            print(f"  ... {processed}/{min(len(todo), max_docs)}")
        time.sleep(0.15)

    # persist the seen set, most-recent-first (rcept_no is time-ordered).
    data["_meta"]["seen"] = sorted(seen)[-SEEN_CAP:]
    save_out(data)
    print(f"done: {processed} filings checked, {hits} had backlog; "
          f"{len(data['companies'])} companies tracked.")


def _probe_latest(code: str, cc: str, bgn: str, end: str):
    """Fetch a ticker's filing list + parse ONLY its latest report's document.

    Cheap discloser test: most firms don't disclose backlog, so we download one
    document instead of all four. Returns (code, cc, filings, latest_backlog).
    Runs in a worker thread (network + parse only; no shared state).
    """
    try:
        filings = dartdoc.periodic_filings(cc, bgn, end)
    except Exception:
        return code, cc, [], None
    if not filings:
        return code, cc, [], None
    latest = filings[0]
    try:
        bl = dartdoc.extract_backlog(dartdoc.fetch_document(latest["rcept_no"]))
    except Exception:
        bl = None
    return code, cc, filings, bl


def _fetch_one(code: str, cc: str, f: dict):
    """Download + parse a single older filing (worker thread)."""
    try:
        bl = dartdoc.extract_backlog(dartdoc.fetch_document(f["rcept_no"]))
    except Exception:
        bl = None
    return code, cc, f, bl


def run_backfill(candidates: list[str] | None, limit: int | None) -> None:
    corp = dartdoc.load_corp_map()
    sectors = load_sector_map()
    codes = [c for c in (candidates if candidates else sorted(corp)) if corp.get(c)]
    if limit:
        codes = codes[:limit]
    end = date.today().strftime("%Y%m%d")
    bgn = (date.today() - timedelta(days=BACKFILL_DAYS)).strftime("%Y%m%d")
    data = load_out()
    seen = set(data["_meta"].get("seen", []))

    # --- Phase 1: probe each ticker's LATEST report (concurrent) --------------
    print(f"backfill phase 1: probing latest report of {len(codes)} tickers "
          f"(x{WORKERS}) to find backlog disclosers ...")
    disclosers: list[tuple[str, str, list]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_probe_latest, c, corp[c], bgn, end) for c in codes]
        for fut in as_completed(futs):
            code, cc, filings, bl = fut.result()
            done += 1
            if filings:
                seen.add(filings[0]["rcept_no"])
            if bl:
                latest = filings[0]
                latest.update(stock_code=code, corp_code=cc)
                merge(data, latest, _quarter_entry(latest, bl))
                _apply_sector(data["companies"][code], sectors)
                disclosers.append((code, cc, filings))
                print(f"  + discloser: {latest.get('corp_name') or code} "
                      f"[{data['companies'][code].get('sector')}] "
                      f"= {bl.get('backlog_raw')} {bl.get('unit') or ''}")
            if done % 100 == 0:
                print(f"  ... probed {done}/{len(codes)} ({len(disclosers)} disclosers)")
                data["_meta"]["seen"] = sorted(seen)[-SEEN_CAP:]
                save_out(data)

    # --- Phase 2: fetch older quarters for disclosers only (concurrent) -------
    tasks = []
    for code, cc, filings in disclosers:
        for f in filings[1:MAX_QUARTERS]:          # [0] latest already merged
            if f["rcept_no"] in seen:
                continue
            f.update(stock_code=code, corp_code=cc)
            tasks.append((code, cc, f))
    print(f"backfill phase 2: fetching {len(tasks)} past-quarter reports "
          f"for {len(disclosers)} disclosers (x{WORKERS}) ...")
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_fetch_one, code, cc, f) for code, cc, f in tasks]
        for fut in as_completed(futs):
            code, cc, f, bl = fut.result()
            seen.add(f["rcept_no"])
            if bl:
                merge(data, f, _quarter_entry(f, bl))
            done += 1
            if done % 100 == 0:
                print(f"  ... {done}/{len(tasks)} past quarters")
                data["_meta"]["seen"] = sorted(seen)[-SEEN_CAP:]
                save_out(data)

    data["_meta"]["seen"] = sorted(seen)[-SEEN_CAP:]
    save_out(data)
    q = sum(len(c.get("quarters", [])) for c in data["companies"].values())
    print(f"backfill done: {len(disclosers)} disclosers / {len(codes)} scanned; "
          f"{len(data['companies'])} companies, {q} quarters total.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/refresh data/kr_backlog.json from DART")
    ap.add_argument("--backfill", action="store_true",
                    help="one-time full sweep to discover backlog-disclosing firms")
    ap.add_argument("--days", type=int, default=2,
                    help="incremental window in days (default 2)")
    ap.add_argument("--max-docs", type=int, default=250, dest="max_docs",
                    help="incremental: max report documents to fetch per run "
                         "(default 250; caps report-deadline spikes, resumes next run)")
    ap.add_argument("--candidates", type=str, default="",
                    help="backfill only these 6-digit codes (comma-separated or @file)")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of tickers scanned in backfill (0 = all)")
    args = ap.parse_args()

    if not dartdoc.key():
        raise SystemExit("DART_API_KEY is not set (register at opendart.fss.or.kr).")

    if args.backfill:
        cands: list[str] | None = None
        if args.candidates:
            if args.candidates.startswith("@"):
                text = Path(args.candidates[1:]).read_text(encoding="utf-8")
                cands = [c.strip() for c in text.replace(",", "\n").split() if c.strip()]
            else:
                cands = [c.strip() for c in args.candidates.split(",") if c.strip()]
        run_backfill(cands, args.limit or None)
    else:
        run_incremental(args.days, args.max_docs)


if __name__ == "__main__":
    main()
