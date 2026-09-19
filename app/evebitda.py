"""12M forward EV/EBITDA — PER 과 같은 틀, 재료만 다르다.

PER 은 분자가 주가 하나라 간단하다. EV 는 분자를 **매 시점 다시 만들어야**
한다.

    EV(t) = 주가(t) × 발행주식수 + 총차입금 − 현금성자산 + 비지배지분 + 우선주

뒤의 네 항목은 재무상태표에서 오고, 재무상태표는 분기에 한 번 바뀐다. 그러니
EV 는 "주가만 매일 움직이고 나머지는 발표일마다 계단을 밟는" 모양이 된다.
계단을 밟는 날은 PER 과 같은 **실적발표일**이다 — 분기말에 밟으면 아직 공개
되지 않은 재무상태표로 그 사이 주가를 나누게 된다.

실측(tools/ev_probe.py, 2026-09-19, AAPL·PLD):

  EDGAR 재무상태표 태그는 **59~70분기**가 잡힌다. 야후의 분기 재무상태표는
  7분기뿐이라 5년을 그릴 수 없다 — 그래서 EDGAR 를 쓴다.
  **회사마다 쓰는 태그가 천차만별이다.** PLD 는 ``LongTermDebt`` 하나뿐이고
  유동차입금·CP·전환사채·리스부채 태그가 **아예 없다.** 없는 것을 0 으로 채우면
  조용히 틀린 값이 되므로, 무엇이 잡혔고 무엇이 없었는지 화면에 같이 싣는다.
  AAPL 현금(현금+단기투자) 62,399,000,576 은 야후 totalCash 와 **정확히 일치**
  했다. 차입금은 야후보다 12.5B 크다 — 리스부채를 넣기 때문이고, 의도한 차이다.

**이중계상**이 제일 무서운 함정이다. ``LongTermDebtNoncurrent`` 는 대개 전환
사채를 **이미 포함한** 합계다. 거기에 ``ConvertibleNotesPayable`` 을 또 더하면
부채가 두 번 들어간다. 그래서 개념마다 **버킷**을 두고, 한 버킷에서는 잡히는
첫 태그 **하나만** 쓴다. 전환사채는 장기차입금 버킷의 **대체 태그**로 넣어,
장기차입금 태그가 아예 없는 회사에서만 쓰이게 한다.

EBITDA 컨센은 무료 출처가 없다(실측: 야후·Alpha Vantage 에 항목 자체가 없고
FMP 는 유료). 그래서 점선 구간은 **매출 컨센 × 최근 EBITDA 마진**으로 만든다.
컨센이 아니라 가정이므로 그렇게 라벨링한다.
"""

from __future__ import annotations

from datetime import date

from . import forwardper, fundamentals

EV_QUARTERS = 32          # PER 과 같다 — 5년 앞을 보려면 더 뒤부터 있어야 한다
MARGIN_QUARTERS = 8       # EBITDA 마진을 볼 과거 분기 수
ASOF_DAYS = 100           # 분기말에서 이만큼 안쪽의 재무상태표만 그 분기 것으로 본다

# --- 버킷 ------------------------------------------------------------------
# 한 버킷 = 한 개념. 그 안에서는 **잡히는 첫 태그 하나만** 쓴다(이중계상 방지).
# 버킷끼리는 더한다.
DEBT_BUCKETS = {
    # 전환사채 태그가 뒤에 붙어 있는 건 **대체**다. 장기차입금 합계는 전환사채를
    # 이미 담고 있어서, 둘 다 더하면 두 번 들어간다.
    "장기차입금(비유동)": ["LongTermDebtNoncurrent",
                       "LongTermDebtAndCapitalLeaseObligations",
                       "LongTermDebt",
                       "ConvertibleDebtNoncurrent", "ConvertibleNotesPayable"],
    "장기차입금(유동)": ["LongTermDebtCurrent",
                     "LongTermDebtAndCapitalLeaseObligationsCurrent",
                     "ConvertibleNotesPayableCurrent"],
    "단기차입금·CP": ["ShortTermBorrowings", "CommercialPaper",
                   "OtherShortTermBorrowings"],
    "운용리스부채(비유동)": ["OperatingLeaseLiabilityNoncurrent"],
    "운용리스부채(유동)": ["OperatingLeaseLiabilityCurrent"],
    "금융리스부채(비유동)": ["FinanceLeaseLiabilityNoncurrent"],
    "금융리스부채(유동)": ["FinanceLeaseLiabilityCurrent"],
}
# ``…AndCapitalLeaseObligations`` 는 금융리스를 이미 담고 있다. 그 태그가 쓰였으면
# 금융리스 버킷은 건너뛴다.
LEASE_INSIDE = {"LongTermDebtAndCapitalLeaseObligations": "금융리스부채(비유동)",
                "LongTermDebtAndCapitalLeaseObligationsCurrent": "금융리스부채(유동)"}

CASH_BUCKETS = {
    "현금성자산": ["CashAndCashEquivalentsAtCarryingValue",
               "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "단기투자자산": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
}
# 비지배지분은 ``MinorityInterest`` **하나만** 쓴다.
# ``StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`` 는
# 이름이 비슷하지만 **자본 총계**다 — 그걸 더하면 EV 가 자본만큼 부풀어 오른다.
OTHER_BUCKETS = {
    "비지배지분": ["MinorityInterest"],
    "우선주": ["PreferredStockValue"],
}
SHARE_TAGS = ["CommonStockSharesOutstanding", "CommonStockSharesIssued"]
DEI_SHARE_TAGS = ["EntityCommonStockSharesOutstanding"]


# --- 재무상태표 읽기 ---------------------------------------------------------
def instants(facts: dict, tag: str, ns: str = "us-gaap") -> dict[str, float]:
    """**시점**값만 추린다 — 재무상태표 항목은 기간이 없다.

    기간 사실(매출 등)은 ``start`` 와 ``end`` 가 다르다. 시점 사실은 ``start``
    가 없거나 ``end`` 와 같다. 같은 날짜가 여러 번이면(정정) 마지막 제출본.
    """
    node = (facts.get("facts") or {}).get(ns, {}).get(tag) or {}
    picked: dict[str, tuple[float, str]] = {}
    for series in (node.get("units") or {}).values():
        for f in series:
            if f.get("start") and f.get("start") != f.get("end"):
                continue
            end, val, filed = f.get("end"), f.get("val"), f.get("filed") or ""
            if end is None or val is None:
                continue
            cur = picked.get(end)
            if cur is None or filed >= cur[1]:
                picked[end] = (float(val), filed)
    return {e: v for e, (v, _) in picked.items()}


def _bucket(facts: dict, tags: list[str]) -> tuple[dict[str, float], str | None]:
    """버킷 하나 — 잡히는 **첫 태그**를 통째로 쓴다.

    날짜별로 태그를 섞지 않는다. 정의가 다른 태그를 날짜마다 갈아 끼우면
    그 이음매가 가짜 부채 증감이 된다(EV 가 한 분기 만에 튄다).
    """
    for tag in tags:
        d = instants(facts, tag)
        if d:
            return d, tag
    return {}, None


def _asof(series: dict[str, float], end: str) -> float | None:
    """그 분기말에 해당하는 값 — 가장 가까운 날짜, 단 한 분기 안쪽만.

    재무상태표 날짜는 분기말과 며칠씩 어긋난다(애플은 52/53주 회계연도라
    9월 27일에 끝난다). 멀리서 끌어오면 몇 분기 전 값이 조용히 붙으므로
    ``ASOF_DAYS`` 밖은 **없는 것으로 둔다.**
    """
    e = forwardper._d(end)
    if e is None:
        return None
    best, gap = None, None
    for k, v in series.items():
        d = forwardper._d(k)
        if d is None:
            continue
        g = abs((d - e).days)
        if g <= ASOF_DAYS and (gap is None or g < gap):
            best, gap = v, g
    return best


def balance_sheet(facts: dict) -> dict:
    """EV 재료를 버킷별로 모아 둔다 — 어느 태그에서 왔는지까지.

    없는 버킷을 0 으로 **채우지 않는다.** 그냥 빠진다. 대신 어떤 버킷이
    비었는지 그대로 실어 보내 화면이 "이 회사는 리스부채 태그가 없습니다"
    라고 말할 수 있게 한다 — 조용한 0 이 제일 나쁘다.
    """
    used: dict[str, str] = {}
    debt: dict[str, dict[str, float]] = {}
    skip: set[str] = set()
    for name, tags in DEBT_BUCKETS.items():
        if name in skip:
            continue
        rows, tag = _bucket(facts, tags)
        if not rows:
            continue
        used[name] = tag
        debt[name] = rows
        if tag in LEASE_INSIDE:
            skip.add(LEASE_INSIDE[tag])      # 이미 안에 들어 있다

    cash: dict[str, dict[str, float]] = {}
    for name, tags in CASH_BUCKETS.items():
        rows, tag = _bucket(facts, tags)
        if rows:
            used[name], cash[name] = tag, rows

    other: dict[str, dict[str, float]] = {}
    for name, tags in OTHER_BUCKETS.items():
        rows, tag = _bucket(facts, tags)
        if rows:
            used[name], other[name] = tag, rows

    shares, stag = _bucket(facts, SHARE_TAGS)
    if not shares:
        # 표지(cover page)에 실리는 dei 태그로 물러선다. 날짜가 제출일이라
        # 분기말과 한 달쯤 어긋나지만 ``_asof`` 가 흡수한다.
        for tag in DEI_SHARE_TAGS:
            d = instants(facts, tag, "dei")
            if d:
                shares, stag = d, f"dei:{tag}"
                break
    if shares:
        used["발행주식수"] = stag

    return {"debt": debt, "cash": cash, "other": other, "shares": shares,
            "tags": used,
            "missing": [n for n in list(DEBT_BUCKETS) + list(CASH_BUCKETS) +
                        list(OTHER_BUCKETS) if n not in used and n not in skip]}


def components(bs: dict, end: str) -> dict | None:
    """분기말 하나의 EV 구성요소. 주식수가 없으면 EV 를 만들 수 없다."""
    sh = _asof(bs.get("shares") or {}, end)
    if not sh or sh <= 0:
        return None
    parts = {}
    debt = 0.0
    for name, rows in (bs.get("debt") or {}).items():
        v = _asof(rows, end)
        if v is None:
            continue
        parts[name] = v
        debt += v
    cash = 0.0
    for name, rows in (bs.get("cash") or {}).items():
        v = _asof(rows, end)
        if v is None:
            continue
        parts[name] = v
        cash += v
    extra = 0.0
    for name, rows in (bs.get("other") or {}).items():
        v = _asof(rows, end)
        if v is None:
            continue
        parts[name] = v
        extra += v
    return {"shares": sh, "debt": debt, "cash": cash, "other": extra,
            # 주가에 곱할 것 말고 **더할 것** — EV = 주가×주식수 + adj
            "adj": debt - cash + extra, "net_debt": debt - cash, "parts": parts}


# --- 창에 EV 붙이기 ----------------------------------------------------------
def attach_ev(windows: list[dict], bs: dict) -> list[dict]:
    """창마다 그 시점에 **시장이 알고 있던** 재무상태표를 붙인다.

    창은 i 분기 발표일에 열린다. 그때 시장이 아는 마지막 재무상태표는 i 분기말
    것이다 — 그래서 ``basis_end`` 를 쓴다. 다음 발표까지 그대로 유지된다.
    """
    out = []
    for w in windows:
        c = components(bs, w["basis_end"])
        if c is None:
            continue
        out.append({**w, "ev": c})
    return out


def ratio_series(dates: list[str], closes: list[float],
                 windows: list[dict]) -> list[dict]:
    """주가 계열 → EV/EBITDA 계열.

    EBITDA 합이 0 이하면 배수를 내지 않는다(``None``). 적자 EBITDA 의 배수는
    음수로 나와 차트도 독해도 망가뜨린다. EV 가 음수인 경우(순현금이 시총보다
    큰 회사)도 같은 이유로 비운다.
    """
    if not windows:
        return []
    wins = sorted(windows, key=lambda w: w["from"])
    out, wi = [], -1
    for d, c in zip(dates, closes):
        while wi + 1 < len(wins) and wins[wi + 1]["from"] <= d:
            wi += 1
        if wi < 0:
            out.append({"date": d, "close": c, "ratio": None})
            continue
        w = wins[wi]
        if w["to"] and d >= w["to"]:
            out.append({"date": d, "close": c, "ratio": None})
            continue
        ev = c * w["ev"]["shares"] + w["ev"]["adj"]
        e = w["eps"]                      # 창의 합계 — 여기서는 EBITDA 합이다
        out.append({"date": d, "close": c, "ev": ev,
                    "ratio": round(ev / e, 3) if e and e > 0 and ev > 0 else None,
                    "confirmed": w["confirmed"], "basis_end": w["basis_end"],
                    "announced": w["from"]})
    return out


# --- 미래 분기 EBITDA(가정) --------------------------------------------------
def margin(ebitda: dict[str, float], revenue: dict[str, float],
           n: int = MARGIN_QUARTERS) -> tuple[float | None, dict]:
    """최근 n 분기 EBITDA 마진의 **중앙값**.

    평균이 아니라 중앙값이다 — 일회성 손익이 낀 한 분기에 끌려가지 않게.
    매출이 0 이하인 분기는 버린다.
    """
    rows = []
    for end in sorted(set(ebitda) & set(revenue), reverse=True):
        r, e = revenue[end], ebitda[end]
        if r and r > 0 and e is not None:
            rows.append(e / r)
        if len(rows) >= n:
            break
    if not rows:
        return None, {"quarters": 0}
    s = sorted(rows)
    k = len(s)
    med = s[k // 2] if k % 2 else (s[k // 2 - 1] + s[k // 2]) / 2
    return med, {"quarters": k, "low": round(min(s), 4), "high": round(max(s), 4)}


# --- 조립 -------------------------------------------------------------------
def build(facts: dict, con: dict, fy_ends: list[str], dates: list[str],
          close: list[float], quarters: int = EV_QUARTERS) -> dict | None:
    """EDGAR + 컨센 + 주가 → EV/EBITDA 차트 묶음.

    내는 키 이름은 PER 차트와 **일부러 같게** 둔다(``per_confirmed`` 등).
    화면이 같은 코드로 두 지표를 그리기 때문이다. 어느 지표인지는 ``metric``
    에 적는다.
    """
    ebitda, ebitda_src = fundamentals.ebitda_rows(facts)
    rows = fundamentals._series(ebitda, quarters)
    if len(rows) < 8:
        return {"error": "EBITDA 분기가 8개도 안 돼 EV/EBITDA 를 그릴 수 없습니다"
                         f"({len(rows)}분기). 은행·보험은 영업이익 개념이 없어 "
                         "EBITDA 를 만들지 않습니다."}

    bs = balance_sheet(facts)
    if not bs["shares"]:
        return {"error": "발행주식수 태그를 찾지 못해 시가총액을 만들 수 없습니다."}

    announced = [a["date"] for a in (con.get("announcements") or [])]
    qs = forwardper.match_announcements(rows, announced)
    known = {q["end"]: q["val"] for q in qs if q.get("val") is not None}

    rev_rows, _ = fundamentals.revenue_rows(facts)
    rev_known = {e: r["val"] for e, r in rev_rows.items() if r.get("val") is not None}
    mgn, mgn_why = margin({q["end"]: q["val"] for q in qs}, rev_known)

    future = forwardper.project_ends(qs[-1]["end"], 8)
    est, est_note = _estimate(future, con, fy_ends, rev_known, mgn)

    windows = attach_ev(forwardper.forward_windows(qs, est), bs)
    series = ratio_series(dates, close, windows)
    if not series:
        return {"error": "주가나 발표일이 없어 EV/EBITDA 계열을 만들지 못했습니다."}

    solid = [r["ratio"] if r.get("confirmed") else None for r in series]
    dashed = [r["ratio"] if r.get("confirmed") is False else None for r in series]
    for i in range(1, len(series)):
        if solid[i] is None and solid[i - 1] is not None and dashed[i] is not None:
            dashed[i - 1] = solid[i - 1]          # 이음매를 잇는다

    last = windows[-1] if windows else None
    return {
        "metric": "ev",
        "metric_label": "12M forward EV/EBITDA",
        # 축 기본 창. PER 은 0–50 이지만 EV/EBITDA 는 대개 한 자리~20 대라
        # 같은 창을 쓰면 선이 바닥에 붙는다.
        "axis": [0, 30],
        "dates": [r["date"] for r in series],
        "close": [r["close"] for r in series],
        "per_confirmed": solid,
        "per_estimated": dashed,
        "marks": [{"announced": w["from"], "to": w["to"],
                   "basis_end": w["basis_end"], "confirmed": w["confirmed"],
                   "eps": w["eps"], "estimated": w["estimated"],
                   "shares": w["ev"]["shares"], "adj": w["ev"]["adj"],
                   "source": w.get("announced_source")} for w in windows],
        "quarters": [{"end": q["end"], "announced": q.get("announced"),
                      "source": q.get("announced_source"), "eps": q.get("val")}
                     for q in qs],
        "estimates": [{"end": e, "eps": None if v.get("val") is None else round(v["val"], 0),
                       "source": v["source"], "note": v.get("note")}
                      for e, v in sorted(est.items())],
        "ebitda_source": ebitda_src,
        "margin": None if mgn is None else round(mgn, 4),
        "margin_why": mgn_why,
        "estimate_note": est_note,
        "tags": bs["tags"],
        "missing": bs["missing"],
        "latest": None if last is None else {
            "end": last["basis_end"], "announced": last["from"],
            "shares": last["ev"]["shares"], "debt": last["ev"]["debt"],
            "cash": last["ev"]["cash"], "other": last["ev"]["other"],
            "net_debt": last["ev"]["net_debt"], "parts": last["ev"]["parts"],
            "ebitda": last["eps"], "estimated": last["estimated"]},
        "basis": "실적발표일",
        "note": (
            "EV = 주가 × 발행주식수 + 총차입금 − 현금성자산 + 비지배지분 + 우선주. "
            "재무상태표는 분기에 한 번 바뀌므로 **실적발표일마다** 계단을 밟고, "
            "그 사이에는 주가만 움직입니다. EBITDA 는 영업이익 + 감가상각인 "
            "계산값이라 회사가 말하는 Adjusted EBITDA 와 다릅니다(주식보상을 "
            "되돌리지 않습니다). 리스부채를 차입금에 넣으면서 EBITDA 에서 "
            "리스비용을 되돌리지는 않아, 리스가 큰 회사의 배수는 높게 나옵니다."),
    }


def _estimate(future: list[str], con: dict, fy_ends: list[str],
              rev_known: dict[str, float], mgn: float | None
              ) -> tuple[dict[str, dict], str]:
    """미발표 분기의 EBITDA — **컨센이 아니라 가정**이다.

    EBITDA 컨센을 주는 무료 출처가 없다(야후·Alpha Vantage 에 항목 자체가 없고
    FMP 는 유료). 그래서 매출 컨센을 PER 과 똑같은 계절성 규칙으로 분기에 나눈
    다음, 최근 EBITDA 마진의 중앙값을 곱한다. 마진이 흔들리는 회사에서는
    빗나가므로 화면에도 "가정" 이라고 적는다.
    """
    from . import consensus

    if mgn is None:
        return {}, "최근 EBITDA 마진을 구하지 못해 추정 구간을 그리지 않습니다."
    rev_est = forwardper.fill_estimates(future, consensus.revenue_estimates(con),
                                        fy_ends, rev_known)
    if not rev_est:
        return {}, "매출 컨센이 없어 추정 구간을 그리지 않습니다."
    out = {}
    for end, r in rev_est.items():
        v = r.get("val")
        out[end] = {"val": None if v is None else v * mgn,
                    "source": f"{r['source']} × 마진 {mgn * 100:.1f}%",
                    "note": r.get("note")}
    return out, (f"EBITDA 컨센이 없어 **매출 컨센 × 최근 EBITDA 마진 "
                 f"{mgn * 100:.1f}%** 로 만든 가정치입니다.")
