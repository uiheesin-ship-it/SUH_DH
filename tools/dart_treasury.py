#!/usr/bin/env python3
"""Collect a company's 자기주식 취득 결정 disclosures from DART (structured API).

Uses the 주요사항보고 structured endpoints:
  - tsstkAqDecsn        : 자기주식취득 결정 (직접취득)
  - tsstkAqTrctrCnsDecsn : 자기주식취득 신탁계약 체결 결정
so no document parsing is needed. Loops year by year (default 2018→now) and
writes every decision (이사회결의일 / 취득목적 / 취득예정 주식수·금액 / 기간 /
방법) to data/dart_treasury.json.

Run where opendart.fss.or.kr is reachable (GitHub Actions). Needs DART_API_KEY.

  DART_API_KEY=xxxx python tools/dart_treasury.py 005930 2018
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
OUT = DATA / "dart_treasury.json"
BASE = "https://opendart.fss.or.kr/api"

ENDPOINTS = {
    "직접취득": "tsstkAqDecsn",
    "신탁계약체결": "tsstkAqTrctrCnsDecsn",
}


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


def load_corp_map() -> dict[str, str]:
    m = json.loads(CORP_CACHE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("corp map cache empty.")
    return m


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


# Which raw fields to surface (name → possible API keys, first hit wins).
FIELDS = {
    "이사회결의일": ["bddd"],
    "취득목적": ["aq_pp"],
    "취득방법": ["aq_mth"],
    "취득예정_보통주": ["aqpln_stk_ostk"],
    "취득예정_우선주": ["aqpln_stk_estk"],
    "취득예정금액_보통주": ["aqpln_prc_ostk"],
    "취득예정금액_우선주": ["aqpln_prc_estk"],
    "취득시작": ["aqexpd_bgd", "cntrctcnsprd_bgd"],
    "취득종료": ["aqexpd_edd", "cntrctcnsprd_edd"],
    "신탁계약금액": ["ctr_prc"],
    "위탁중개업자": ["cs_iv_bk"],
}


def tidy(rec: dict, kind: str) -> dict:
    out = {"구분": kind, "rcept_no": rec.get("rcept_no", ""),
           "rcept_dt": rec.get("rcept_no", "")[:8]}
    for label, keys in FIELDS.items():
        for k in keys:
            v = rec.get(k)
            if v not in (None, "", "-"):
                out[label] = v
                break
    out["url"] = (f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rec.get('rcept_no','')}"
                  if rec.get("rcept_no") else "")
    out["_raw"] = rec
    return out


def main() -> None:
    if not KEY:
        raise SystemExit("DART_API_KEY is not set.")
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "005930").strip()
    start_year = int(sys.argv[2]) if len(sys.argv) > 2 else 2018
    this_year = date.today().year
    corp = load_corp_map().get(ticker)
    if not corp:
        raise SystemExit(f"{ticker}: corp_code not found.")

    records: list[dict] = []
    for kind, ep in ENDPOINTS.items():
        for yr in range(start_year, this_year + 1):
            bgn, end = f"{yr}0101", f"{yr}1231"
            for rec in fetch(ep, corp, bgn, end):
                if "_error" in rec or "_status" in rec:
                    print(f"  {ep} {yr}: {rec}")
                    continue
                records.append(tidy(rec, kind))
            time.sleep(0.15)

    records.sort(key=lambda r: r.get("rcept_no", ""))
    result = {"ticker": ticker, "corp_code": corp,
              "_from_year": start_year, "count": len(records),
              "decisions": records}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{ticker}: 자기주식취득 결정 {len(records)}건 → {OUT}")


if __name__ == "__main__":
    main()
