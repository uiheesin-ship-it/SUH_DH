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


# One row of the 전환청구권행사 summary table:
#   회차 | 발행당시 권면총액 | KRW… | 신고일 현재 미전환사채 잔액 | KRW… | 전환가액 | 전환가능 주식수
_ROW = re.compile(
    r"(\d{1,2})\s*\|\s*([\d,]{4,})\s*\|\s*KRW[^|]*\|\s*([\d,]+)\s*\|\s*KRW[^|]*"
    r"\|\s*([\d,]+)\s*\|\s*([\d,]+)")


def parse_conversion(txt: str) -> dict:
    """Parse a 전환청구권행사 filing's table into per-회차 rows.

    Returns {"rounds": [{round, issued_face, unconverted_face, conv_price,
    convertible_shares}]}. The disclosure itself reports 전환가능 주식수, so no
    division is needed.
    """
    rows = []
    for m in _ROW.finditer(txt):
        rows.append({
            "round": int(m.group(1)),
            "issued_face": _num(m.group(2)),
            "unconverted_face": _num(m.group(3)),
            "conv_price": _num(m.group(4)),
            "convertible_shares": _num(m.group(5)),
        })
    out: dict[str, object] = {"rounds": rows}
    if not rows:  # keep a snippet when the table shape didn't match
        idx = txt.find("미전환")
        if idx < 0:
            idx = txt.find("전환청구")
        if idx >= 0:
            out["raw_snippet"] = txt[max(0, idx - 40):idx + 400]
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

    # latest table row per round (newest 전환청구권행사 filing wins)
    latest: dict[int, dict] = {}
    for e in sorted(convs, key=lambda x: x.get("rcept_dt", "")):
        for row in e.get("rounds", []):
            r = row.get("round")
            if r is not None:
                latest[r] = {**row, "as_of": e.get("rcept_dt")}

    # rounds that never had a conversion filing → full 발행총액 still outstanding
    for iss in issuances:
        tm = iss.get("bd_tm")
        if not (isinstance(tm, str) and tm.isdigit()):
            continue
        r = int(tm)
        if r not in latest:
            latest[r] = {
                "round": r,
                "issued_face": _num(iss.get("bd_fta")),
                "unconverted_face": _num(iss.get("bd_fta")),
                "conv_price": _num(iss.get("cv_prc")),
                "convertible_shares": _num(iss.get("cvisstk_cnt")),
                "as_of": "발행분(전환청구 이력 없음)",
            }

    remaining = sorted(latest.values(), key=lambda x: x["round"])
    tot_face = sum(x["unconverted_face"] or 0 for x in remaining)
    tot_shares = sum(x["convertible_shares"] or 0 for x in remaining)

    result = {
        "ticker": ticker, "corp_code": corp, "_since": since, "_end": end,
        "total_unconverted_face": tot_face,
        "total_convertible_shares": tot_shares,
        "remaining_by_round": remaining,
        "issuances": issuances,
        "conversions": sorted(convs, key=lambda x: x.get("rcept_dt", ""), reverse=True),
    }
    print(f"  미전환 합계: {tot_face:,}원 / 전환가능 {tot_shares:,}주")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{ticker}: 발행결정 {len(issuances)}건, 전환청구권행사 {len(convs)}건 → {OUT}")


if __name__ == "__main__":
    main()
