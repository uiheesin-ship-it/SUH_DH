#!/usr/bin/env python3
"""Extract 최대주주등소유주식변동신고서 rows from DART for a ticker.

Pulls every 최대주주등소유주식변동신고서 (지분공시) filed since a cutoff, parses the
detail table (성명 | 관계 | 종류 | 변동일 | 변동전 | 증감 | 변동후 | 단가 | 변동방법)
row by row, and emits each transaction. A summary filters rows to a given
holder + method (default 미래에셋자산운용 / 장내매수) and sums the quantity.

Run where opendart.fss.or.kr is reachable (GitHub Actions). Needs DART_API_KEY.

  DART_API_KEY=xxxx python tools/dart_holder_changes.py 085620 20260101 미래에셋자산운용 장내
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
OUT = DATA / "dart_holder_changes.json"
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
    m = json.loads(CORP_CACHE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("corp map cache empty.")
    return m


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
    s = s.replace("</tr>", " || ").replace("</TR>", " || ")
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


_DATE = re.compile(r"^(\d{4})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})$")
_NAMEISH = re.compile(r"미래에셋[가-힣A-Za-z()]*|박현주|[가-힣]{2,4}(?:\(주\))?$")


def parse_rows(txt: str) -> list[dict]:
    """Walk the pipe/row-separated table, emitting one dict per 변동 row.

    Carries 성명 forward across merged cells (current holder), and for each
    변동일 cell reads the following numbers (변동전/증감/변동후/단가) + 변동방법.
    """
    cells = [c.strip() for c in re.split(r"\|\||\|", txt)]
    rows: list[dict] = []
    current = None
    for i, c in enumerate(cells):
        if "미래에셋자산운용" in c:
            current = "미래에셋자산운용"
        elif re.fullmatch(_NAMEISH, c) and ("미래에셋" in c or "박현주" in c):
            current = c[:24]
        m = _DATE.match(c)
        if not m:
            continue
        y, mo, da = m.groups()
        window = [w for w in cells[i + 1:i + 12] if w][:9]
        nums: list[int] = []
        for w in window:
            for x in re.findall(r"\d[\d,]{2,}", w):
                v = x.replace(",", "")
                if v.isdigit():
                    nums.append(int(v))
        method = ""
        for w in window:
            if re.search(r"장내매수|장내매도|장외매수|장외매도|시간외|장내|장외|증여|상속|무상|유상|현물|기타취득|처분", w):
                method = w[:24]
                break
        delta = None
        if len(nums) >= 3:
            delta = nums[2] - nums[0]          # 변동후 - 변동전 (authoritative)
        elif len(nums) == 2:
            delta = nums[1]
        rows.append({
            "name": current,
            "date": f"{y}-{int(mo):02d}-{int(da):02d}",
            "delta": delta,
            "method": method,
            "nums": nums[:4],
        })
    return rows


def main() -> None:
    if not KEY:
        raise SystemExit("DART_API_KEY is not set.")
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "085620").strip()
    since = sys.argv[2] if len(sys.argv) > 2 else "20260101"
    name_filter = sys.argv[3] if len(sys.argv) > 3 else "미래에셋자산운용"
    method_filter = sys.argv[4] if len(sys.argv) > 4 else "장내"
    end = date.today().strftime("%Y%m%d")
    corp = load_corp_map().get(ticker)
    if not corp:
        raise SystemExit(f"{ticker}: corp_code not found.")

    # No pblntf_ty filter — enumerate every filing and match by report name.
    filings: list[dict] = []
    for page in range(1, 21):
        url = (f"{BASE}/list.json?crtfc_key={KEY}&corp_code={corp}"
               f"&bgn_de={since}&end_de={end}"
               f"&page_no={page}&page_count=100")
        try:
            js = json.loads(_get(url))
        except Exception:
            break
        if js.get("status") == "013":
            break
        if js.get("status") != "000":
            print(f"  list status {js.get('status')}: {js.get('message')}")
            break
        for it in js.get("list", []):
            nm = it.get("report_nm") or ""
            if ("소유주식변동" in nm) or ("최대주주등소유" in nm):
                filings.append({"rcept_no": (it.get("rcept_no") or "").strip(),
                                "rcept_dt": (it.get("rcept_dt") or "").strip(),
                                "report_nm": nm.strip()})
        if js.get("page_no", 1) >= js.get("total_page", 1):
            break
        time.sleep(0.1)

    all_rows = []
    for f in filings:
        try:
            rows = parse_rows(fetch_doc(f["rcept_no"]))
        except Exception as e:
            rows = [{"parse_error": str(e)}]
        for r in rows:
            r["rcept_no"] = f["rcept_no"]
            r["rcept_dt"] = f["rcept_dt"]
        all_rows.extend(rows)
        time.sleep(0.2)

    # filtered summary: holder + method + 변동일 within the since-year onward, buys only
    yr = since[:4]
    hits = [r for r in all_rows
            if r.get("name") == name_filter
            and method_filter in (r.get("method") or "")
            and (r.get("date") or "")[:4] >= yr
            and (r.get("delta") or 0) > 0]
    # de-dup identical (date, delta) across filings that restate the same tx
    seen = set()
    uniq = []
    for r in sorted(hits, key=lambda x: x["date"]):
        k = (r["date"], r["delta"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    total = sum(r["delta"] for r in uniq)

    result = {
        "ticker": ticker, "corp_code": corp, "_since": since, "_end": end,
        "name_filter": name_filter, "method_filter": method_filter,
        "filings": filings,
        "matched_buys": uniq,
        "matched_total_qty": total,
        "all_rows": all_rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{ticker}: 소유주식변동 공시 {len(filings)}건, {name_filter} {method_filter}매수 "
          f"{len(uniq)}행 합계 {total:,}주")


if __name__ == "__main__":
    main()
