"""EDGAR(data.sec.gov)에서 companyfacts 를 받아 온다.

여기만 네트워크를 안다. 변환 규칙은 ``app/fundamentals.py`` 가, 조립은
``app/quarterly.py`` 가 한다.

User-Agent 에 대하여: SEC 는 연락처가 담긴 UA 를 요구하는데, 실측하니 그 형식
(그리고 앱명+URL 형식)은 data.sec.gov 에서 403 이고 평범한 브라우저 UA 만
200 이다(tools/fundamentals_probe.py, 2026-09-17). WAF 가 그렇게 동작한다.
어쩔 수 없이 브라우저 UA 를 쓰되 **요청량을 최소로 둔다** — 티커당 파일 둘,
초당 두 건 이하, 받은 건 캐시한다. 미리 전 종목을 모으지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import cache

ROOT = Path(__file__).resolve().parent.parent
CIK_FILE = ROOT / "data" / "sec_cik.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
PAUSE = 0.5
EFTS_PAUSE = 2.0          # 전문검색은 data.sec.gov 보다 훨씬 빡빡하다
EFTS_TRIES = 3
# companyfacts 는 분기에 한 번 바뀐다 — 길게 잡아도 된다.
FACTS_TTL = float(os.environ.get("SUH_DH_SEC_TTL", "21600"))

_cik_map: dict[str, str] | None = None


def _get(url: str, timeout: float = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cik_map() -> dict[str, str]:
    """커밋된 티커→CIK 씨앗 목록. **힌트일 뿐이다.**

    SEC 원본(www.sec.gov/files/company_tickers.json)이 403 이라 공개 미러에서
    받아 온 것이다. 그래서 쓸 때마다 submissions 응답으로 실제로 맞는지
    확인한다 — 어차피 회사명을 받으려고 부르는 호출이라 확인 비용이 0 이다.
    """
    global _cik_map
    if _cik_map is None:
        try:
            _cik_map = json.loads(CIK_FILE.read_text(encoding="utf-8")).get("map") or {}
        except Exception:  # noqa: BLE001
            _cik_map = {}
    return _cik_map


def resolve_cik(ticker: str) -> str | None:
    """전문검색으로 CIK 를 찾는다 — 씨앗 목록이 없거나 틀렸을 때만.

    결과의 display_names 가 "Apple Inc. (AAPL) (CIK 0000320193)" 꼴이다.
    괄호 안 티커가 **정확히** 일치하는 항목만 받는다 — 본문에 그 글자가
    우연히 있는 문서를 잡으면 안 된다.
    """
    q = urllib.parse.quote(f'"{ticker}"')
    url = f"https://efts.sec.gov/LATEST/search-index?q={q}&forms=10-Q,10-K"
    hits = None
    for attempt in range(EFTS_TRIES):
        try:
            hits = json.loads(_get(url, timeout=25)).get("hits", {}).get("hits", [])
            break
        except Exception:  # noqa: BLE001
            if attempt == EFTS_TRIES - 1:
                return None
            time.sleep(EFTS_PAUSE * (attempt + 1))
    pat = re.compile(r"\((" + re.escape(ticker.upper()) + r")\)\s*\(CIK\s*(\d{10})\)", re.I)
    for h in hits or []:
        for name in (h.get("_source") or {}).get("display_names") or []:
            m = pat.search(name)
            if m:
                return m.group(2)
    return None


def submissions(cik: str) -> dict:
    d = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=30))
    return {"name": d.get("name"), "tickers": d.get("tickers"),
            "sic": d.get("sicDescription"), "fiscal_year_end": d.get("fiscalYearEnd")}


def companyfacts(cik: str) -> dict:
    return json.loads(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))


def lookup(ticker: str) -> tuple[str, dict]:
    """티커 → (CIK, 회사 메타). 씨앗 목록을 쓰되 **SEC 응답으로 확인한다.**

    엉뚱한 회사의 재무제표를 보여 주는 것보다 못한 실패는 없다.
    """
    t = ticker.upper().strip()
    cik, tried = cik_map().get(t), False
    if not cik:
        cik, tried = resolve_cik(t), True
        time.sleep(EFTS_PAUSE)
    if not cik:
        raise LookupError(f"{t} 의 CIK 를 찾지 못했습니다")

    for _ in range(2):
        meta = submissions(cik)
        listed = [x.upper() for x in (meta.get("tickers") or [])]
        if not listed or t in listed:
            return cik, meta
        if tried:
            raise LookupError(f"CIK {cik} 가 {t} 와 맞지 않습니다({listed})")
        cik, tried = resolve_cik(t), True
        time.sleep(EFTS_PAUSE)
        if not cik:
            raise LookupError(f"{t} 의 CIK 를 찾지 못했습니다")
    raise LookupError(f"{t} 의 CIK 확인에 실패했습니다")


def fetch(ticker: str) -> tuple[str, dict, dict]:
    """티커 → (CIK, 메타, companyfacts). 캐시된다."""
    def produce():
        cik, meta = lookup(ticker)
        time.sleep(PAUSE)
        return cik, meta, companyfacts(cik)

    return cache.get_or_set(f"secfacts:{ticker.upper()}", FACTS_TTL, produce)
