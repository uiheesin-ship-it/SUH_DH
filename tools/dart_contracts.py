#!/usr/bin/env python3
"""Collect '단일판매ㆍ공급계약체결' disclosures from DART for given tickers.

For each ticker it lists the exchange disclosures (거래소공시, pblntf_ty=I) whose
report name is a single-supply/供給 contract, filed on/after a cutoff date, then
opens each filing's document and extracts the three fields the user cares about:

  - 계약금액 (contract amount)
  - 계약상대방 (counterparty)
  - 계약기간 (start ~ end)

Output: data/dart_contracts.json  (+ a flat rows list for the xlsx builder).

Run where opendart.fss.or.kr is reachable (GitHub Actions; the dev sandbox blocks
it). Needs a free key in DART_API_KEY.

  DART_API_KEY=xxxx python tools/dart_contracts.py 420770,064290 20260101
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
OUT = DATA / "dart_contracts.json"
BASE = "https://opendart.fss.or.kr/api"

# report_nm of a single-supply contract filing (and its corrections).
NAME_HIT = re.compile(r"단일판매|공급계약")


def _get(url: str, timeout: int = 25, retries: int = 3) -> bytes:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "suh-dh/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:      # transient timeout / reset
            last = e
            time.sleep(2 * (i + 1))
    raise last


def load_corp_map() -> dict[str, str]:
    if CORP_CACHE.exists():
        m = json.loads(CORP_CACHE.read_text(encoding="utf-8"))
        if m:
            return m
    raw = _get(f"{BASE}/corpCode.xml?crtfc_key={KEY}", timeout=180, retries=6)
    import xml.etree.ElementTree as ET
    zf = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(zf.read(zf.namelist()[0]))
    out: dict[str, str] = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        if len(sc) == 6 and sc.isdigit() and cc:
            out[sc] = cc
    CORP_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def list_contract_filings(corp: str, bgn: str, end: str) -> list[dict]:
    """Return [{rcept_no, rcept_dt, report_nm}] of contract disclosures."""
    hits: list[dict] = []
    for page in range(1, 6):
        url = (f"{BASE}/list.json?crtfc_key={KEY}&corp_code={corp}"
               f"&bgn_de={bgn}&end_de={end}&pblntf_ty=I"
               f"&page_no={page}&page_count=100")
        try:
            js = json.loads(_get(url))
        except Exception:
            break
        st = js.get("status")
        if st == "013":
            break
        if st != "000":
            print(f"    list status {st}: {js.get('message')}")
            break
        for it in js.get("list", []):
            nm = it.get("report_nm") or ""
            if NAME_HIT.search(nm):
                hits.append({
                    "rcept_no": (it.get("rcept_no") or "").strip(),
                    "rcept_dt": (it.get("rcept_dt") or "").strip(),
                    "report_nm": nm.strip(),
                })
        if js.get("page_no", 1) >= js.get("total_page", 1):
            break
        time.sleep(0.1)
    return hits


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\t\r\n  ]+")


def _text(raw: bytes) -> str:
    """Best-effort decode + de-tag a DART filing document to plain text."""
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            s = raw.decode(enc)
            break
        except Exception:
            s = raw.decode("utf-8", "ignore")
    s = s.replace("</td>", " | ").replace("</TD>", " | ")
    s = _TAG.sub(" ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return _WS.sub(" ", s).strip()


def fetch_document_text(rcept_no: str) -> str:
    """Download a filing's original document(s) and return concatenated text."""
    raw = _get(f"{BASE}/document.xml?crtfc_key={KEY}&rcept_no={rcept_no}",
               timeout=60, retries=3)
    # document.xml returns a zip of one or more sub-documents.
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        return " ".join(_text(zf.read(n)) for n in zf.namelist())
    except zipfile.BadZipFile:
        return _text(raw)


_NUM = r"([0-9][0-9,]*)"
_DATE = r"(\d{4}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2})"


def _norm_date(s: str | None) -> str | None:
    if not s:
        return None
    d = re.sub(r"\s", "", s)
    m = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", d)
    if not m:
        return None
    y, mo, da = m.groups()
    return f"{y}-{int(mo):02d}-{int(da):02d}"


def parse_fields(txt: str) -> dict:
    """Pull 계약금액 / 계약상대방 / 계약기간 out of the filing text."""
    out: dict[str, object] = {}

    # 계약금액 — prefer the confirmed amount; take the first big number after label.
    m = re.search(r"계약금액[^0-9]{0,20}" + _NUM, txt)
    if not m:
        m = re.search(r"(?:확정\s*)?계약금액[^0-9]{0,40}" + _NUM, txt)
    if m:
        try:
            out["amount_won"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # 최근 매출액 대비 (%)
    mp = re.search(r"매출액\s*대비[^0-9\-]{0,10}([0-9.]+)\s*%", txt)
    if mp:
        out["pct_of_sales"] = float(mp.group(1))

    # 계약 품목 (장비 종류) — the "판매ㆍ공급계약 내용" cell describes the item.
    mi = re.search(r"공급\s*계약\s*내용\s*[:|]?\s*([^|]{2,80})", txt)
    if not mi:
        mi = re.search(r"계약\s*내용\s*[:|]?\s*([^|]{2,80})", txt)
    if mi:
        item = mi.group(1).strip(" :|-")
        item = re.split(r"(계약내역|계약금액|계약상대|판매ㆍ공급지역|판매·공급지역"
                        r"|주요|계약\(수주\)|최근)", item)[0].strip()
        if len(item) >= 2 and item not in ("-", "–"):
            out["item"] = item[:80]

    # 계약상대방 — capture the cell value after the label up to the next separator.
    mc = re.search(r"계약상대(?:방|자)\s*[:|]?\s*([^|]{1,60})", txt)
    if mc:
        val = mc.group(1).strip(" :|-")
        val = re.split(r"(회사와의|판매|공급|계약내역|주요|확정|최근)", val)[0].strip()
        if val and val not in ("-", "–"):
            out["counterparty"] = val[:60]

    # 계약기간 — two dates, or labelled 시작일/종료일.
    ms = re.search(r"(?:계약\s*)?시작일\s*[:|]?\s*" + _DATE, txt)
    me = re.search(r"(?:계약\s*)?종료일\s*[:|]?\s*" + _DATE, txt)
    if ms:
        out["period_start"] = _norm_date(ms.group(1))
    if me:
        out["period_end"] = _norm_date(me.group(1))
    if "period_start" not in out:
        mr = re.search(r"계약기간[^0-9]{0,20}" + _DATE + r"[^0-9]{0,10}" + _DATE, txt)
        if mr:
            out["period_start"] = _norm_date(mr.group(1))
            out["period_end"] = _norm_date(mr.group(2))

    # 계약(수주)일자
    md = re.search(r"계약\s*\(?수주\)?\s*일자?\s*[:|]?\s*" + _DATE, txt)
    if md:
        out["contract_date"] = _norm_date(md.group(1))

    # keep a short raw snippet for manual verification when parsing is thin.
    if "amount_won" not in out or "period_end" not in out:
        idx = txt.find("계약금액")
        if idx >= 0:
            out["raw_snippet"] = txt[idx:idx + 240]
    return out


def viewer_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def main() -> None:
    if not KEY:
        raise SystemExit("DART_API_KEY is not set (register at opendart.fss.or.kr).")
    tickers = (sys.argv[1] if len(sys.argv) > 1 else "420770,064290").split(",")
    tickers = [t.strip() for t in tickers if t.strip()]
    since = sys.argv[2] if len(sys.argv) > 2 else "20260101"
    end = date.today().strftime("%Y%m%d")

    corp = load_corp_map()
    result: dict[str, object] = {"_since": since, "_generated_end": end, "tickers": {}}
    rows: list[dict] = []
    for t in tickers:
        cc = corp.get(t)
        if not cc:
            print(f"{t}: corp_code 없음 — 건너뜀")
            result["tickers"][t] = {"error": "corp_code_not_found"}
            continue
        filings = list_contract_filings(cc, since, end)
        print(f"{t}: 단일판매·공급계약 공시 {len(filings)}건 (>= {since})")
        recs = []
        for f in filings:
            try:
                txt = fetch_document_text(f["rcept_no"])
                fields = parse_fields(txt)
            except Exception as e:
                fields = {"parse_error": str(e)}
            rec = {**f, **fields, "url": viewer_url(f["rcept_no"])}
            recs.append(rec)
            rows.append({"ticker": t, **rec})
            time.sleep(0.2)
        # newest first
        recs.sort(key=lambda r: r.get("rcept_dt", ""), reverse=True)
        result["tickers"][t] = {"corp_code": cc, "count": len(recs), "contracts": recs}

    result["rows"] = rows
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}  (총 {len(rows)}건)")


if __name__ == "__main__":
    main()
