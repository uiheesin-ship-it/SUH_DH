"""국장 컨센서스와 상장주식수 — 네이버 모바일 API.

미장의 야후 자리에 들어간다. 키가 필요 없고 지연도 없다.

    m.stock.naver.com/api/stock/{종목코드}/finance/quarter
    m.stock.naver.com/api/stock/{종목코드}/finance/annual

실측(tools/kr_fundamentals_probe.py, 2026-09-18, 삼성전자·KB금융·에코프로비엠):

  ``financeInfo.trTitleList`` 의 기간마다 **isConsensus** 플래그가 붙는다.
  확정과 추정이 **한 응답에** 같이 온다 — 미장에서 실선/점선을 나눈 것과 정확히
  같은 구조다.
  분기는 **6기간(확정 5 + 추정 1)**, 연간은 **4기간(확정 3 + 추정 1)**.
  ``financeInfo.rowList`` 에 매출액·영업이익·당기순이익·지배주주순이익·EPS·
  BPS·PER 등 16행이 온다.
  금액 단위는 **억원**이다(삼성전자 2025 3분기 매출 860,617 = 86.06조).
  EPS 는 원. 단위는 여기서 원으로 바꿔 내보낸다 — 화면에서 다시 줄인다.

**한계가 뚜렷하다.** 앞으로 오는 건 분기 **하나**와 연간 **하나**뿐이다. 미장은
야후가 분기 2 + 연간 2 를 줘서 12개월 네 분기를 계절성으로 채웠는데, 국장은
올해 남은 분기까지밖에 안 채워진다. 그래서 회계연도 후반에는 12M forward 창이
다 안 채워져 그 구간이 비게 된다 — 지어내지 않고 비운다.
"""

from __future__ import annotations

import json
import os
import urllib.request

from . import cache

KR_CONSENSUS_TTL = float(os.environ.get("SUH_DH_KR_CONSENSUS_TTL", "3600"))
BASE = "https://m.stock.naver.com/api/stock"
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
EOK = 100_000_000.0       # 억원 → 원

# 네이버 행 이름 → 우리 항목 이름. 금액인지 주당인지에 따라 단위가 다르다.
ROWS = {
    "매출액": ("매출", True),
    "영업이익": ("영업이익", True),
    "당기순이익": ("당기순이익", True),
    "지배주주순이익": ("지배주주순이익", True),
    "EPS": ("희석EPS", False),
}


def _get(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://m.stock.naver.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _num(x):
    """네이버는 숫자를 "1,234" / "-" / "-5" 로 준다."""
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if not s or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows(fi: dict) -> list[dict]:
    for k in ("rowList", "financeDetail", "list", "rows"):
        v = fi.get(k)
        if isinstance(v, list) and v:
            return v
    for v in fi.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _period(fi: dict) -> dict[str, bool]:
    """기간 키(YYYYMM) → 추정인가.

    trTitleList 의 title 은 "2026.09." 꼴이다. rowList 의 값 키는 "202609" 라
    점을 빼서 맞춘다.
    """
    out = {}
    for t in fi.get("trTitleList") or []:
        title = (t.get("title") or "").replace(".", "").strip()
        if len(title) >= 6:
            out[title[:6]] = (t.get("isConsensus") == "Y")
    return out


def _parse(payload: dict) -> dict:
    fi = (payload or {}).get("financeInfo") or {}
    periods = _period(fi)
    out: dict[str, dict] = {k: {"consensus": v} for k, v in periods.items()}
    for row in _rows(fi):
        name = (row.get("title") or row.get("krName") or row.get("name") or "").strip()
        spec = ROWS.get(name)
        if spec is None:
            continue
        label, is_money = spec
        vals = row.get("value") or row.get("valueList") or row.get("values") or {}
        if not isinstance(vals, dict):
            continue
        for key, cell in vals.items():
            v = _num((cell or {}).get("value") if isinstance(cell, dict) else cell)
            if v is None:
                continue
            if isinstance(cell, dict) and cell.get("cx") == "minus" and v > 0:
                v = -v
            out.setdefault(key, {"consensus": periods.get(key, False)})
            out[key][label] = v * EOK if is_money else v
    return out


def fetch(code: str) -> dict:
    """한 종목의 분기·연간 실적+컨센. 실패해도 예외를 던지지 않는다.

    컨센이 없어도 확정 구간(차트의 대부분)은 그려져야 한다. 그래서 조각마다
    따로 막아 둔다.
    """
    def produce():
        out = {"code": code, "quarters": {}, "years": {}, "shares": None,
               "price": None, "market_cap": None, "sources": []}
        for kind, key in (("quarter", "quarters"), ("annual", "years")):
            try:
                out[key] = _parse(_get(f"{BASE}/{code}/finance/{kind}"))
                if out[key]:
                    out["sources"].append(f"네이버 finance/{kind}")
            except Exception:  # noqa: BLE001
                pass
        try:
            d = _get(f"{BASE}/{code}/integration")
            out["name"] = d.get("stockName") or d.get("itemName")
            out["shares"] = _num((d.get("stockItemTotalInfos") and
                                  _find(d, "상장주식수")) or d.get("listedStockCount"))
            out["market_cap"] = _num(_find(d, "시가총액"))
            out["price"] = _num(d.get("closePrice"))
        except Exception:  # noqa: BLE001
            pass
        return out

    return cache.get_or_set(f"krconsensus:{code}", KR_CONSENSUS_TTL, produce,
                            cache_when=lambda v: bool(v.get("quarters")))


def _find(payload: dict, label: str):
    """네이버 통합 응답에서 이름표로 값을 찾는다.

    ``stockItemTotalInfos`` 같은 목록이 [{"key": "상장주식수", "value": "5,969,782,550"}]
    꼴로 온다. 키 이름이 버전마다 달라서 **이름표로** 찾는다 — 모양이 바뀌어도
    안 깨지고, 못 찾으면 그냥 없는 값이 된다.
    """
    stack = [payload]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("key") == label or cur.get("name") == label:
                return cur.get("value")
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def series(con: dict, kind: str, label: str) -> tuple[dict[str, float], dict[str, float]]:
    """(확정, 추정) 두 묶음으로 나눈다 — 키는 "YYYYMM"."""
    src = (con or {}).get("quarters" if kind == "quarter" else "years") or {}
    known, est = {}, {}
    for key, row in src.items():
        v = row.get(label)
        if v is None:
            continue
        (est if row.get("consensus") else known)[key] = v
    return known, est
