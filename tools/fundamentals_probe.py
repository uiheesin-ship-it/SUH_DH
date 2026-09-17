#!/usr/bin/env python3
"""실적·컨센 출처 실측 3차 — EDGAR 를 실제로 쓸 수 있는지 확정한다.

2차에서 갈렸다. 403 은 IP 차단이 아니라 **호스트·UA 조합** 문제였다:

  UA 연락처없음 / 이메일형식   www·data 모두 403
  UA 브라우저                  www.sec.gov 403 · data.sec.gov **200**

즉 재무 데이터 본체(data.sec.gov 의 companyfacts·submissions)는 열린다.
막힌 건 티커→CIK 매핑 파일 하나(www.sec.gov/files/company_tickers.json)뿐이다.

3차가 확정할 것:
  1. 신원을 밝히면서 통과하는 UA 가 있나 — SEC 는 연락처 있는 UA 를 요구하고
     우리도 위장보다 declare 하는 쪽이 낫다.
  2. 티커→CIK 를 어디서 얻나 (www 가 막혔으므로 대안이 필요).
  3. 통과 UA 로 실제 내용 — 5년치 분기 개수, 기준일→제출일 지연, EBITDA 태그.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date

TICKERS = {"AAPL": "0000320193", "MU": "0000723125", "JPM": "0000019617",
           "APPS": "0000317788", "JPM_": None}
BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def log(m=""):
    print(m, flush=True)


def fetch(url, ua, timeout=25, raw=False):
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, (body if raw else body[:200])
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}".encode()


def probe_uas():
    """신원을 밝히면서 통과하는 UA 를 찾는다(위장보다 declare 가 낫다)."""
    uas = [
        ("브라우저(2차에서 통과)", BROWSER),
        ("브라우저+신원 declare",
         "Mozilla/5.0 (compatible; SUH-DH/1.0; +https://github.com/uiheesin-ship-it/SUH_DH)"),
        ("SEC 안내 형식", "SUH_DH Dashboard noreply@users.noreply.github.com"),
        ("앱명+URL", "SUH_DH/1.0 (+https://github.com/uiheesin-ship-it/SUH_DH)"),
    ]
    urls = [("data/companyfacts", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"),
            ("data/submissions", "https://data.sec.gov/submissions/CIK0000320193.json"),
            ("www/company_tickers", "https://www.sec.gov/files/company_tickers.json")]
    ok_ua = None
    for label, ua in uas:
        codes = []
        for name, url in urls:
            c, _ = fetch(url, ua, timeout=20)
            codes.append(f"{name} {c}")
            time.sleep(0.3)
        log(f"  {label:26} {' · '.join(codes)}")
        if ok_ua is None and codes[0].endswith("200"):
            ok_ua = ua
    return ok_ua


def probe_cik_sources(ua):
    """www 가 막혔으니 티커→CIK 를 어디서 얻을지 찾는다."""
    cands = [
        ("data.sec.gov 미러", "https://data.sec.gov/files/company_tickers.json"),
        ("www (참고)", "https://www.sec.gov/files/company_tickers.json"),
        ("EDGAR 전문검색", "https://efts.sec.gov/LATEST/search-index?q=%22Apple%20Inc%22&forms=10-K"),
        ("efts entity search",
         "https://efts.sec.gov/LATEST/search-index?q=AAPL"),
    ]
    for name, url in cands:
        c, body = fetch(url, ua, timeout=20)
        extra = ""
        if c == 200:
            extra = f"  {len(body)}B 이상"
        log(f"  {name:22} HTTP {c}{extra}")
        time.sleep(0.3)

    # submissions 는 CIK 로만 부를 수 있지만, 그 안에 tickers 가 들어 있다.
    c, body = fetch("https://data.sec.gov/submissions/CIK0000320193.json", ua,
                    timeout=25, raw=True)
    if c == 200:
        d = json.loads(body)
        log(f"  submissions 안의 tickers: {d.get('tickers')} · 이름 {d.get('name')}")
        log("    → CIK 를 알면 티커 확인은 되지만 역방향 매핑은 안 된다."
            " 목록을 저장소에 커밋해 두는 쪽이 현실적.")


def probe_content(ua):
    tags = {
        "매출": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "RevenueFromContractWithCustomerIncludingAssessedTax",
                 "Revenues", "SalesRevenueNet"],
        "영업이익": ["OperatingIncomeLoss"],
        "순이익": ["NetIncomeLoss"],
        "희석EPS": ["EarningsPerShareDiluted"],
        "D&A": ["DepreciationDepletionAndAmortization",
                "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization"],
        "주식수(희석)": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    }
    cutoff = date.today().year - 6
    for t, cik in TICKERS.items():
        if not cik:
            continue
        c, body = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                        ua, timeout=45, raw=True)
        if c != 200:
            log(f"  {t:6} HTTP {c}")
            continue
        facts = json.loads(body)
        us = facts.get("facts", {}).get("us-gaap", {})
        cells, lags, annual = [], [], 0
        for label, cands in tags.items():
            best, used = {}, None
            for tag in cands:
                for units in (us.get(tag, {}).get("units") or {}).values():
                    q = {}
                    for f in units:
                        s, e = f.get("start"), f.get("end")
                        if not s or not e or date.fromisoformat(e).year < cutoff:
                            continue
                        days = (date.fromisoformat(e) - date.fromisoformat(s)).days
                        if not (80 <= days <= 100):
                            continue
                        if e not in q or f.get("filed", "") >= q[e].get("filed", ""):
                            q[e] = f
                    if len(q) > len(best):
                        best, used = q, tag
            cells.append(f"{label} {len(best):>2}")
            if label == "순이익":
                for e, f in sorted(best.items())[-6:]:
                    if f.get("filed"):
                        lags.append((date.fromisoformat(f["filed"]) - date.fromisoformat(e)).days)
                # 연간(10-K)에만 있는 분기 = Q4 를 역산해야 하는지 확인
                for units in (us.get("NetIncomeLoss", {}).get("units") or {}).values():
                    annual = sum(1 for f in units
                                 if f.get("start") and f.get("end")
                                 and date.fromisoformat(f["end"]).year >= cutoff
                                 and 350 <= (date.fromisoformat(f["end"])
                                             - date.fromisoformat(f["start"])).days <= 380)
                    break
        lag = f"{min(lags)}~{max(lags)}일" if lags else "—"
        log(f"  {t:6} {'  '.join(cells)}")
        log(f"         기준일→제출일 {lag} · 연간(10-K) 사실 {annual}개 (Q4 역산용)")
        custom = [f"{ns}:{tag}" for ns, node in (facts.get("facts") or {}).items()
                  if ns != "us-gaap" for tag in node if "ebitda" in tag.lower()]
        log(f"         EBITDA 고유태그: {custom[:4] if custom else '없음'}")
        time.sleep(0.4)


def main():
    log("=" * 72)
    log("1. 통과하는 User-Agent 찾기 (위장 말고 신원을 밝히면서)")
    log("=" * 72)
    ua = probe_uas()
    log(f"\n  채택: {ua or '없음'}")
    if not ua:
        return

    log("\n" + "=" * 72)
    log("2. 티커→CIK 매핑을 어디서 얻나 (www 가 막혔다)")
    log("=" * 72)
    probe_cik_sources(ua)

    log("\n" + "=" * 72)
    log("3. 실제 내용 — 최근 6년 분기 개수 · 제출 지연 · EBITDA")
    log("=" * 72)
    probe_content(ua)


if __name__ == "__main__":
    main()
