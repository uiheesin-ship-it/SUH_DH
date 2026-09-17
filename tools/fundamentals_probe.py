#!/usr/bin/env python3
"""실적·컨센 데이터를 어디서 얼마나 받을 수 있는지 실측한다(측정 전용).

만들기 전에 답해야 할 질문이 둘이다.
  1. 5년치 분기 실적(매출·영업이익·순이익·EBITDA)을 어디서 받나?
  2. 컨센서스를 무료로 받을 수 있나?

추측 대신 재 본다. 아무것도 커밋하지 않고 결과만 로그에 찍는다.
샌드박스에서는 SEC·야후·나스닥이 모두 막히므로 GitHub Actions 에서 실행한다.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from collections import defaultdict

# 성격이 다른 종목들 — 대형 기술주, 반도체, 은행(영업이익 태그가 없다), 소형주,
# 유틸리티, REIT, 최근 상장. 한 종목만 되는 걸 "된다"고 착각하지 않으려는 것.
TICKERS = ["AAPL", "MU", "JPM", "APPS", "CEG", "PLD", "ARM", "SMCI"]

# SEC 는 연락처가 담긴 User-Agent 를 요구한다(없으면 403).
UA = "SUH_DH fundamentals probe (github.com/uiheesin-ship-it/SUH_DH)"

REVENUE_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
TAGS = {
    "매출": REVENUE_TAGS,
    "영업이익": ["OperatingIncomeLoss"],
    "순이익": ["NetIncomeLoss"],
    "희석EPS": ["EarningsPerShareDiluted"],
    "감가상각(D&A)": ["DepreciationDepletionAndAmortization",
                      "DepreciationAmortizationAndAccretionNet",
                      "DepreciationAndAmortization"],
}


def log(m=""):
    print(m, flush=True)


def get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ------------------------------------------------------------------ EDGAR
def cik_map():
    raw = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    return {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in raw.values()}


def quarterly(units, want_days=(80, 100)):
    """분기(약 90일) 구간 사실만 추린다. 10-Q 는 3개월·9개월 수치를 같이 싣는다."""
    from datetime import date

    out = {}
    for f in units:
        s, e = f.get("start"), f.get("end")
        if not s or not e:
            continue
        d = (date.fromisoformat(e) - date.fromisoformat(s)).days
        if not (want_days[0] <= d <= want_days[1]):
            continue
        # 같은 분기가 여러 번 나오면 나중에 제출된 것(정정)을 쓴다.
        prev = out.get(e)
        if prev is None or f.get("filed", "") >= prev.get("filed", ""):
            out[e] = f
    return out


def probe_edgar(ticker, cik):
    facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    us = facts.get("facts", {}).get("us-gaap", {})
    row, filed_ok = {}, 0
    for label, tags in TAGS.items():
        best, used = {}, None
        for tag in tags:
            node = us.get(tag)
            if not node:
                continue
            for unit_key, units in (node.get("units") or {}).items():
                q = quarterly(units)
                if len(q) > len(best):
                    best, used = q, f"{tag}/{unit_key}"
        row[label] = (len(best), used)
        if best:
            filed_ok += sum(1 for f in best.values() if f.get("filed"))

    # 회사 고유 네임스페이스에 Adjusted EBITDA 류 태그가 있나?
    custom = []
    for ns, node in (facts.get("facts") or {}).items():
        if ns == "us-gaap":
            continue
        for tag in node:
            t = tag.lower()
            if "ebitda" in t:
                custom.append(f"{ns}:{tag}")
    return row, filed_ok, custom


# -------------------------------------------------------------- 컨센서스
def probe_yahoo_estimates(ticker):
    """yfinance 가 주는 컨센: 앞으로 몇 분기치 EPS 추정을 들고 있나."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    out = {}

    # ① earnings_dates — 미래 분기 행에 EPS Estimate 가 채워져 온다.
    try:
        import pandas as pd

        df = tk.get_earnings_dates(limit=24)
        if df is not None and not df.empty:
            now = pd.Timestamp.now(tz=df.index.tz)
            fut = df[df.index > now]
            col = "EPS Estimate"
            out["earnings_dates 미래분기"] = int(fut[col].notna().sum()) if col in fut else 0
            out["earnings_dates 과거분기"] = int((df.index <= now).sum())
    except Exception as e:  # noqa: BLE001
        out["earnings_dates"] = f"실패: {type(e).__name__}"

    # ② earnings_estimate — 현재/다음 분기, 올해/내년
    for attr in ("earnings_estimate", "revenue_estimate", "growth_estimates"):
        try:
            v = getattr(tk, attr, None)
            out[attr] = "없음" if v is None or len(v) == 0 else f"{len(v)}행 {list(v.index)}"
        except Exception as e:  # noqa: BLE001
            out[attr] = f"실패: {type(e).__name__}"

    # ③ forwardEps / trailingEps
    try:
        info = tk.get_info()
        out["forwardEps"] = info.get("forwardEps")
        out["trailingEps"] = info.get("trailingEps")
        out["sharesOutstanding"] = info.get("sharesOutstanding")
    except Exception as e:  # noqa: BLE001
        out["info"] = f"실패: {type(e).__name__}"
    return out


def probe_nasdaq(ticker):
    """나스닥 공개 API — 분기별 컨센을 주지만 데이터센터 IP 를 막는 일이 잦다."""
    url = f"https://api.nasdaq.com/api/analyst/{ticker}/earnings-forecast"
    try:
        raw = json.loads(get(url, headers={"Accept": "application/json"}, timeout=15))
        d = (raw.get("data") or {})
        q = ((d.get("quarterlyForecast") or {}).get("rows") or [])
        y = ((d.get("yearlyForecast") or {}).get("rows") or [])
        return f"분기 {len(q)}행, 연간 {len(y)}행"
    except Exception as e:  # noqa: BLE001
        return f"실패: {type(e).__name__} {e}"


def probe_stockanalysis(ticker):
    """stockanalysis.com 예측 페이지 — API 는 없고 페이지에 JSON 이 박혀 있다."""
    try:
        html = get(f"https://stockanalysis.com/stocks/{ticker.lower()}/forecast/",
                   timeout=15).decode("utf-8", "replace")
        hit = [k for k in ("estimatesChart", "revenueEstimate", "epsEstimate",
                           "analystRatings") if k in html]
        return f"{len(html) // 1000}KB, 힌트 {hit or '없음'}"
    except Exception as e:  # noqa: BLE001
        return f"실패: {type(e).__name__}"


def main():
    only = sys.argv[1:] or TICKERS

    log("=" * 70)
    log("1. EDGAR companyfacts — 5년치 분기 실적")
    log("=" * 70)
    try:
        cmap = cik_map()
        log(f"  티커→CIK 매핑 {len(cmap):,}개 ✅")
    except Exception as e:  # noqa: BLE001
        log(f"  ❌ SEC 자체가 안 열립니다: {type(e).__name__} {e}")
        cmap = {}

    custom_all = defaultdict(list)
    for t in only:
        cik = cmap.get(t.upper())
        if not cik:
            log(f"  {t:6} CIK 없음")
            continue
        try:
            row, filed_ok, custom = probe_edgar(t, cik)
        except Exception as e:  # noqa: BLE001
            log(f"  {t:6} ❌ {type(e).__name__} {e}")
            continue
        parts = " ".join(f"{k} {n:>2}" for k, (n, _) in row.items())
        log(f"  {t:6} {parts}   filed 있는 사실 {filed_ok}")
        for k, (n, used) in row.items():
            if n == 0:
                log(f"         ↳ {k}: 태그 없음 (후보 {TAGS[k]})")
        if custom:
            custom_all[t] = custom[:5]
        time.sleep(0.2)          # SEC 는 초당 10건 제한

    log("\n  회사 고유 EBITDA 태그:")
    if custom_all:
        for t, tags in custom_all.items():
            log(f"    {t:6} {tags}")
    else:
        log("    없음 — Adjusted EBITDA 는 XBRL 로 못 받는다는 뜻")

    log("\n" + "=" * 70)
    log("2. 컨센서스 — 무료로 받을 수 있나")
    log("=" * 70)
    for t in only[:4]:
        log(f"\n  ── {t} ──")
        for k, v in probe_yahoo_estimates(t).items():
            log(f"    yahoo {k:24} {v}")
        log(f"    nasdaq api               {probe_nasdaq(t)}")
        log(f"    stockanalysis            {probe_stockanalysis(t)}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
