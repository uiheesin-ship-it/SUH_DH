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
def _rows(fi):
    """financeInfo 안에서 항목 행 목록을 찾는다 — 키 이름을 모르니 훑는다."""
    for k in ("rowList", "financeDetail", "list", "rows"):
        v = fi.get(k)
        if isinstance(v, list) and v:
            return k, v
    for k, v in fi.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return k, v
    return None, []


def probe_naver_finance(code, name, period):
    """실적 + 컨센이 한 응답에 같이 온다 — 그 구조를 끝까지 본다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/finance/{period}"
    try:
        d = get(url)
    except Exception as e:  # noqa: BLE001
        log(f"   finance/{period:8} ✕ {hide(e)}")
        return
    fi = d.get("financeInfo") or {}
    titles = fi.get("trTitleList") or []
    conf = [t for t in titles if t.get("isConsensus") != "Y"]
    est = [t for t in titles if t.get("isConsensus") == "Y"]
    log(f"   finance/{period:8} 기간 {len(titles)}개 "
        f"— 확정 {len(conf)}개 {[t.get('title') for t in conf]}")
    log(f"   {'':17} 추정 {len(est)}개 {[t.get('title') for t in est]}")
    key, rows = _rows(fi)
    log(f"   {'':17} 항목 목록은 '{key}' 에 {len(rows)}개")
    for r in rows[:14]:
        title = r.get("title") or r.get("krName") or r.get("name") or "?"
        vals = None
        for vk in ("value", "valueList", "values", "columns"):
            if vk in r:
                vals = r[vk]
                break
        shown = json.dumps(vals, ensure_ascii=False)[:150] if vals is not None else "?"
        log(f"   {'':17}   {title:16} {shown}")
    if rows and len(rows) > 14:
        log(f"   {'':17}   … 외 {len(rows) - 14}개")


def probe_naver(code, name):
    log(f"\n■ {name}({code}) — 네이버 모바일 API")
    for period in ("quarter", "annual"):
        probe_naver_finance(code, name, period)
        time.sleep(0.4)
    # 컨센 요약이 따로 있나
    try:
        d = get(f"https://m.stock.naver.com/api/stock/{code}/integration")
        ci = d.get("consensusInfo")
        log(f"   consensusInfo    {json.dumps(ci, ensure_ascii=False)[:300]}")
    except Exception as e:  # noqa: BLE001
        log(f"   consensusInfo    ✕ {hide(e)}")


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


# ------------------------------------------------- DART 5년 이력 · 발표일
def _dart(url_path, key, **params):
    q = urllib.parse.urlencode({"crtfc_key": key, **params})
    return get(f"https://opendart.fss.or.kr/api/{url_path}?{q}", ua=PC_UA)


def _corp(code):
    try:
        corp = json.loads((ROOT / "data" / "dart_corp.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return corp.get(code)


def probe_dart_history(code, name, years=5):
    """5년 × 4보고서를 다 받아 본다 — 분기값을 만들 수 있나.

    미장은 EDGAR 가 분기 사실을 직접 준다. 국장 정기보고서는 **누적**으로 싣는
    일이 많아(3분기보고서 = 1~9월 누적) 그걸 차분해야 분기가 된다. 어느 필드가
    당기 3개월이고 어느 필드가 누적인지를 여기서 못 박는다.
    """
    key = os.environ.get("DART_API_KEY", "").strip()
    log(f"\n■ {name}({code}) — DART 5년 이력")
    if not key:
        log("   키 없음(DART_API_KEY) — 건너뜁니다")
        return
    cc = _corp(code)
    if not cc:
        log(f"   corp_code 없음 — data/dart_corp.json 에 {code} 가 없습니다")
        return

    import datetime
    this_year = datetime.date.today().year
    want = ["매출액", "영업이익", "당기순이익"]
    ok = 0
    for year in range(this_year - years + 1, this_year + 1):
        for rc in ("11013", "11012", "11014", "11011"):
            try:
                d = _dart("fnlttSinglAcnt.json", key, corp_code=cc,
                          bsns_year=str(year), reprt_code=rc)
            except Exception as e:  # noqa: BLE001
                log(f"   {year} {REPRT[rc]:4} ✕ {hide(e)}")
                continue
            if d.get("status") != "000":
                log(f"   {year} {REPRT[rc]:4} — status={d.get('status')} {d.get('message')}")
                time.sleep(0.4)
                continue
            got = {}
            for r in d.get("list") or []:
                nm = (r.get("account_nm") or "").strip()
                if nm in want and r.get("fs_div") == "CFS":
                    got[nm] = (r.get("thstrm_amount"), r.get("thstrm_add_amount"),
                               r.get("thstrm_nm"))
            if got:
                ok += 1
                bits = " · ".join(
                    f"{k} 당기 {v[0]} / 누적 {v[1]}" for k, v in got.items())
                log(f"   {year} {REPRT[rc]:4} ✓ {bits}  [{list(got.values())[0][2]}]")
            else:
                log(f"   {year} {REPRT[rc]:4} — 손익 항목 없음({len(d.get('list') or [])}행)")
            time.sleep(0.4)
    log(f"   → 받은 보고서 {ok}/{years * 4}")


def probe_dart_dates(code, name, years=5):
    """**실적발표일**을 어디서 얻나.

    미장은 야후가 실제 발표일을 준다. 국장은 DART 공시목록의 접수일자(rcept_dt)
    가 그 자리다. 정기보고서 접수일보다 **잠정실적 공시**가 먼저 나오는 일이
    많아(삼성전자 잠정실적), 둘 다 세어 본다.
    """
    key = os.environ.get("DART_API_KEY", "").strip()
    log(f"\n■ {name}({code}) — DART 공시 접수일")
    if not key:
        log("   키 없음 — 건너뜁니다")
        return
    cc = _corp(code)
    if not cc:
        log("   corp_code 없음")
        return
    import datetime
    end = datetime.date.today()
    beg = end.replace(year=end.year - years)
    for label, ty in (("정기보고서(A)", "A"), ("거래소공시(I)", "I")):
        try:
            d = _dart("list.json", key, corp_code=cc, bgn_de=beg.strftime("%Y%m%d"),
                      end_de=end.strftime("%Y%m%d"), pblntf_ty=ty, page_count="100")
        except Exception as e:  # noqa: BLE001
            log(f"   {label:12} ✕ {hide(e)}")
            continue
        if d.get("status") != "000":
            log(f"   {label:12} — status={d.get('status')} {d.get('message')}")
            continue
        rows = d.get("list") or []
        if ty == "A":
            keep = [r for r in rows if "분기보고서" in (r.get("report_nm") or "")
                    or "반기보고서" in (r.get("report_nm") or "")
                    or "사업보고서" in (r.get("report_nm") or "")]
        else:
            keep = [r for r in rows if "잠정" in (r.get("report_nm") or "")]
        log(f"   {label:12} 전체 {len(rows)}건 · 쓸 만한 것 {len(keep)}건")
        for r in sorted(keep, key=lambda x: x.get("rcept_dt") or "")[-6:]:
            log(f"       {r.get('rcept_dt')}  {r.get('report_nm')}")
        time.sleep(0.4)


def probe_dart_all(code, name, year=None, rc="11014"):
    """fnlttSinglAcntAll — **전체 재무제표**. 주요계정으로는 모자란 것들을 본다.

    fnlttSinglAcnt(주요계정)은 매출·영업이익·당기순이익과 재무상태표 합계만
    준다. 미장과 같은 것을 만들려면 더 필요하다.

      주당순이익   PER 의 분모. 순이익÷현재주식수로 만들면 과거 증자·분할이
                   반영되지 않아 옛 구간이 통째로 틀어진다.
      감가상각비   EBITDA 를 만들려면 필요하다(영업이익 + 감가상각).
      차입금·현금  EV 를 만들려면 필요하다.

    있는지 없는지에 따라 국장에서 무엇까지 만들 수 있는지가 갈린다.
    """
    key = os.environ.get("DART_API_KEY", "").strip()
    import datetime
    year = year or str(datetime.date.today().year - 1)
    log(f"\n■ {name}({code}) — DART 전체 재무제표 {year} {REPRT[rc]}")
    if not key:
        log("   키 없음 — 건너뜁니다")
        return
    cc = _corp(code)
    if not cc:
        log("   corp_code 없음")
        return
    try:
        d = _dart("fnlttSinglAcntAll.json", key, corp_code=cc, bsns_year=year,
                  reprt_code=rc, fs_div="CFS")
    except Exception as e:  # noqa: BLE001
        log(f"   ✕ {hide(e)}")
        return
    if d.get("status") != "000":
        log(f"   status={d.get('status')} {d.get('message')}")
        return
    rows = d.get("list") or []
    log(f"   전체 {len(rows)}행")
    marks = {"주당순이익": ("주당",), "감가상각": ("감가상각", "상각비"),
             "차입금·사채": ("차입금", "사채"), "리스부채": ("리스부채",),
             "현금성": ("현금및현금성", "단기금융", "단기투자"),
             "비지배지분": ("비지배",), "우선주": ("우선주",)}
    for label, words in marks.items():
        hit = [r for r in rows
               if any(w in (r.get("account_nm") or "") for w in words)]
        if not hit:
            log(f"   {label:12} — 없음")
            continue
        log(f"   {label:12} {len(hit)}행")
        for r in hit[:5]:
            log(f"       [{r.get('sj_div')}] {(r.get('account_nm') or '')[:28]:30}"
                f" 당기 {r.get('thstrm_amount')} / 누적 {r.get('thstrm_add_amount')}"
                f"  ({r.get('account_id')})")


def probe_kr_horizon(code, name):
    """컨센이 **몇 분기·몇 해 앞**까지 오나 — 12개월을 채울 수 있나.

    미장은 야후가 분기 2개 + 연간 2개를 준다. 그걸로 계절성 배분을 해서 4분기를
    채웠다. 국장 네이버는 실측(2026-09-18)으로 분기 **1개**, 연간 **1개**뿐이라
    올해 잔여 분기까지밖에 안 채워진다 — 내년 1·2분기가 빈다.

    그래서 내년 컨센을 주는 곳이 있는지 본다. 네이버의 다른 엔드포인트와
    FnGuide 를 열어 (E) 가 붙은 연도가 몇 개인지 센다.
    """
    log(f"\n■ {name}({code}) — 컨센 지평")
    variants = [
        ("finance/quarter", f"https://m.stock.naver.com/api/stock/{code}/finance/quarter"),
        ("finance/annual", f"https://m.stock.naver.com/api/stock/{code}/finance/annual"),
        ("finance/quarter?type=consensus",
         f"https://m.stock.naver.com/api/stock/{code}/finance/quarter?financeType=consensus"),
        ("integration", f"https://m.stock.naver.com/api/stock/{code}/integration"),
        ("estimate", f"https://m.stock.naver.com/api/stock/{code}/estimate"),
        ("consensus", f"https://m.stock.naver.com/api/stock/{code}/consensus"),
        ("trend", f"https://m.stock.naver.com/api/stock/{code}/finance/annual/trend"),
    ]
    for label, url in variants:
        try:
            d = get(url)
        except Exception as e:  # noqa: BLE001
            log(f"   {label:32} ✕ {hide(e)}")
            time.sleep(0.3)
            continue
        fi = d.get("financeInfo") if isinstance(d, dict) else None
        if isinstance(fi, dict) and fi.get("trTitleList"):
            titles = fi["trTitleList"]
            est = [t.get("title") for t in titles if t.get("isConsensus") == "Y"]
            log(f"   {label:32} 기간 {len(titles)}개 · 추정 {len(est)}개 {est}")
        else:
            keys = sorted(d)[:12] if isinstance(d, dict) else type(d).__name__
            log(f"   {label:32} ✓ 키 {keys}")
        time.sleep(0.3)

    # FnGuide 는 연간 컨센을 몇 해까지 싣나
    url = ("https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A"
           f"{code}&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701")
    try:
        html = get(url, ua=PC_UA, raw=True).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        log(f"   {'FnGuide SVD_Main':32} ✕ {hide(e)}")
        return
    import re as _re
    years = sorted(set(_re.findall(r"(20\d\d)/\d\d\(E\)", html)))
    cols = sorted(set(_re.findall(r"(20\d\d)/\d\d", html)))
    log(f"   {'FnGuide SVD_Main':32} {len(html):,}자 · 추정 연도 {years} · 전체 기간 {cols[:12]}")


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
        if only == "dart5":
            probe_dart_history(code, name)
            probe_dart_dates(code, name)
        if only == "dartall":
            probe_dart_all(code, name)
        if only == "horizon":
            probe_kr_horizon(code, name)
        if not only or only == "fnguide":
            probe_fnguide(code, name)
        if not only or only == "web":
            probe_naver_web(code, name)


if __name__ == "__main__":
    main()
