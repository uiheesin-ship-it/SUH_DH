#!/usr/bin/env python3
"""실적·컨센 데이터 출처 실측(측정 전용). 1차 결과로 초점을 좁힌 2차 프로브.

1차에서 EDGAR 가 403 이었다. SEC 는 연락처가 담긴 User-Agent 를 요구하는데
형식이 안 맞았을 수도 있고, 클라우드 IP 를 막는 것일 수도 있다. 둘은 대응이
완전히 다르므로(전자는 헤더 수정, 후자는 출처 교체) 먼저 가른다.

컨센은 1차에서 이만큼 확인됐다:
  earnings_dates 미래 분기  1개뿐      → 4개 분기를 이걸로는 못 채운다
  earnings_estimate        0q·+1q·0y·+1y → 분기 2개 + 연간 2개
  forwardEps               전 종목 있음 (APPS 는 적자인데도 +0.95)
  나스닥 API               타임아웃(차단)
  stockanalysis            페이지에 estimatesChart 박혀 있음

그래서 2차는 EDGAR 진단 + 컨센 실제 값 확인에 집중한다.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

TICKERS = ["AAPL", "MU", "JPM", "APPS"]


def log(m=""):
    print(m, flush=True)


def fetch(url, ua, extra=None, timeout=20):
    h = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate", **(extra or {})}
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()[:400]
    except urllib.error.HTTPError as e:
        return e.code, (e.read()[:200] if hasattr(e, "read") else b"")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}".encode()


def probe_sec_headers():
    """403 이 UA 탓인지 IP 탓인지 가른다."""
    # SEC 안내 형식: "Sample Company Name AdminContact@<domain>.com"
    uas = [
        ("연락처 없음(1차와 동일)", "SUH_DH fundamentals probe (github.com/uiheesin-ship-it/SUH_DH)"),
        ("이메일 형식", "SUH_DH Dashboard noreply@users.noreply.github.com"),
        ("브라우저 위장", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    ]
    urls = [
        ("company_tickers", "https://www.sec.gov/files/company_tickers.json"),
        ("companyfacts", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"),
        ("submissions", "https://data.sec.gov/submissions/CIK0000320193.json"),
    ]
    for label, ua in uas:
        log(f"\n  UA: {label}")
        for name, url in urls:
            code, body = fetch(url, ua)
            note = ""
            if code != 200:
                note = f"  ← {body[:120].decode('utf-8', 'replace')}"
            log(f"    {name:16} HTTP {code}{note}")
            time.sleep(0.3)


def probe_edgar_content(ua):
    """UA 가 통하면 실제로 5년치 분기가 잡히는지 본다."""
    from datetime import date

    code, _ = fetch("https://www.sec.gov/files/company_tickers.json", ua)
    if code != 200:
        log("  (통하는 UA 가 없어 내용 확인은 건너뜁니다)")
        return
    req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json",
                                 headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = json.loads(r.read())
    cmap = {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in raw.values()}
    log(f"  티커→CIK {len(cmap):,}개")

    tags = {
        "매출": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "RevenueFromContractWithCustomerIncludingAssessedTax",
                 "Revenues", "SalesRevenueNet"],
        "영업이익": ["OperatingIncomeLoss"],
        "순이익": ["NetIncomeLoss"],
        "희석EPS": ["EarningsPerShareDiluted"],
        "D&A": ["DepreciationDepletionAndAmortization",
                "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization"],
    }
    for t in TICKERS:
        cik = cmap.get(t)
        if not cik:
            continue
        req = urllib.request.Request(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=40) as r:
            facts = json.loads(r.read())
        us = facts.get("facts", {}).get("us-gaap", {})
        cells, lag = [], []
        for label, cands in tags.items():
            best, used = {}, None
            for tag in cands:
                for units in (us.get(tag, {}).get("units") or {}).values():
                    q = {}
                    for f in units:
                        s, e = f.get("start"), f.get("end")
                        if not s or not e:
                            continue
                        if not (80 <= (date.fromisoformat(e) - date.fromisoformat(s)).days <= 100):
                            continue
                        if e not in q or f.get("filed", "") >= q[e].get("filed", ""):
                            q[e] = f
                    if len(q) > len(best):
                        best, used = q, tag
            cells.append(f"{label} {len(best):>2}")
            if label == "순이익" and best:
                for e, f in sorted(best.items())[-4:]:
                    if f.get("filed"):
                        lag.append((date.fromisoformat(f["filed"]) - date.fromisoformat(e)).days)
        avg = f"{sum(lag)//len(lag)}일" if lag else "—"
        log(f"  {t:6} {'  '.join(cells)}   기준일→제출일 평균 {avg}")
        custom = [f"{ns}:{tag}" for ns, node in (facts.get("facts") or {}).items()
                  if ns != "us-gaap" for tag in node if "ebitda" in tag.lower()]
        if custom:
            log(f"         EBITDA 고유태그: {custom[:4]}")
        time.sleep(0.3)


def probe_consensus_values():
    """컨센 실제 값 — 12M forward EPS 를 만들 수 있는 재료인지 본다."""
    import yfinance as yf

    for t in TICKERS:
        log(f"\n  ── {t} ──")
        tk = yf.Ticker(t)
        try:
            est = tk.earnings_estimate
            for idx in est.index:
                row = est.loc[idx]
                log(f"    {idx:4} EPS평균 {row.get('avg')}  분석가 {row.get('numberOfAnalysts')}")
        except Exception as e:  # noqa: BLE001
            log(f"    earnings_estimate 실패: {type(e).__name__}")
        try:
            info = tk.get_info()
            log(f"    forwardEps {info.get('forwardEps')} · trailingEps {info.get('trailingEps')}"
                f" · 결산월 {info.get('lastFiscalYearEnd')}")
        except Exception as e:  # noqa: BLE001
            log(f"    info 실패: {type(e).__name__}")
        time.sleep(1.0)


def probe_stockanalysis_financials():
    """EDGAR 가 막힐 때의 대안 — 분기 손익계산서가 페이지에 있나."""
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
    for t in TICKERS[:2]:
        for path in ("financials/?p=quarterly", "financials/"):
            code, _ = fetch(f"https://stockanalysis.com/stocks/{t.lower()}/{path}", ua)
            log(f"  {t:6} {path:26} HTTP {code}")
            time.sleep(0.5)


def main():
    log("=" * 72)
    log("1. EDGAR 403 진단 — UA 문제인가 IP 차단인가")
    log("=" * 72)
    probe_sec_headers()

    log("\n" + "=" * 72)
    log("2. EDGAR 내용 (통하는 UA 로)")
    log("=" * 72)
    probe_edgar_content("SUH_DH Dashboard noreply@users.noreply.github.com")

    log("\n" + "=" * 72)
    log("3. 컨센 실제 값")
    log("=" * 72)
    probe_consensus_values()

    log("\n" + "=" * 72)
    log("4. 대안: stockanalysis 분기 재무제표")
    log("=" * 72)
    probe_stockanalysis_financials()


if __name__ == "__main__":
    main()
