#!/usr/bin/env python3
"""Collect a ticker's convertible-bond (전환사채/CB) picture from DART.

For the given ticker it pulls:
  1. 전환사채권 발행결정 (cvbdIsDecsn) — each CB tranche: 회차, 발행총액,
     전환가액, 전환청구기간, 전환에 따라 발행할 주식수 (structured API).
  2. 전환청구권행사 disclosures (거래소공시) — every conversion event, parsed for
     회차 / 전환청구 주식수 / 전환가액 / 전환 후 미전환사채 권면총액.

It writes everything (structured issuances + parsed conversions + raw snippets)
to data/dart_cb.json so the remaining (미전환) balance per 회차 can be computed.

Run where opendart.fss.or.kr is reachable (GitHub Actions). Needs DART_API_KEY.

  DART_API_KEY=xxxx python tools/dart_cb.py 340360 20220101
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

KEY = os.environ.get("DART_API_KEY", "").strip()
DATA = Path(__file__).resolve().parent.parent / "data"
CORP_CACHE = DATA / "dart_corp.json"
OUT = DATA / "dart_cb.json"
BASE = "https://opendart.fss.or.kr/api"


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
    if CORP_CACHE.exists():
        m = json.loads(CORP_CACHE.read_text(encoding="utf-8"))
        if m:
            return m
    raise SystemExit("corp map cache missing (data/dart_corp.json).")


def cb_issuances(corp: str, bgn: str, end: str) -> list[dict]:
    """전환사채권 발행결정 records (structured). Returns raw dicts as-is."""
    url = (f"{BASE}/cvbdIsDecsn.json?crtfc_key={KEY}&corp_code={corp}"
           f"&bgn_de={bgn}&end_de={end}")
    try:
        js = json.loads(_get(url))
    except Exception as e:
        return [{"_error": str(e)}]
    if js.get("status") != "000":
        return [{"_status": js.get("status"), "_message": js.get("message")}]
    return js.get("list", [])


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\t\r\n  ]+")


def _text(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            s = raw.decode(enc)
            break
        except Exception:
            s = raw.decode("utf-8", "ignore")
    s = s.replace("</td>", " | ").replace("</TD>", " | ")
    s = _TAG.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _WS.sub(" ", s).strip()


def fetch_doc(rcept_no: str) -> str:
    raw = _get(f"{BASE}/document.xml?crtfc_key={KEY}&rcept_no={rcept_no}",
               timeout=60, retries=3)
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        return " ".join(_text(zf.read(n)) for n in zf.namelist())
    except zipfile.BadZipFile:
        return _text(raw)


_N = r"([0-9][0-9,]*)"


def _num(s: str | None):
    if not s:
        return None
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return None


def parse_conversion(txt: str) -> dict:
    """Parse a 전환청구권행사 filing for 회차 / 주식수 / 전환가 / 미전환 잔액."""
    out: dict[str, object] = {}
    m = re.search(r"회\s*차\s*[:|]?\s*(\d+)", txt)
    if m:
        out["round"] = int(m.group(1))
    m = re.search(r"전환청구\s*주식\s*수[^0-9]{0,12}" + _N, txt)
    if m:
        out["converted_shares"] = _num(m.group(1))
    m = re.search(r"전환가\s*액[^0-9]{0,12}" + _N, txt)
    if m:
        out["conv_price"] = _num(m.group(1))
    # 전환 후 미전환 사채 권면(전자등록)총액
    m = re.search(r"미전환\s*사채[^0-9]{0,30}" + _N, txt)
    if m:
        out["unconverted_face"] = _num(m.group(1))
    m = re.search(r"전환청구\s*금액[^0-9]{0,12}" + _N, txt)
    if m:
        out["converted_amount"] = _num(m.group(1))
    # snippet for verification
    idx = txt.find("미전환")
    if idx < 0:
        idx = txt.find("전환청구")
    if idx >= 0:
        out["raw_snippet"] = txt[max(0, idx - 40):idx + 200]
    return out


def conversion_events(corp: str, bgn: str, end: str) -> list[dict]:
    """전환청구권행사 거래소공시 events, newest first, with parsed fields."""
    events: list[dict] = []
    for page in range(1, 11):
        url = (f"{BASE}/list.json?crtfc_key={KEY}&corp_code={corp}"
               f"&bgn_de={bgn}&end_de={end}&pblntf_ty=I"
               f"&page_no={page}&page_count=100")
        try:
            js = json.loads(_get(url))
        except Exception:
            break
        if js.get("status") == "013":
            break
        if js.get("status") != "000":
            break
        for it in js.get("list", []):
            nm = it.get("report_nm") or ""
            if "전환청구권행사" not in nm:
                continue
            rc = (it.get("rcept_no") or "").strip()
            rec = {"rcept_no": rc, "rcept_dt": (it.get("rcept_dt") or "").strip(),
                   "report_nm": nm.strip()}
            try:
                rec.update(parse_conversion(fetch_doc(rc)))
            except Exception as e:
                rec["parse_error"] = str(e)
            events.append(rec)
            time.sleep(0.2)
        if js.get("page_no", 1) >= js.get("total_page", 1):
            break
        time.sleep(0.1)
    return events


def main() -> None:
    if not KEY:
        raise SystemExit("DART_API_KEY is not set.")
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "340360").strip()
    since = sys.argv[2] if len(sys.argv) > 2 else "20220101"
    end = date.today().strftime("%Y%m%d")
    corp = load_corp_map().get(ticker)
    if not corp:
        raise SystemExit(f"{ticker}: corp_code not found.")

    issuances = cb_issuances(corp, since, end)
    convs = conversion_events(corp, since, end)

    # latest 미전환 권면총액 per round (newest event wins)
    latest_unconv: dict[int, dict] = {}
    for e in sorted(convs, key=lambda x: x.get("rcept_dt", "")):
        r = e.get("round")
        if r is not None and e.get("unconverted_face") is not None:
            latest_unconv[r] = {"unconverted_face": e["unconverted_face"],
                                "as_of": e.get("rcept_dt"),
                                "conv_price": e.get("conv_price")}

    result = {
        "ticker": ticker, "corp_code": corp, "_since": since, "_end": end,
        "issuances": issuances,
        "conversions": sorted(convs, key=lambda x: x.get("rcept_dt", ""), reverse=True),
        "latest_unconverted_by_round": latest_unconv,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{ticker}: 발행결정 {len(issuances)}건, 전환청구권행사 {len(convs)}건 → {OUT}")


if __name__ == "__main__":
    main()
