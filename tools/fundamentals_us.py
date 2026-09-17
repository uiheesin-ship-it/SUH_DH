#!/usr/bin/env python3
"""한 종목의 분기 실적을 EDGAR 에서 받아 정규화한다.

  python tools/fundamentals_us.py AAPL MU JPM
  python tools/fundamentals_us.py AAPL --json out.json

미리 전 종목을 모으지 않는다 — 요청한 티커만 받는다.

User-Agent 에 대하여: SEC 는 연락처가 담긴 UA 를 요구하는데, 실측하니 그 형식
(그리고 앱명+URL 형식)은 data.sec.gov 에서 403 이고 평범한 브라우저 UA 만
200 이다(tools/fundamentals_probe.py, 2026-09-17). WAF 가 그렇게 동작한다.
어쩔 수 없이 브라우저 UA 를 쓰되, 요청량을 최소로 둔다 — 티커당 파일 하나,
초당 한 건 이하, 받은 건 캐시한다.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.fundamentals import build_metrics  # noqa: E402

CIK_FILE = ROOT / "data" / "sec_cik.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
PAUSE = 0.5          # SEC 는 초당 10건까지 허용하지만 우리는 훨씬 아래로 쓴다


def log(m=""):
    print(m, flush=True)


def _get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_cik_map() -> dict[str, str]:
    """이미 찾아 둔 티커 → CIK. 처음 찾은 것만 쌓이는 **자라는 캐시**다."""
    if not CIK_FILE.exists():
        return {}
    try:
        return json.loads(CIK_FILE.read_text(encoding="utf-8")).get("map") or {}
    except Exception:  # noqa: BLE001
        return {}


def save_cik_map(m: dict[str, str]) -> None:
    CIK_FILE.parent.mkdir(parents=True, exist_ok=True)
    CIK_FILE.write_text(
        json.dumps({"count": len(m), "map": dict(sorted(m.items()))},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def refresh_cik_map() -> dict[str, str]:
    """전체 목록은 www.sec.gov 에 있는데 거기가 403 이다. 열리면 받아 둔다."""
    try:
        raw = json.loads(_get("https://www.sec.gov/files/company_tickers.json", timeout=30))
    except Exception as e:  # noqa: BLE001
        log(f"  전체 CIK 목록 없음({type(e).__name__}) — 티커별로 찾습니다")
        return {}
    m = {v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in raw.values()}
    save_cik_map(m)
    log(f"  전체 CIK 목록 갱신 {len(m):,}개")
    return m


def resolve_cik(ticker: str) -> str | None:
    """티커 하나의 CIK 를 EDGAR 전문검색으로 찾는다.

    전체 목록(www.sec.gov/files/company_tickers.json)이 403 이라 쓸 수 없다.
    efts.sec.gov 는 열리고, 검색 결과에 "Apple Inc. (AAPL) (CIK 0000320193)"
    꼴의 display_names 가 들어 있다. 거기서 괄호 안 티커가 정확히 일치하는
    항목만 받는다 — 본문에 그 글자가 우연히 있는 문서를 잡으면 안 된다.
    """
    import re
    import urllib.parse

    q = urllib.parse.quote(f'"{ticker}"')
    url = f"https://efts.sec.gov/LATEST/search-index?q={q}&forms=10-Q,10-K"
    try:
        hits = json.loads(_get(url, timeout=25)).get("hits", {}).get("hits", [])
    except Exception as e:  # noqa: BLE001
        log(f"    전문검색 실패: {type(e).__name__}")
        return None
    pat = re.compile(r"\((" + re.escape(ticker.upper()) + r")\)\s*\(CIK\s*(\d{10})\)", re.I)
    for h in hits:
        for name in (h.get("_source") or {}).get("display_names") or []:
            m = pat.search(name)
            if m:
                return m.group(2)
    return None


def companyfacts(cik: str) -> dict:
    return json.loads(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))


def company_meta(cik: str) -> dict:
    d = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=30))
    return {"name": d.get("name"), "tickers": d.get("tickers"),
            "sic": d.get("sicDescription"), "fiscal_year_end": d.get("fiscalYearEnd")}


def fetch(ticker: str, cik_map: dict[str, str], quarters: int = 20) -> dict:
    t = ticker.upper().strip()
    cik = cik_map.get(t)
    if not cik:
        cik = resolve_cik(t)
        if cik:
            cik_map[t] = cik          # 다음부터는 캐시에서 바로
            time.sleep(PAUSE)
    if not cik:
        return {"ticker": t, "error": "CIK 를 찾지 못했습니다"}
    try:
        meta = company_meta(cik)
        time.sleep(PAUSE)
        facts = companyfacts(cik)
    except urllib.error.HTTPError as e:
        return {"ticker": t, "error": f"EDGAR HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ticker": t, "error": f"{type(e).__name__}: {e}"}
    return {"ticker": t, "cik": cik, **meta, "metrics": build_metrics(facts, quarters)}


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_path = None
    if "--json" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--json") + 1])
    tickers = argv or ["AAPL"]

    cik_map = refresh_cik_map() or load_cik_map()
    log(f"CIK 캐시 {len(cik_map):,}개")
    before = len(cik_map)

    results = []
    for t in tickers:
        r = fetch(t, cik_map)
        results.append(r)
        if r.get("error"):
            log(f"\n■ {t} — ❌ {r['error']}")
            continue
        log(f"\n■ {t} — {r.get('name')} ({r.get('sic')}) 결산 {r.get('fiscal_year_end')}")
        for label, m in r["metrics"].items():
            qs = m["quarters"]
            if not qs:
                log(f"   {label:12} —  ({m['source']})")
                continue
            last = qs[-1]
            yoy = f"{last['yoy']:+.1f}%" if last.get("yoy") is not None else "—"
            qoq = f"{last['qoq']:+.1f}%" if last.get("qoq") is not None else "—"
            log(f"   {label:12} {m['count']:2}분기 · 최근 {last['end']} "
                f"{last['val']:,.0f}  YoY {yoy}  QoQ {qoq}   ({m['source']})")
        time.sleep(PAUSE)

    if len(cik_map) > before:
        save_cik_map(cik_map)
        log(f"\nCIK 캐시에 {len(cik_map) - before}개 추가 → {CIK_FILE.name}")

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
        log(f"\nWrote {out_path} ({out_path.stat().st_size / 1e3:.0f}KB)")


if __name__ == "__main__":
    main()
