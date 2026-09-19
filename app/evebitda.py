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
ASOF_BACK = 100           # 분기말 **이전** 이만큼 안쪽의 값만 그 분기 것으로 본다
ASOF_AHEAD = 45           # 분기말 **이후**는 이만큼만 — 표지(dei)의 제출일 때문

# --- 버킷 ------------------------------------------------------------------
# 한 버킷 = 한 개념. 그 안에서는 **잡히는 첫 태그 하나만** 쓴다(이중계상 방지).
# 버킷끼리는 더한다.
DEBT_BUCKETS = {
    "장기차입금(비유동)": ["LongTermDebtNoncurrent",
                       "LongTermDebtAndCapitalLeaseObligations",
                       "LongTermDebt",
                       # 실측(SMCI 2026-06-30): 위 셋이 다 끊긴 뒤 이 태그에만
                       # 4.06B 이 남아 있었다. "장·단기 차입금 합계" 라는 뜻이다.
                       "DebtLongtermAndShorttermCombinedAmount"],
    "장기차입금(유동)": ["LongTermDebtCurrent",
                     "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "단기차입금·CP": ["ShortTermBorrowings", "CommercialPaper",
                   "OtherShortTermBorrowings"],
    # 전환사채는 **따로 더한다.** 대개 장기차입금 합계 안에 이미 들어 있지만,
    # 아닌 회사가 있다 — 실측(SMCI)에서 전환사채 4.66B 이 합계 4.06B 과 별개로
    # 잡혔고, 둘을 더해야 야후 값과 정확히 맞았다. 포함 여부는 아래
    # ``CONTAINED_IF_LARGER`` 가 **금액으로** 판정한다.
    "전환사채(비유동)": ["ConvertibleLongTermNotesPayable", "ConvertibleDebtNoncurrent",
                     "ConvertibleNotesPayable"],
    "전환사채(유동)": ["ConvertibleNotesPayableCurrent", "ConvertibleDebtCurrent"],
    "운용리스부채(비유동)": ["OperatingLeaseLiabilityNoncurrent"],
    "운용리스부채(유동)": ["OperatingLeaseLiabilityCurrent"],
    # 유동·비유동을 안 나누고 합계만 올리는 회사가 있다. 나눠 올린 회사에서는
    # 아래 ``SPLIT_WINS`` 가 이걸 뺀다(안 그러면 리스가 두 배가 된다).
    "운용리스부채(합계)": ["OperatingLeaseLiability"],
    "금융리스부채(비유동)": ["FinanceLeaseLiabilityNoncurrent"],
    "금융리스부채(유동)": ["FinanceLeaseLiabilityCurrent"],
}
# ``…AndCapitalLeaseObligations`` 는 금융리스를 이미 담고 있다. 그 태그가 쓰인
# 날짜에는 금융리스 버킷을 건너뛴다.
LEASE_INSIDE = {"LongTermDebtAndCapitalLeaseObligations": "금융리스부채(비유동)",
                "LongTermDebtAndCapitalLeaseObligationsCurrent": "금융리스부채(유동)"}
# **금액으로** 판정하는 포함 관계. 합계가 전환사채보다 크거나 같으면 그 안에
# 들어 있다고 보고 전환사채를 빼고, 작으면 별개로 보고 더한다. 합계가 부분보다
# 작을 수는 없다는 산수 하나에 기대는 규칙이라 태그 이름 추측보다 튼튼하다.
#
# 실측으로 양쪽이 다 나온다. SMCI 2024-03-31 은 장기차입금 85.6M 에 전환사채
# 1,696M — 은행 대출과 전환사채가 별개다. 2026-06-30 은 합계 4.06B 에 전환사채
# 4.66B — 역시 별개다. MSTR 2021-03-31 은 장기차입금이 전환사채보다 커서 안에
# 들어 있다.
CONTAINED_IF_LARGER = {"전환사채(비유동)": "장기차입금(비유동)",
                       "전환사채(유동)": "장기차입금(유동)"}
# 유동·비유동을 나눠 올렸으면 합계 태그는 쓰지 않는다.
SPLIT_WINS = {"운용리스부채(합계)": ("운용리스부채(비유동)", "운용리스부채(유동)")}

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
# 발행주식수만 **날짜별로 합친다** — 다른 버킷과 규칙이 다르다.
#
# 실측(2026-09-19): WMT 는 ``CommonStockSharesOutstanding`` 이 **2012년까지
# 4분기**밖에 없다. 버킷 규칙(첫 태그 하나만)을 그대로 쓰면 그 4분기를 잡고
# 멈춰서 최근 시총을 못 만들고, EV/EBITDA 가 통째로 안 그려졌다. 주식수는
# 부채와 달리 **같은 개념을 여러 태그가 나눠 담고 있을 뿐**이라 날짜별로
# 우선순위대로 메우는 게 맞다(fundamentals.collect 과 같은 방식).
#
# 순서에 뜻이 있다. 표지(dei)의 것은 제출일 기준 **실제 유통주식수**라
# ``CommonStockSharesIssued``(자기주식 포함) 보다 낫다 — JPM 은 발행 41.0억
# 주 vs 유통 27.0억 주로 1.5배 차이가 난다.
SHARE_SOURCES = [("us-gaap", "CommonStockSharesOutstanding"),
                 ("dei", "EntityCommonStockSharesOutstanding"),
                 ("us-gaap", "CommonStockSharesIssued")]
# 마지막 수단: **가중평균 희석주식수**(손익 쪽 항목이라 시점값이 아니다).
#
# 차등의결권(듀얼클래스) 회사는 위 세 태그가 다 비어 있을 수 있다 — 보통주를
# Class A/B 로 나눠 올리면 companyfacts 에는 차원이 붙은 사실이 실리지 않아
# 총계가 사라진다(실측: MSTR 은 셋 다 0개라 EV 를 못 만들었다).
#
# 기말 발행주식수가 아니라 그 분기의 **평균**이고 희석 효과가 들어가 있어
# 정의가 다르다. 그래도 0 이나 '못 그림' 보다는 낫고, 어느 쪽을 썼는지는
# 화면에 그대로 적는다.
SHARE_FALLBACK_LABEL = "가중평균 희석주식수(기말 발행주식수 아님)"


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

def _bucket(facts: dict, tags: list[str]) -> dict[str, tuple[float, str]]:
    """버킷 하나 — **날짜마다** 잡히는 첫 태그 하나를 쓴다.

    한 날짜에 태그를 하나만 쓰는 것이 이중계상을 막는 규칙이다. 처음에는 회사
    전체에서 첫 태그 하나를 골라 통째로 썼는데, 그러면 **회사가 자금조달 수단을
    바꾼 구간이 통째로 0 이 된다.**

    실측(SMCI, 2026-09-19)이 그랬다. 옛날에는 은행 차입이 있어
    ``LongTermDebtNoncurrent`` 가 버킷을 차지했는데 지금은 전환사채
    (``ConvertibleNotesPayable``, 약 9B)로 갈아탔다. 최근 분기 차입금이 리스부채
    0.54B 만 남아 EV 가 야후보다 **41% 작게** 나왔다.

    날짜별로 우선순위를 다시 매기면 양쪽 구간이 다 맞는다. 같은 날짜에 장기차입금
    합계와 전환사채가 **둘 다** 있으면 합계가 이기므로(전환사채는 그 안에 이미
    들어 있다) 이중계상도 그대로 막힌다.
    """
    out: dict[str, tuple[float, str]] = {}
    for tag in tags:
        for end, v in instants(facts, tag).items():
            out.setdefault(end, (v, tag))
    return out


def _asof(series: dict, end: str):
    """그 분기말에 해당하는 값 — **앞뒤를 다르게** 본다.

    재무상태표 날짜는 분기말과 며칠씩 어긋난다(애플은 52/53주 회계연도라
    9월 27일에 끝난다). 그렇다고 앞뒤를 똑같이 열어 두면 안 된다. 분기말
    **뒤**로 90일쯤 열면 **다음 분기 재무상태표**가 끌려 들어올 수 있고, 그건
    그 발표 시점에 시장이 몰랐던 값이다 — 미래 정보가 과거 차트에 새어 든다.

    그래서 뒤쪽은 ``ASOF_AHEAD`` 일까지만 연다. 표지(dei)의 발행주식수는 제출일
    기준이라 분기말보다 2~4주 늦게 찍히는데, 그건 **그 분기 보고서와 같이**
    공개되므로 발표 시점에 알 수 있는 값이다. 앞쪽은 한 분기(``ASOF_BACK``)
    까지 열고, 그 밖은 **없는 것으로 둔다** — 몇 분기 전 숫자가 조용히 붙는
    것보다 비는 편이 낫다.
    """
    e = forwardper._d(end)
    if e is None:
        return None
    back, ahead = None, None
    for k, v in series.items():
        d = forwardper._d(k)
        if d is None:
            continue
        g = (d - e).days
        if -ASOF_BACK <= g <= 0 and (back is None or -g < back[0]):
            back = (-g, v)
        elif 0 < g <= ASOF_AHEAD and (ahead is None or g < ahead[0]):
            ahead = (g, v)
    if back is not None:
        return back[1]
    return None if ahead is None else ahead[1]


def balance_sheet(facts: dict) -> dict:
    """EV 재료를 버킷별로 모아 둔다 — 날짜마다 어느 태그에서 왔는지까지.

    없는 버킷을 0 으로 **채우지 않는다.** 그냥 빠진다. 대신 어떤 버킷이
    비었는지 그대로 실어 보내 화면이 "이 회사는 리스부채 태그가 없습니다"
    라고 말할 수 있게 한다 — 조용한 0 이 제일 나쁘다.
    """
    used: dict[str, str] = {}

    def group(spec):
        out = {}
        for name, tags in spec.items():
            rows = _bucket(facts, tags)
            if not rows:
                continue
            out[name] = rows
            # 날짜마다 태그가 다를 수 있다 — 쓰인 것을 전부 적는다.
            used[name] = " / ".join(sorted({t for _, t in rows.values()}))
        return out

    debt, cash, other = group(DEBT_BUCKETS), group(CASH_BUCKETS), group(OTHER_BUCKETS)

    shares: dict[str, float] = {}
    stags = []
    for ns, tag in SHARE_SOURCES:
        rows = instants(facts, tag, ns)
        if not rows:
            continue
        before = len(shares)
        for end, v in rows.items():
            shares.setdefault(end, v)       # 빈 날짜만 메운다
        if len(shares) > before:
            stags.append(tag if ns == "us-gaap" else f"{ns}:{tag}")
    if len(shares) < 8:
        # 듀얼클래스 회사는 시점 태그가 통째로 비어 있다 — 손익 쪽의
        # 가중평균 희석주식수로 물러선다.
        wa = fundamentals._metric(facts, fundamentals.SHARES_TAGS, mode="mean")
        before = len(shares)
        for end, row in wa.items():
            if row.get("val") and row["val"] > 0:
                shares.setdefault(end, float(row["val"]))
        if len(shares) > before:
            stags.append(SHARE_FALLBACK_LABEL)
    if shares:
        used["발행주식수"] = " + ".join(stags)

    return {"debt": debt, "cash": cash, "other": other, "shares": shares,
            "tags": used,
            "missing": [n for n in list(DEBT_BUCKETS) + list(CASH_BUCKETS) +
                        list(OTHER_BUCKETS) if n not in used]}


def components(bs: dict, end: str) -> dict | None:
    """분기말 하나의 EV 구성요소. 주식수가 없으면 EV 를 만들 수 없다."""
    sh = _asof(bs.get("shares") or {}, end)
    if not sh or sh <= 0:
        return None

    picked: dict[str, tuple[float, str]] = {}
    for grp in ("debt", "cash", "other"):
        for name, rows in (bs.get(grp) or {}).items():
            hit = _asof(rows, end)
            if hit is not None:
                picked[name] = hit

    # 겹치는 것을 **그 날짜의 값으로** 걷어낸다. 태그는 날짜마다 달라지므로
    # 판정도 날짜마다 해야 한다.
    dropped = []

    def drop(name):
        if name in picked:
            picked.pop(name)
            dropped.append(name)

    # ① ``…AndCapitalLeaseObligations`` 는 금융리스를 이미 담고 있다.
    for _, tag in list(picked.values()):
        if LEASE_INSIDE.get(tag):
            drop(LEASE_INSIDE[tag])
    # ② 합계가 전환사채보다 크거나 같으면 그 안에 들어 있다 — 작으면 별개다.
    for part, whole in CONTAINED_IF_LARGER.items():
        if part in picked and whole in picked and picked[whole][0] >= picked[part][0]:
            drop(part)
    # ③ 유동·비유동을 나눠 올렸으면 합계 태그는 쓰지 않는다.
    for total, splits in SPLIT_WINS.items():
        if total in picked and any(x in picked for x in splits):
            drop(total)

    parts = {n: v for n, (v, _) in picked.items()}
    debt = sum(v for n, v in parts.items() if n in DEBT_BUCKETS)
    cash = sum(v for n, v in parts.items() if n in CASH_BUCKETS)
    extra = sum(v for n, v in parts.items() if n in OTHER_BUCKETS)

    # 태그는 있는데 **이 날짜에만** 값이 없는 버킷이 있다(애플의 리스부채가
    # 그렇다). 전 기간 없는 것과 구별해서 따로 알려 준다.
    absent = [n for grp in ("debt", "cash", "other")
              for n in (bs.get(grp) or {}) if n not in parts and n not in dropped]
    return {"shares": sh, "debt": debt, "cash": cash, "other": extra,
            # 주가에 곱할 것 말고 **더할 것** — EV = 주가×주식수 + adj
            "adj": debt - cash + extra, "net_debt": debt - cash,
            "parts": parts, "absent": absent,
            "tags": {n: t for n, (_, t) in picked.items()}}

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
    # 매출이 EBITDA 보다 한 분기 더 나가 있을 수 있다(그 분기 감가상각이 아직
    # 안 잡히면 EBITDA 가 안 만들어진다). 그 분기는 곧 **추정할 분기**라,
    # 확정으로 세면 연간 컨센에서 두 번 빠져 남은 분기가 쪼그라든다.
    last_end = rows[-1]["end"]
    rev_known = {e: r["val"] for e, r in rev_rows.items()
                 if r.get("val") is not None and e <= last_end}
    mgn, mgn_why = margin({q["end"]: q["val"] for q in qs}, rev_known)

    future = forwardper.project_ends(last_end, 8)
    est, est_note = _estimate(future, con, fy_ends, rev_known, mgn)

    raw = forwardper.forward_windows(qs, est)
    windows = attach_ev(raw, bs)
    if raw and not windows:
        return {"error": "분기말마다 발행주식수를 찾지 못해 시가총액을 만들 수 "
                         f"없습니다(주식수 태그: {bs['tags'].get('발행주식수', '없음')})."}
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
            "absent": last["ev"]["absent"],
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
    if mgn <= 0:
        # 최근 절반 이상이 적자 EBITDA 라는 뜻이다. 그 마진을 매출 컨센에 곱하면
        # 음수 EBITDA 를 지어내게 되고, 배수는 어차피 비워진다. 실측(MSTR)에서
        # 중앙값이 −3081% 로 나왔다 — 그릴 값이 아니라 안 그리는 게 맞다.
        return {}, (f"최근 EBITDA 마진 중앙값이 {mgn * 100:.1f}% (적자)라 "
                    "추정 구간을 그리지 않습니다.")
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
