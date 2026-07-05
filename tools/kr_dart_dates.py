#!/usr/bin/env python3
"""Populate Korean earnings dates in data/kr_earnings.json from OpenDART.

Korean quarterly earnings *dates* aren't in the free price APIs, but DART (the
FSS electronic disclosure system) records every company's preliminary-earnings
filing — 영업(잠정)실적(공정공시) — with an official receipt date (접수일자) that
is exactly the market-moving announcement date. This script pulls those dates
for every registered KR ticker via the OpenDART REST API and writes the most
recent ~10 quarters per ticker into data/kr_earnings.json.

Run it in an environment that can reach opendart.fss.or.kr (e.g. GitHub Actions;
the sandbox proxy blocks it). Needs a free API key in the DART_API_KEY env var
(register at https://opendart.fss.or.kr → 인증키 신청).

  DART_API_KEY=xxxxx python tools/kr_dart_dates.py
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from pathlib import Path

KEY = os.environ.get("DART_API_KEY", "").strip()
KR_FILE = Path(__file__).resolve().parent.parent / "data" / "kr_earnings.json"
BASE = "https://opendart.fss.or.kr/api"
YEARS_BACK = 1150            # ~3 years, enough for ~8-10 quarters
MAX_DATES = 10
# A preliminary-earnings filing's report name contains 잠정 (영업(잠정)실적…).
MATCH = "잠정"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "suh-dh/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()


def load_corp_map() -> dict[str, str]:
    """Map 6-digit stock code -> 8-digit DART corp_code (from corpCode.xml zip)."""
    raw = _get(f"{BASE}/corpCode.xml?crtfc_key={KEY}")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(zf.read(zf.namelist()[0]))
    out: dict[str, str] = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        if len(sc) == 6 and sc.isdigit() and cc:
            out[sc] = cc
    return out


def preliminary_dates(corp_code: str, bgn: str, end: str) -> list[str]:
    """Receipt dates (YYYY-MM-DD) of a company's 잠정실적 filings, newest first."""
    dates: set[str] = set()
    for page in range(1, 5):
        url = (f"{BASE}/list.json?crtfc_key={KEY}&corp_code={corp_code}"
               f"&bgn_de={bgn}&end_de={end}&pblntf_ty=I"
               f"&page_no={page}&page_count=100")
        try:
            js = json.loads(_get(url))
        except Exception:
            break
        status = js.get("status")
        if status == "013":       # no matching data
            break
        if status != "000":       # 020 rate limit, 011 usage, etc.
            print(f"    DART status {status}: {js.get('message')}")
            break
        for it in js.get("list", []):
            if MATCH in (it.get("report_nm") or ""):
                rd = (it.get("rcept_dt") or "").strip()
                if len(rd) == 8 and rd.isdigit():
                    dates.add(f"{rd[:4]}-{rd[4:6]}-{rd[6:]}")
        if js.get("page_no", 1) >= js.get("total_page", 1):
            break
        time.sleep(0.1)
    return sorted(dates, reverse=True)[:MAX_DATES]


def main() -> None:
    if not KEY:
        raise SystemExit("DART_API_KEY is not set (register at opendart.fss.or.kr).")
    data = json.loads(KR_FILE.read_text(encoding="utf-8"))
    tickers = [t for t in data if not t.startswith("_")]
    corp = load_corp_map()
    print(f"corp map: {len(corp)} stock codes; {len(tickers)} tickers to update")

    end = date.today().strftime("%Y%m%d")
    bgn = (date.today() - timedelta(days=YEARS_BACK)).strftime("%Y%m%d")
    updated = missing = 0
    for i, t in enumerate(tickers, 1):
        code = t.split(".")[0]
        cc = corp.get(code)
        if not cc:
            missing += 1
            continue
        try:
            ds = preliminary_dates(cc, bgn, end)
        except Exception as e:
            print(f"  {t} failed: {e}")
            ds = []
        if ds:
            data[t]["dates"] = ds
            updated += 1
        if i % 25 == 0:
            print(f"  ... {i}/{len(tickers)} processed")
        time.sleep(0.08)

    KR_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done: {updated} tickers got DART dates, {missing} had no corp_code.")


if __name__ == "__main__":
    main()
