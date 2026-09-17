"""티커 하나의 분기 실적 + 12M forward PER 차트를 조립한다.

미리 전 종목을 모으지 않는다 — **입력받은 티커만** 그때 받아 온다.

세 군데서 가져온다.

  EDGAR    분기 실적(매출·영업이익·순이익·EBITDA·EPS·주식수)   app/secdata.py
  야후     컨센(0q·+1q·0y·+1y)과 **실제 실적발표일**           app/consensus.py
  야후     주가                                               app/charts.py

셋 중 하나가 없어도 나머지는 살아야 한다. 컨센이 없으면 점선 구간만 없어지고
확정 구간(차트의 대부분)은 그대로 그려진다.
"""

from __future__ import annotations


from . import charts, consensus, forwardper, fundamentals, secdata

TABLE_QUARTERS = 20        # 화면 표에 보여 줄 분기 수(5년)
PER_QUARTERS = 32          # PER 계산용 — 5년 앞을 보려면 더 뒤부터 있어야 한다
PRICE_YEARS = 5


def _price(ticker: str) -> tuple[list[str], list[float]]:
    try:
        ch = charts.get_chart(ticker, "max")
    except Exception:  # noqa: BLE001
        return [], []
    dates, close = ch.get("dates") or [], ch.get("close") or []
    if not dates:
        return [], []
    cutoff = f"{int(dates[-1][:4]) - PRICE_YEARS}{dates[-1][4:]}"
    keep = [i for i, d in enumerate(dates) if d >= cutoff]
    return [dates[i] for i in keep], [close[i] for i in keep]


def _fy_ends(facts: dict) -> list[str]:
    """회계연도 마지막 기준일 — EDGAR 연간 사실에서 **실제 날짜**로 받는다.

    결산월만 알면 될 것 같지만 아니다. 애플처럼 52/53주 회계연도를 쓰면 매년
    날짜가 달라진다(9월 27일, 9월 28일…). 연간 사실의 end 를 그대로 쓰고,
    앞으로 두 해만 12개월씩 더해 만든다.
    """
    ann = fundamentals.collect(facts, fundamentals.NET_INCOME_TAGS,
                               *fundamentals.ANNUAL_DAYS)
    ends = sorted(ann)
    if not ends:
        return []
    last = forwardper._d(ends[-1])
    return ends + [forwardper.add_months(last, 12).isoformat(),
                   forwardper.add_months(last, 24).isoformat()]


def build(ticker: str) -> dict:
    """티커 → 실적 표 + forward PER 차트."""
    cik, meta, facts = secdata.fetch(ticker)
    metrics = fundamentals.build_metrics(facts, TABLE_QUARTERS)
    out = {"ticker": ticker.upper(), "cik": cik, "name": meta.get("name"),
           "sic": meta.get("sic"), "fiscal_year_end": meta.get("fiscal_year_end"),
           "metrics": metrics, "notes": []}

    eps_rows = fundamentals.with_growth(
        fundamentals._series(_eps_rows(facts), PER_QUARTERS))
    if not eps_rows:
        out["notes"].append("희석EPS 를 찾지 못해 forward PER 을 그릴 수 없습니다.")
        out["per"] = None
        return out

    con = {}
    try:
        con = consensus.fetch(ticker)
    except Exception as e:  # noqa: BLE001
        out["notes"].append(f"컨센을 받지 못했습니다({type(e).__name__}) — 확정 구간만 그립니다.")

    announced = [a["date"] for a in (con.get("announcements") or [])]
    quarters = forwardper.match_announcements(eps_rows, announced)
    known = {q["end"]: q["val"] for q in quarters if q.get("val") is not None}
    future = forwardper.project_ends(quarters[-1]["end"], 8)
    est = forwardper.fill_estimates(future, consensus.eps_estimates(con),
                                    _fy_ends(facts), known)
    windows = forwardper.forward_windows(quarters, est)
    dates, close = _price(ticker)
    series = forwardper.per_series(dates, close, windows)

    if not est:
        out["notes"].append(
            "컨센을 못 받아 추정 구간(점선)이 없습니다. 마지막 확정 분기까지만 그립니다.")
    out["per"] = _chart(series, windows, quarters, con, est)
    return out


def _eps_rows(facts: dict) -> dict[str, dict]:
    """희석 EPS 분기 계열(Q4 역산 포함)."""
    q = fundamentals.collect(facts, fundamentals.EPS_TAGS, *fundamentals.QUARTER_DAYS)
    if not q:
        return {}
    a = fundamentals.collect(facts, fundamentals.EPS_TAGS, *fundamentals.ANNUAL_DAYS)
    return fundamentals.derive_q4(q, a)


def _chart(series: list[dict], windows: list[dict], quarters: list[dict],
           con: dict, est: dict) -> dict:
    """차트가 바로 먹을 수 있는 모양으로.

    실선(확정)과 점선(추정)을 **따로** 낸다. 한 배열에 담고 스타일만 바꾸면
    경계가 어디인지 그림에서 사라진다. 경계 한 점은 양쪽에 다 넣어 선이
    끊기지 않게 한다.
    """
    dates = [r["date"] for r in series]
    solid, dashed = [], []
    for i, r in enumerate(series):
        v, ok = r.get("per"), r.get("confirmed")
        solid.append(v if ok else None)
        dashed.append(v if ok is False else None)
    for i in range(1, len(series)):
        if solid[i] is None and solid[i - 1] is not None and dashed[i] is not None:
            dashed[i - 1] = solid[i - 1]        # 이음매를 잇는다

    return {
        "dates": dates,
        "close": [r["close"] for r in series],
        "per_confirmed": solid,
        "per_estimated": dashed,
        # 차트에 세로선으로 찍을 두 날짜. 요구대로 **둘 다** 낸다.
        "marks": [{"announced": w["from"], "basis_end": w["basis_end"],
                   "confirmed": w["confirmed"], "eps": w["eps"],
                   "estimated": w["estimated"],
                   "source": w.get("announced_source")} for w in windows],
        "quarters": [{"end": q["end"], "announced": q.get("announced"),
                      "source": q.get("announced_source"), "eps": q.get("val")}
                     for q in quarters],
        "estimates": [{"end": e, "eps": round(v["val"], 4), "source": v["source"]}
                      for e, v in sorted(est.items())],
        "consensus_sources": con.get("sources") or [],
        "shares": con.get("shares"),
        "market_cap": con.get("market_cap"),
        "basis": "실적발표일",
        "note": (
            "계단은 실적발표일에 밟습니다. 기준일(분기말)에 밟으면 아직 공개되지 "
            "않은 실적으로 그 사이 주가를 나누게 되기 때문입니다. 기준일은 같이 "
            "표시만 합니다. 과거 구간은 '그때 시장이 기대하던 PER' 이 아니라 "
            "'지나고 보니 그때 주가가 실제 향후 4분기 이익의 몇 배였나' 입니다 — "
            "과거 시점의 그 당시 컨센은 무료로 구할 수 없습니다."),
    }
