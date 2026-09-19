"""DART 정기보고서 → 분기 시계열. **네트워크를 모른다.**

미장(app/fundamentals.py)과 하는 일이 같고, 걸리는 함정만 다르다. 수집은
app/krdart.py 가 한다.

실측(tools/kr_fundamentals_probe.py, 2026-09-19)으로 확인한 것:

  **손익 계정의 ``thstrm_amount`` 는 당기 3개월이다.** 누적이 아니다.
  에코프로비엠 2022 반기: 당기 1,187,144,379,130 · 누적 1,849,606,294,291 이고
  누적 = 1분기(662,461,915,161) + 당기 로 딱 맞는다. 미장에서 D&A 를 누적
  차분해야 했던 것과 달리 손익은 바로 쓰면 된다.
  **사업보고서는 당기가 연간이고 누적이 없다.** 그래서 미장과 똑같이
  Q4 = 연간 − 3분기 누적 으로 역산한다. 3분기 누적은 3분기보고서의
  ``thstrm_add_amount`` 에 있다.
  **현금흐름표(CF)는 누적이다.** 감가상각이 거기 있으므로 차분해야 한다.
  미장과 같은 함정이 여기서만 남는다.
  **재무상태표(BS)는 시점값**이라 기간이 없다.
  주당이익은 ``ifrs-full_BasicEarningsLossPerShare`` /
  ``…DilutedEarningsLossPerShare`` 로 **표준 계정코드**가 온다. 미장처럼 회사가
  태그를 갈아타지 않아 오히려 깔끔하다.
  **감가상각은 회사마다 있고 없다**(에코프로비엠은 없다). 미장과 같은 한계다.

한국은 금액 단위가 원이다. 화면에는 억원으로 줄여 보여 주지만 여기서는 원을
그대로 들고 있는다 — 단위 변환은 보여 줄 때 한 번만 한다.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# --- 계정 매핑 --------------------------------------------------------------
# DART 는 표준 계정코드(account_id)를 준다. 없을 때만 이름으로 찾는다.
REVENUE = (["ifrs-full_Revenue", "ifrs-full_RevenueFromSaleOfGoods",
            "dart_OperatingIncomeLoss"],
           ["매출액", "영업수익", "수익(매출액)"])
OPERATING = (["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
             ["영업이익", "영업이익(손실)"])
NET_INCOME = (["ifrs-full_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익"])
OWNER_NET = (["ifrs-full_ProfitLossAttributableToOwnersOfParent"],
             ["지배기업의 소유주에게 귀속되는 당기순이익", "지배주주순이익"])
EPS = (["ifrs-full_DilutedEarningsLossPerShare", "ifrs-full_BasicEarningsLossPerShare"],
       ["희석주당이익", "희석주당순이익", "기본주당이익", "기본주당순이익"])
DA = (["ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense",
       "ifrs-full_DepreciationAndAmortisationExpense"],
      ["감가상각비 및 상각비", "감가상각비와 상각비", "감가상각비"])

QUARTER_OF = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
STALE_DAYS = 250          # 국장은 분기보고서 마감이 45일이라 미장보다 넉넉하게


def _num(x):
    """DART 는 금액을 문자열로 준다 — 쉼표와 괄호 음수를 푼다."""
    if x is None:
        return None
    s = str(x).strip().replace(",", "").replace(" ", "")
    if not s or s in ("-", "—"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


_DT = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")


def period_end(rows: list[dict], year: int, reprt: str) -> str | None:
    """이 보고서가 덮는 기간의 **마지막 날**.

    ``thstrm_dt`` 가 "2025.07.01 ~ 2025.09.30" 처럼 온다. 거기서 마지막 날짜를
    쓴다 — 결산월이 12월이 아닌 회사(3월 결산 등)도 맞기 때문이다. 없으면
    (회계연도, 보고서)에서 12월 결산으로 가정해 만든다.
    """
    for r in rows:
        m = _DT.findall(str(r.get("thstrm_dt") or ""))
        if m:
            y, mo, d = m[-1]
            try:
                return date(int(y), int(mo), int(d)).isoformat()
            except ValueError:
                continue
    q = QUARTER_OF.get(reprt)
    if not q:
        return None
    # 12월 결산 가정: 3·6·9·12월 말일
    mo = q * 3
    nxt = date(year + (mo == 12), mo % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def _pick(rows: list[dict], ids: list[str], names: list[str],
          sj: tuple[str, ...]) -> dict | None:
    """한 보고서에서 한 계정을 찾는다 — 표준 계정코드 먼저, 이름은 대비책.

    같은 이름이 여러 재무제표에 나온다(비지배지분은 BS·CIS·CF 에 다 있다).
    그래서 어느 재무제표(``sj_div``)에서 찾을지를 반드시 좁힌다.
    """
    pool = [r for r in rows if (r.get("sj_div") or "") in sj]
    for aid in ids:
        for r in pool:
            if (r.get("account_id") or "").strip() == aid:
                return r
    for nm in names:
        for r in pool:
            if (r.get("account_nm") or "").strip() == nm:
                return r
    # 이름이 조금씩 다른 회사가 있다 — 마지막으로 포함 검색.
    for nm in names:
        for r in pool:
            if nm in (r.get("account_nm") or ""):
                return r
    return None


def income_series(reports: dict, spec: tuple[list[str], list[str]]) -> dict[str, dict]:
    """손익 계정 하나의 분기 계열. Q4 는 연간에서 역산한다.

    1~3분기는 ``thstrm_amount`` 가 그대로 그 분기 3개월이다. 사업보고서는
    그게 연간이므로 같은 해 3분기보고서의 누적(9개월)을 빼서 Q4 를 만든다.
    """
    ids, names = spec
    out: dict[str, dict] = {}
    ytd3: dict[int, float] = {}          # 회계연도 → 3분기까지 누적
    annual: dict[int, tuple[float, str]] = {}

    for (year, reprt), rows in sorted(reports.items()):
        row = _pick(rows, ids, names, ("IS", "CIS"))
        if row is None:
            continue
        end = period_end(rows, year, reprt)
        if end is None:
            continue
        cur = _num(row.get("thstrm_amount"))
        add = _num(row.get("thstrm_add_amount"))
        if reprt == "11011":
            if cur is not None:
                annual[year] = (cur, end)
            continue
        if cur is not None:
            out[end] = {"end": end, "val": cur, "year": year,
                        "quarter": QUARTER_OF[reprt], "source": "보고값",
                        "account": row.get("account_nm"), "fs": row.get("_fs")}
        if reprt == "11014" and add is not None:
            ytd3[year] = add

    for year, (total, end) in annual.items():
        if end in out:
            continue
        nine = ytd3.get(year)
        if nine is None:
            continue
        out[end] = {"end": end, "val": total - nine, "year": year, "quarter": 4,
                    "source": "계산값(연간−3분기 누적)", "derived": "연간−3분기 누적"}
    return out


def cash_flow_series(reports: dict, spec: tuple[list[str], list[str]]) -> dict[str, dict]:
    """현금흐름표 계정의 분기 계열 — **누적을 차분한다.**

    CF 는 회계연도 시작부터 누적이라 구간이 3·6·9·12개월로 늘어난다. 같은 해
    안에서 바로 앞 누적을 빼면 그 분기 값이 된다. 미장에서 감가상각에 쓰던 것과
    같은 규칙이고, 국장에서는 CF 전체가 이 꼴이다.
    """
    ids, names = spec
    by_year: dict[int, list[tuple[int, str, float]]] = {}
    for (year, reprt), rows in sorted(reports.items()):
        row = _pick(rows, ids, names, ("CF",))
        if row is None:
            continue
        v = _num(row.get("thstrm_amount"))
        end = period_end(rows, year, reprt)
        if v is None or end is None:
            continue
        by_year.setdefault(year, []).append((QUARTER_OF[reprt], end, v))

    out: dict[str, dict] = {}
    for year, rows in by_year.items():
        prev = 0.0
        for q, end, v in sorted(rows):
            out[end] = {"end": end, "val": v - prev, "year": year, "quarter": q,
                        "source": "계산값(누적 차분)", "derived": "누적 차분"}
            prev = v
    return out


def balance_series(reports: dict, ids: list[str], names: list[str]) -> dict[str, float]:
    """재무상태표 계정의 **시점** 계열."""
    out: dict[str, float] = {}
    for (year, reprt), rows in sorted(reports.items()):
        row = _pick(rows, ids, names, ("BS",))
        if row is None:
            continue
        v = _num(row.get("thstrm_amount"))
        end = period_end(rows, year, reprt)
        if v is not None and end:
            out[end] = v
    return out


def _series(rows: dict[str, dict], limit: int) -> list[dict]:
    return [rows[e] for e in sorted(rows)][-limit:]


def build_metrics(reports: dict, quarters: int = 20) -> dict:
    """정기보고서들 → 항목별 분기 시계열.

    미장과 같은 모양으로 낸다(같은 화면이 그린다). 항목마다 어디서 온 값인지
    ``source`` 에 적는다 — 계산값을 보고값처럼 보여 주면 안 된다.
    """
    from .fundamentals import with_growth

    revenue = income_series(reports, REVENUE)
    operating = income_series(reports, OPERATING)
    net = income_series(reports, NET_INCOME)
    owner = income_series(reports, OWNER_NET)
    eps = income_series(reports, EPS)
    da = cash_flow_series(reports, DA)

    ebitda = {}
    for end, op in operating.items():
        d = da.get(end)
        if d is None:
            continue
        ebitda[end] = {"end": end, "val": op["val"] + d["val"], "year": op["year"],
                       "quarter": op["quarter"],
                       "source": "계산값(영업이익+감가상각)",
                       "derived": "영업이익+감가상각"}

    plan = {
        "매출": (revenue, "보고값(DART 연결)"),
        "영업이익": (operating, "보고값(DART 연결)"),
        "당기순이익": (net, "보고값(DART 연결)"),
        "지배주주순이익": (owner, "보고값(DART 연결)"),
        "EBITDA": (ebitda, "계산값(영업이익+감가상각, 감가상각은 현금흐름표 누적 차분)"),
        "희석EPS": (eps, "보고값(DART 연결)"),
    }
    metrics = {}
    for label, (rows, source) in plan.items():
        series = with_growth(_series(rows, quarters))
        metrics[label] = {"source": source, "count": len(series),
                          "adjusted": False if label == "EBITDA" else None,
                          "quarters": series}
    latest = max((m["quarters"][-1]["end"] for m in metrics.values() if m["quarters"]),
                 default=None)
    for m in metrics.values():
        m["latest"] = m["quarters"][-1]["end"] if m["quarters"] else None
        m["stale_days"] = None
        if latest and m["latest"]:
            m["stale_days"] = (date.fromisoformat(latest)
                               - date.fromisoformat(m["latest"])).days
            if m["stale_days"] > STALE_DAYS:
                m["warning"] = (f"최신 분기가 {m['latest']} 에서 끊겼습니다"
                                f"(다른 항목은 {latest}).")
    metrics["EBITDA"]["note"] = (
        "Adjusted EBITDA 가 아닙니다. 영업이익에 현금흐름표의 감가상각비를 더한 "
        "순수 계산값입니다. 감가상각을 현금흐름표에 따로 싣지 않는 회사는 "
        "EBITDA 가 비어 있습니다.")
    return metrics
