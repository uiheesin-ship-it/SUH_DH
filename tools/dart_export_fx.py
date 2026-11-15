#!/usr/bin/env python3
"""Pull 수출/내수 매출 비중 and 원재료 매입 외화(USD) 비중 from DART.

Both figures live in a company's *periodic report* (사업/반기/분기보고서):
  - 수출/내수 split  -> "II. 사업의 내용 > 매출 및 수주상황 (매출실적)" table
  - 원재료 매입 통화 -> 원재료 매입현황 / 환위험(시장위험) 서술

For each ticker this finds the latest periodic report (pblntf_ty=A), downloads
the full document text, and dumps keyword-anchored snippets so the numbers can
be read off. It also best-effort parses 수출/내수/합계 amounts into a ratio.

Run where opendart.fss.or.kr is reachable (GitHub Actions). Needs DART_API_KEY.

  DART_API_KEY=xxxx python tools/dart_export_fx.py 007660,357780
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
from pathlib import Path

KEY = os.environ.get("DART_API_KEY", "").strip()
DATA = Path(__file__).resolve().parent.parent / "data"
CORP_CACHE = DATA / "dart_corp.json"
OUT = DATA / "dart_export_fx.json"
BASE = "https://opendart.fss.or.kr/api"


def _get(url: str, timeout: int = 40, retries: int = 4) -> bytes:
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


def latest_periodic(corp: str) -> dict | None:
    """Most recent 정기보고서 (사업/반기/분기). pblntf_ty=A."""
    url = (f"{BASE}/list.json?crtfc_key={KEY}&corp_code={corp}"
           f"&bgn_de=20240101&end_de=20261231&pblntf_ty=A"
           f"&page_no=1&page_count=100&sort=date&sort_mth=desc")
    js = json.loads(_get(url))
    if js.get("status") != "000":
        print(f"  list status {js.get('status')}: {js.get('message')}")
        return None
    best = None
    for it in js.get("list", []):
        nm = it.get("report_nm") or ""
        if re.search(r"사업보고서|반기보고서|분기보고서", nm) and "기재정정" not in nm[:4]:
            best = {"rcept_no": (it.get("rcept_no") or "").strip(),
                    "rcept_dt": (it.get("rcept_dt") or "").strip(),
                    "report_nm": nm.strip()}
            break
    # fall back to including corrections if nothing clean found
    if best is None:
        for it in js.get("list", []):
            nm = it.get("report_nm") or ""
            if re.search(r"사업보고서|반기보고서|분기보고서", nm):
                best = {"rcept_no": (it.get("rcept_no") or "").strip(),
                        "rcept_dt": (it.get("rcept_dt") or "").strip(),
                        "report_nm": nm.strip()}
                break
    return best


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[\t\r\n   ]+")


def _text(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            s = raw.decode(enc)
            break
        except Exception:
            s = raw.decode("utf-8", "ignore")
    s = s.replace("</td>", " | ").replace("</TD>", " | ")
    s = s.replace("</tr>", " \n ").replace("</TR>", " \n ")
    s = _TAG.sub(" ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return _WS.sub(" ", s).strip()


def fetch_document_text(rcept_no: str) -> str:
    raw = _get(f"{BASE}/document.xml?crtfc_key={KEY}&rcept_no={rcept_no}",
               timeout=90, retries=4)
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        return " ".join(_text(zf.read(n)) for n in zf.namelist())
    except zipfile.BadZipFile:
        return _text(raw)


def snippets(txt: str, patterns: list[str], width: int = 260,
             maxn: int = 6) -> list[str]:
    out: list[str] = []
    seen: set[int] = set()
    for pat in patterns:
        for m in re.finditer(pat, txt):
            a = max(0, m.start() - width)
            b = min(len(txt), m.end() + width)
            # dedupe overlapping windows
            if any(abs(a - s) < 120 for s in seen):
                continue
            seen.add(a)
            out.append(txt[a:b].strip())
            if len(out) >= maxn:
                return out
    return out


def parse_export_ratio(txt: str) -> dict:
    """Best-effort: find 수출/내수/합계 amounts near 매출실적 and compute %."""
    out: dict[str, object] = {}
    # look at the매출실적 region
    region = txt
    mi = re.search(r"매출실적", txt)
    if mi:
        region = txt[mi.start(): mi.start() + 4000]
    # amounts following 수출 / 내수 labels (take the合計 row's largest)
    def grab(label: str) -> list[int]:
        vals = []
        for m in re.finditer(label + r"[^0-9\-]{0,8}([0-9][0-9,]{3,})", region):
            try:
                vals.append(int(m.group(1).replace(",", "")))
            except ValueError:
                pass
        return vals
    exp = grab(r"수\s*출")
    dom = grab(r"내\s*수")
    if exp and dom:
        e, d = max(exp), max(dom)
        if e + d > 0:
            out["export_amt"] = e
            out["domestic_amt"] = d
            out["export_pct_est"] = round(100 * e / (e + d), 1)
    return out


def main() -> None:
    if not KEY:
        print("DART_API_KEY missing"); sys.exit(1)
    tickers = (sys.argv[1] if len(sys.argv) > 1 else "007660,357780").split(",")
    cmap = load_corp_map()
    result = {}
    for t in tickers:
        t = t.strip()
        corp = cmap.get(t)
        print(f"[{t}] corp={corp}")
        if not corp:
            result[t] = {"error": "no corp_code"}; continue
        rep = latest_periodic(corp)
        if not rep:
            result[t] = {"error": "no periodic report"}; continue
        print(f"  {rep['report_nm']} ({rep['rcept_dt']}) {rep['rcept_no']}")
        txt = fetch_document_text(rep["rcept_no"])
        entry = {
            "report_nm": rep["report_nm"],
            "rcept_dt": rep["rcept_dt"],
            "rcept_no": rep["rcept_no"],
            "doc_len": len(txt),
            "export_ratio": parse_export_ratio(txt),
            "snip_sales": snippets(txt, [r"매출실적", r"수\s*출\s*액", r"내\s*수", r"수출비중"]),
            "snip_rawmat": snippets(txt, [r"원재료", r"주요\s*원재료", r"매입\s*현황", r"매입액"]),
            "snip_fx": snippets(txt, [r"환\s*위험", r"외화", r"달러", r"USD", r"환율\s*변동"]),
        }
        result[t] = entry
        time.sleep(0.3)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
