"""미장 개별 종목의 분기 실적 — EDGAR XBRL(data.sec.gov)에서.

이 모듈은 **네트워크를 모른다.** ``companyfacts`` JSON 을 받아 분기 시계열로
펴고 성장률을 붙이는 일만 한다. 수집은 ``tools/fundamentals_us.py`` 가 한다.
그래야 합성 데이터로 오프라인 검증이 된다(샌드박스에서는 SEC 가 막혀 있다).

실측으로 확인한 것들(tools/fundamentals_probe.py, 2026-09-17):

  최근 6년 분기가 21개씩 잡힌다 — 5년 20분기에 충분하다.
  **은행·보험은 매출·영업이익 태그가 아예 없다**(JPM 은 둘 다 0개). 구조적인
  일이라 억지로 채우지 않고 "해당 없음"으로 둔다. 매출만 은행 전용 태그로 만든다.
  **Adjusted EBITDA 는 XBRL 에 없다.** 4종목 전부 고유 태그 0개 — 비GAAP 이라
  회사가 보도자료에서 각자 정의한다. 그래서 여기서는 영업이익 + 감가상각으로
  **계산**하고 그렇게 라벨링한다. "Adjusted" 가 아니다.
  D&A 는 분기 태그가 6~10개뿐이다 — 현금흐름표에 **누적(YTD)** 으로 실리기
  때문이다. 누적을 차분해 분기값을 만든다.

정정공시를 어떻게 다루는지가 중요하다. 같은 분기가 여러 번 제출되는데(10-K/A,
재작성), 쓰임이 갈린다.

  실적 표    → 지금 가장 정확한 값이 맞다   → **마지막 제출본**
  과거 PER   → 그때 시장이 알던 값이 맞다   → **첫 제출본**

그래서 분기마다 둘 다 들고 있는다. 마지막 것만 쓰면 과거 차트에 미래 정보가
새어 든다(프로브에서 제출 지연이 34~398일로 나온 게 이 탓이다 — 398일짜리는
1년 뒤의 정정본이었다).
"""

from __future__ import annotations

from datetime import date

# --- 개념 매핑 --------------------------------------------------------------
# 회사마다 쓰는 태그가 다르다. 앞에서부터 찾아 가장 많이 잡히는 것을 쓴다.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
# 은행·보험은 위 태그를 안 쓴다. 이자수익 + 비이자수익으로 "총수익"을 만든다.
BANK_REVENUE_PARTS = [
    ["InterestAndDividendIncomeOperating", "InterestIncomeExpenseNet"],
    ["NoninterestIncome", "RevenuesNetOfInterestExpense"],
]
OPERATING_TAGS = ["OperatingIncomeLoss"]
NET_INCOME_TAGS = ["NetIncomeLoss", "ProfitLoss"]
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]
DA_TAGS = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
    "DepreciationDepletionAndAmortizationExcludingAmortizationOfDeferredFinancingCosts",
]
SHARES_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding",
               "WeightedAverageNumberOfSharesOutstandingBasic"]

QUARTER_DAYS = (80, 100)      # 3개월 구간
ANNUAL_DAYS = (350, 380)      # 12개월 구간


def _days(f) -> int | None:
    s, e = f.get("start"), f.get("end")
    if not s or not e:
        return None
    try:
        return (date.fromisoformat(e) - date.fromisoformat(s)).days
    except ValueError:
        return None


def _units(facts: dict, tag: str):
    """us-gaap 태그의 모든 단위를 하나로 훑는다(USD, USD/shares, shares…)."""
    node = (facts.get("facts") or {}).get("us-gaap", {}).get(tag) or {}
    for series in (node.get("units") or {}).values():
        for f in series:
            yield f


def collect(facts: dict, tags: list[str], lo: int, hi: int) -> dict[str, dict]:
    """기간 길이가 [lo, hi] 인 사실을 기준일별로 모은다.

    같은 기준일이 여러 번 나오면(정정공시) **첫 제출본과 마지막 제출본을 둘 다**
    남긴다 — 실적 표는 마지막이 맞고 과거 시점 계산은 첫 번째가 맞다.
    """
    out: dict[str, dict] = {}
    for tag in tags:
        for f in _units(facts, tag):
            d = _days(f)
            if d is None or not (lo <= d <= hi):
                continue
            end, filed, val = f.get("end"), f.get("filed") or "", f.get("val")
            if val is None:
                continue
            cur = out.get(end)
            if cur is None:
                out[end] = {"end": end, "start": f.get("start"), "val": val,
                            "first_val": val, "first_filed": filed,
                            "last_filed": filed, "form": f.get("form"), "tag": tag}
                continue
            if filed < cur["first_filed"]:
                cur["first_val"], cur["first_filed"] = val, filed
            if filed >= cur["last_filed"]:
                cur["val"], cur["last_filed"], cur["form"] = val, filed, f.get("form")
        if out:
            break          # 먼저 잡힌 태그를 쓴다(매출 태그는 신→구 순서)
    return out


def _sum_parts(facts: dict, groups: list[list[str]], lo: int, hi: int) -> dict[str, dict]:
    """여러 태그를 더해 한 항목을 만든다(은행 총수익 = 이자 + 비이자)."""
    per_group = [collect(facts, g, lo, hi) for g in groups]
    if not all(per_group):
        return {}
    ends = set(per_group[0])
    for g in per_group[1:]:
        ends &= set(g)
    out = {}
    for end in ends:
        rows = [g[end] for g in per_group]
        out[end] = {
            "end": end, "start": rows[0]["start"],
            "val": sum(r["val"] for r in rows),
            "first_val": sum(r["first_val"] for r in rows),
            "first_filed": max(r["first_filed"] for r in rows),
            "last_filed": max(r["last_filed"] for r in rows),
            "form": rows[0]["form"], "tag": "+".join(r["tag"] for r in rows),
        }
    return out


def derive_q4(quarterly: dict[str, dict], annual: dict[str, dict]) -> dict[str, dict]:
    """10-K 는 분기를 안 싣는다 — Q4 = 연간 − (Q1+Q2+Q3).

    회계연도 안에 들어가는 분기 셋을 날짜로 찾는다. fy/fp 는 **제출물**의 회계
    연도라 사실 자체의 연도와 어긋날 때가 있어 쓰지 않는다.
    """
    out = dict(quarterly)
    for end, a in annual.items():
        if end in out:
            continue
        try:
            a_start = date.fromisoformat(a["start"])
            a_end = date.fromisoformat(end)
        except (ValueError, TypeError):
            continue
        inside = [q for q in quarterly.values()
                  if q.get("start") and a_start <= date.fromisoformat(q["start"])
                  and date.fromisoformat(q["end"]) <= a_end]
        if len(inside) != 3:
            continue
        out[end] = {
            "end": end,
            "start": max(q["end"] for q in inside),
            "val": a["val"] - sum(q["val"] for q in inside),
            "first_val": a["first_val"] - sum(q["first_val"] for q in inside),
            "first_filed": a["first_filed"], "last_filed": a["last_filed"],
            "form": a.get("form"), "tag": a.get("tag"), "derived": "연간−3분기",
        }
    return out


def quarterly_from_ytd(facts: dict, tags: list[str]) -> dict[str, dict]:
    """누적(YTD) 항목을 차분해 분기값으로 만든다 — 감가상각이 이 꼴이다.

    현금흐름표는 회계연도 시작부터 누적이라 구간이 90·180·270·365일로 늘어난다.
    같은 회계연도 안에서 바로 앞 누적을 빼면 그 분기 값이 된다.
    """
    rows = []
    for tag in tags:
        for f in _units(facts, tag):
            d = _days(f)
            if d is None or d < 80 or d > 380:
                continue
            if f.get("val") is None:
                continue
            rows.append(f)
        if rows:
            break
    if not rows:
        return {}

    # 회계연도 시작(start)별로 묶고, 누적 길이 순으로 차분한다.
    by_start: dict[str, list] = {}
    for f in rows:
        by_start.setdefault(f["start"], []).append(f)

    out: dict[str, dict] = {}
    for start, group in by_start.items():
        group = sorted(group, key=lambda f: f["end"])
        # 같은 (start, end) 가 여러 번이면 마지막 제출본
        dedup = {}
        for f in group:
            e = f["end"]
            if e not in dedup or (f.get("filed") or "") >= (dedup[e].get("filed") or ""):
                dedup[e] = f
        prev_val, prev_end = 0.0, start
        for end in sorted(dedup):
            f = dedup[end]
            val = f["val"] - prev_val
            out[end] = {"end": end, "start": prev_end, "val": val, "first_val": val,
                        "first_filed": f.get("filed") or "", "last_filed": f.get("filed") or "",
                        "form": f.get("form"), "tag": f"{f.get('tag', tags[0])}(YTD 차분)",
                        "derived": "누적 차분"}
            prev_val, prev_end = f["val"], end
    return out


# --- 항목 조립 --------------------------------------------------------------
def _series(rows: dict[str, dict], limit: int) -> list[dict]:
    return [rows[e] for e in sorted(rows)][-limit:]


def build_metrics(facts: dict, quarters: int = 20) -> dict:
    """companyfacts → 항목별 분기 시계열.

    항목마다 **어디서 온 값인지**를 같이 싣는다(``source``). 계산값을 보고값처럼
    보여 주면 안 되기 때문이다 — 특히 EBITDA 는 "Adjusted EBITDA" 가 아니다.
    """
    ann = collect(facts, NET_INCOME_TAGS, *ANNUAL_DAYS)

    def metric(tags, label, annual_tags=None):
        q = collect(facts, tags, *QUARTER_DAYS)
        if q:
            a = collect(facts, annual_tags or tags, *ANNUAL_DAYS)
            q = derive_q4(q, a)
        return q

    revenue = metric(REVENUE_TAGS, "매출")
    rev_source = "보고값"
    if not revenue:
        # 은행·보험: 매출 태그가 없다. 이자 + 비이자로 총수익을 만든다.
        revenue = _sum_parts(facts, BANK_REVENUE_PARTS, *QUARTER_DAYS)
        rev_source = "계산값(이자수익+비이자수익)" if revenue else "없음"

    operating = metric(OPERATING_TAGS, "영업이익")
    net = metric(NET_INCOME_TAGS, "순이익")
    eps = metric(EPS_TAGS, "희석EPS")
    shares = metric(SHARES_TAGS, "가중평균주식수")

    # D&A 는 분기 태그가 드물다 — 누적을 차분해 만든다.
    da = collect(facts, DA_TAGS, *QUARTER_DAYS)
    da_source = "보고값"
    if len(da) < 4:
        ytd = quarterly_from_ytd(facts, DA_TAGS)
        if len(ytd) > len(da):
            da, da_source = ytd, "계산값(누적 차분)"

    # EBITDA = 영업이익 + 감가상각. **Adjusted EBITDA 가 아니다** — 비GAAP 이라
    # XBRL 에 없고(실측 4종목 전부 고유 태그 0개), 회사마다 정의가 다르다.
    ebitda = {}
    for end, op in operating.items():
        d = da.get(end)
        if d is None:
            continue
        ebitda[end] = {"end": end, "start": op["start"],
                       "val": op["val"] + d["val"],
                       "first_val": op["first_val"] + d["first_val"],
                       "first_filed": max(op["first_filed"], d["first_filed"]),
                       "last_filed": max(op["last_filed"], d["last_filed"]),
                       "form": op.get("form"), "tag": "OperatingIncomeLoss + D&A",
                       "derived": "영업이익+감가상각"}

    out = {
        "매출": (revenue, rev_source),
        "영업이익": (operating, "보고값" if operating else "없음(은행·보험은 개념 없음)"),
        "순이익": (net, "보고값"),
        "EBITDA": (ebitda, f"계산값(영업이익+감가상각, 감가상각은 {da_source})"),
        "희석EPS": (eps, "보고값"),
        "가중평균주식수": (shares, "보고값"),
    }
    metrics = {}
    for label, (rows, source) in out.items():
        series = with_growth(_series(rows, quarters))
        metrics[label] = {
            "source": source,
            "adjusted": False if label == "EBITDA" else None,
            "count": len(series),
            "quarters": series,
        }
    metrics["EBITDA"]["note"] = (
        "Adjusted EBITDA 가 아닙니다. 비GAAP 이라 XBRL 에 없고 회사마다 정의가 "
        "다릅니다(일회성·주식보상 등 무엇을 빼는지). 여기 값은 영업이익에 "
        "감가상각을 더한 순수 계산값입니다.")
    return metrics


def with_growth(series: list[dict]) -> list[dict]:
    """YoY(4분기 전 대비)·QoQ(직전 분기 대비) 성장률을 붙인다.

    분모가 0 이거나 **음수면 성장률을 주지 않는다.** 적자에서 적자로 가는 구간의
    증감률은 부호가 뒤집혀 읽는 사람을 속인다(-10 → -5 를 "+50% 성장"으로).
    """
    out = []
    for i, row in enumerate(series):
        r = dict(row)
        for label, back in (("qoq", 1), ("yoy", 4)):
            r[label] = None
            if i >= back:
                prev = series[i - back].get("val")
                cur = row.get("val")
                if prev is not None and cur is not None and prev > 0:
                    r[label] = round((cur / prev - 1) * 100, 2)
        out.append(r)
    return out
