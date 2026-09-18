#!/usr/bin/env python3
"""국장 분기 실적 + 컨센을 어디서 받을 수 있나 — 실측.

미장은 EDGAR(실적) + 야후(컨센)로 풀렸다. 국장은 그 두 자리에 무엇이 들어갈지가
전부라, 짓기 전에 **재 본다.** 확인할 것은 셋이다.

  1. 항목이 있나   매출·영업이익·당기순이익이 분기별로 나오나
  2. 얼마나 최신인가 지연이 며칠인가 — 가장 최근 분기가 언제까지 나오나
  3. 컨센이 있나   향후 분기·연도 추정치가 무료로 나오나

후보:
  DART Open API   opendart.fss.or.kr — 공시 원본. 키는 이미 저장소에 있다.
  네이버 모바일    m.stock.naver.com/api — JSON. 키가 필요 없다.
  FnGuide         comp.fnguide.com — 네이버 종목분석의 원 데이터.
  네이버 금융 웹   finance.naver.com — HTML.

키는 로그에 찍지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 업종을 흩어 고른다 — 제조·반도체·플랫폼·금융·바이오·코스닥
SAMPLES = [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("005380", "현대차"),
           ("035420", "NAVER"), ("105560", "KB금융"), ("247540", "에코프로비엠")]

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def log(m=""):
    print(m, flush=True)


def get(url, ua=UA, timeout=20, raw=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept": "application/json, text/html, */*",
        "Referer": "https://m.stock.naver.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return body if raw else json.loads(body)


def hide(e):
    return f"{type(e).__name__}: {str(e).split('?')[0][:100]}"


def walk_keys(o, depth=0, out=None):
    """중첩 JSON 에서 어떤 키가 있는지 훑는다 — 모양을 모르니 먼저 본다."""
    out = out if out is not None else []
    if depth > 3:
        return out
    if isinstance(o, dict):
        for k, v in o.items():
            out.append(k)
            walk_keys(v, depth + 1, out)
    elif isinstance(o, list) and o:
        walk_keys(o[0], depth + 1, out)
    return out


# --------------------------------------------------------------- 네이버 모바일
def probe_naver(code, name):
    log(f"\n■ {name}({code}) — 네이버 모바일 API")
    paths = ["integration", "finance/annual", "finance/quarter", "basic",
             "finance/annual/summary", "finance/quarter/summary"]
    for p in paths:
        url = f"https://m.stock.naver.com/api/stock/{code}/{p}"
        try:
            d = get(url)
        except Exception as e:  # noqa: BLE001
            log(f"   {p:24} ✕ {hide(e)}")
            continue
        keys = sorted(set(walk_keys(d)))
        log(f"   {p:24} ✓ 키 {len(keys)}개")
        hit = [k for k in keys if any(w in k.lower() for w in
               ("sales", "revenue", "operat", "profit", "income", "estim",
                "consensus", "quarter", "annual", "eps", "per"))]
        if hit:
            log(f"   {'':24}   관심 키: {hit[:14]}")
        log(f"   {'':24}   원문: {json.dumps(d, ensure_ascii=False)[:260]}")
        time.sleep(0.4)


# --------------------------------------------------------------------- FnGuide
def probe_fnguide(code, name):
    log(f"\n■ {name}({code}) — FnGuide")
    url = ("https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A"
           f"{code}&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701")
    try:
        html = get(url, ua=PC_UA, raw=True).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        log(f"   ✕ {hide(e)}")
        return
    marks = ["매출액", "영업이익", "당기순이익", "(E)", "컨센서스", "추정",
             "IFRS", "연간", "분기"]
    found = {m: html.count(m) for m in marks if m in html}
    log(f"   ✓ {len(html):,}자 · 발견: {found}")


# ------------------------------------------------------------------ 네이버 금융
def probe_naver_web(code, name):
    log(f"\n■ {name}({code}) — 네이버 금융 웹")
    for label, url in [
        ("coinfo", f"https://finance.naver.com/item/coinfo.naver?code={code}"),
        ("main", f"https://finance.naver.com/item/main.naver?code={code}"),
    ]:
        try:
            html = get(url, ua=PC_UA, raw=True).decode("euc-kr", "replace")
        except Exception as e:  # noqa: BLE001
            log(f"   {label:8} ✕ {hide(e)}")
            continue
        marks = ["매출액", "영업이익", "당기순이익", "(E)", "추정", "컨센서스"]
        found = {m: html.count(m) for m in marks if m in html}
        log(f"   {label:8} ✓ {len(html):,}자 · 발견: {found}")


# ----------------------------------------------------------------------- DART
REPRT = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업"}


def probe_dart(code, name):
    key = os.environ.get("DART_API_KEY", "").strip()
    log(f"\n■ {name}({code}) — DART Open API")
    if not key:
        log("   키 없음(DART_API_KEY) — 건너뜁니다")
        return
    try:
        corp = json.loads((ROOT / "data" / "dart_corp.json").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log(f"   corp 매핑을 못 읽음: {e}")
        return
    cc = corp.get(code)
    if not cc:
        log(f"   corp_code 없음 — data/dart_corp.json 에 {code} 가 없습니다")
        return

    for year, rc in [("2026", "11012"), ("2026", "11013"), ("2025", "11011"),
                     ("2025", "11014")]:
        url = ("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
               f"?crtfc_key={urllib.parse.quote(key)}&corp_code={cc}"
               f"&bsns_year={year}&reprt_code={rc}")
        try:
            d = get(url, ua=PC_UA)
        except Exception as e:  # noqa: BLE001
            log(f"   {year} {REPRT[rc]:4} ✕ {hide(e)}")
            continue
        status, msg = d.get("status"), d.get("message")
        rows = d.get("list") or []
        if status != "000":
            log(f"   {year} {REPRT[rc]:4} ✕ status={status} {msg}")
            continue
        want = ["매출액", "영업이익", "당기순이익"]
        got = {}
        for r in rows:
            nm = (r.get("account_nm") or "").strip()
            if nm in want and r.get("fs_div") == "CFS":
                got[nm] = {"당기": r.get("thstrm_amount"),
                           "누적": r.get("thstrm_add_amount"),
                           "기간": r.get("thstrm_nm")}
        log(f"   {year} {REPRT[rc]:4} ✓ {len(rows)}행 · 찾은 항목 {list(got)}")
        for k, v in got.items():
            log(f"   {'':12}   {k}: 당기 {v['당기']} · 누적 {v['누적']} ({v['기간']})")
        time.sleep(0.6)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    picks = [(c, n) for c, n in SAMPLES if not args or c in args or n in args]
    only = sys.argv[1:] and sys.argv[1].startswith("--only=") and sys.argv[1][7:]

    log("국장 실적·컨센 출처 실측")
    log(f"대상: {', '.join(n for _, n in picks)}")
    for code, name in picks:
        if not only or only == "naver":
            probe_naver(code, name)
        if not only or only == "dart":
            probe_dart(code, name)
        if not only or only == "fnguide":
            probe_fnguide(code, name)
        if not only or only == "web":
            probe_naver_web(code, name)


if __name__ == "__main__":
    main()
