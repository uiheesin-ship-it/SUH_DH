#!/usr/bin/env python3
"""Fetch 회사분할/분할합병 결정 disclosures from DART (structured, full dump).

Uses the 주요사항보고 structured endpoints cmpDvDecsn (회사분할결정) and
cmpDvmgDecsn (회사분할합병결정) for a ticker over a date range and dumps every
field (분할방법/분할비율/존속·신설회사/분할기일/재상장 등) to data/dart_split.json.

Run where opendart.fss.or.kr is reachable (GitHub Actions). Needs DART_API_KEY.

  DART_API_KEY=xxxx python tools/dart_split.py 035720 20260801 20260831
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

KEY = os.environ.get("DART_API_KEY", "").strip()
DATA = Path(__file__).resolve().parent.parent / "data"
CORP_CACHE = DATA / "dart_corp.json"
OUT = DATA / "dart_split.json"
BASE = "https://opendart.fss.or.kr/api"

ENDPOINTS = {"회사분할결정": "cmpDvDecsn", "회사분할합병결정": "cmpDvmgDecsn"}


def _get(url: str, timeout: int = 25, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "suh-dh/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def fetch(endpoint: str, corp: str, bgn: str, end: str) -> list[dict]:
    url = (f"{BASE}/{endpoint}.json?crtfc_key={KEY}&corp_code={corp}"
           f"&bgn_de={bgn}&end_de={end}")
    try:
        js = json.loads(_get(url))
    except Exception as e:
        return [{"_error": str(e)}]
    st = js.get("status")
    if st == "013":
        return []
    if st != "000":
        return [{"_status": st, "_message": js.get("message")}]
    return js.get("list", [])


def main() -> None:
    if not KEY:
        raise SystemExit("DART_API_KEY is not set.")
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "035720").strip()
    bgn = sys.argv[2] if len(sys.argv) > 2 else "20260101"
    end = sys.argv[3] if len(sys.argv) > 3 else date.today().strftime("%Y%m%d")
    corp = json.loads(CORP_CACHE.read_text(encoding="utf-8")).get(ticker)
    if not corp:
        raise SystemExit(f"{ticker}: corp_code not found.")

    out = {"ticker": ticker, "corp_code": corp, "bgn": bgn, "end": end, "records": []}
    for kind, ep in ENDPOINTS.items():
        for rec in fetch(ep, corp, bgn, end):
            if "_error" in rec or "_status" in rec:
                print(f"  {ep}: {rec}")
                continue
            rec["_kind"] = kind
            rec["_url"] = (f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
                           f"{rec.get('rcept_no','')}")
            out["records"].append(rec)
        time.sleep(0.15)

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{ticker}: 분할/분할합병 결정 {len(out['records'])}건 → {OUT}")


if __name__ == "__main__":
    main()
