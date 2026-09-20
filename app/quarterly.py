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


from . import charts, consensus, evebitda, forwardper, fundamentals, secdata

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
    fy_ends = _fy_ends(facts)
    dates, close = _price(ticker)

    # 같은 파이프라인을 **기준마다 한 번씩** 돌린다.
    #
    # GAAP 과 조정(non-GAAP)은 숫자가 다르다 — 주식보상이 큰 회사는 조정 쪽이
    # 훨씬 크다. 지금까지는 확정 구간을 GAAP 으로, 추정 구간을 조정 컨센으로
    # 그려서 그 경계에서 선이 인위적으로 꺾였다. 기준마다 과거·미래를 한 기준
    # 으로 맞춰 따로 그리고, 화면에서 고르게 한다.
    adjusted = _adjusted(quarters, con)
    bases = {}
    for name, qs in (("gaap", quarters), ("adjusted", adjusted)):
        if not qs:
            continue
        bases[name] = _one_basis(name, qs, con, fy_ends, dates, close)

    if not bases:
        out["notes"].append("EPS 계열을 만들지 못해 forward PER 을 그릴 수 없습니다.")
        out["per"] = None
        _attach_forecast(out, con, quarters, fy_ends, adjusted)
        out["ev"] = _ev(facts, con, fy_ends, dates, close)
        return out

    # 기본은 조정 — 컨센과 같은 기준이라 경계에서 선이 안 꺾인다.
    default = "adjusted" if "adjusted" in bases else "gaap"
    out["per"] = bases[default]
    out["per_bases"] = bases
    out["per_basis"] = default
    if "adjusted" not in bases:
        out["notes"].append(
            "조정(non-GAAP) EPS 이력을 못 받아 GAAP 으로만 그립니다 — 추정 구간은 "
            "조정 기준 컨센이라 그 경계에서 선이 꺾일 수 있습니다.")
    _attach_forecast(out, con, quarters, fy_ends, adjusted)
    out["ev"] = _ev(facts, con, fy_ends, dates, close)
    return out


def _ev(facts: dict, con: dict, fy_ends: list[str], dates: list[str],
        close: list[float]) -> dict | None:
    """EV/EBITDA 묶음 — 실패해도 PER 화면을 죽이지 않는다.

    재료가 하나 더 많다(재무상태표). 태그가 회사마다 달라 못 만드는 종목이
    반드시 생기는데, 그때 페이지 전체가 500 이 되면 안 된다. 이유를 담은
    딕셔너리로 돌려주고 화면이 그 이유를 보여 준다.
    """
    if not dates:
        return {"error": "주가를 받지 못해 EV/EBITDA 를 그릴 수 없습니다."}
    try:
        return evebitda.build(facts, con, fy_ends, dates, close)
    except Exception as e:  # noqa: BLE001
        return {"error": f"EV/EBITDA 를 만들지 못했습니다({type(e).__name__}: {e})."}


def _attach_forecast(out: dict, con: dict, quarters: list[dict],
                     fy_ends: list[str], adjusted: list[dict] | None = None) -> None:
    """항목마다 컨센 칸을 붙인다 — 확정 실적 오른쪽에 이어 붙을 것들.

    기간 이름을 야후는 0q/+1q/0y/+1y 라는 **상대 이름**으로만 준다. 실제
    날짜는 EDGAR 쪽에서 만들어 넘긴다: 분기는 마지막 확정 분기 다음 둘,
    연간은 아직 안 끝난 회계연도부터 셋.
    """
    last_end = quarters[-1]["end"] if quarters else None
    q_ends = forwardper.project_ends(last_end, len(consensus.Q_KEYS)) if last_end else []
    first_future = forwardper._d(q_ends[0]) if q_ends else None
    y_ends = [e for e in fy_ends
              if first_future and forwardper._d(e) and forwardper._d(e) >= first_future]
    y_ends = y_ends[:consensus.YEAR_SLOTS]

    shares = None
    qs = out["metrics"].get("가중평균주식수", {}).get("quarters") or []
    if qs and qs[-1].get("val"):
        shares = qs[-1]["val"]

    plans = {
        "매출": lambda: consensus.forecast(con, "revenue", q_ends, y_ends),
        "희석EPS": lambda: consensus.forecast(con, "eps", q_ends, y_ends),
        # 순이익 컨센은 어디에도 없다. EPS 컨센에 주식수를 곱해 **만든다** —
        # 보고된 컨센이 아니므로 source 에 그렇게 적힌다.
        "순이익": (lambda: consensus.forecast(con, "eps", q_ends, y_ends, scale=shares))
                  if shares else
                  (lambda: consensus.empty_forecast("주식수를 못 구해 EPS 컨센을 금액으로 바꿀 수 없습니다")),
        "영업이익": lambda: consensus.empty_forecast(
            "영업이익 컨센을 주는 무료 출처가 없습니다 — 야후·Alpha Vantage 에는 항목 "
            "자체가 없고, FMP 는 유료 플랜에서만 열립니다(무료로는 값이 전부 비어 "
            "옵니다). 실측 2026-09-18."),
        "EBITDA": lambda: consensus.empty_forecast(
            "EBITDA 컨센을 주는 무료 출처가 없습니다"),
        "가중평균주식수": lambda: consensus.empty_forecast("주식수 컨센은 없습니다"),
    }
    for label, make in plans.items():
        if label in out["metrics"]:
            out["metrics"][label]["estimates"] = make()
    _eps_bases(out, con, quarters, adjusted or [], q_ends, y_ends)
    out["forecast_note"] = (
        "컨센은 야후에서 받습니다 — 실측(2026-09-17, 4종목)으로 **매출과 EPS 만**, "
        "**앞으로 두 분기와 두 회계연도**까지 나옵니다. 영업이익 컨센은 무료 출처가 "
        "없고, 순이익은 EPS 컨센에 최근 주식수를 곱해 만든 계산값입니다. "
        "내후년 칸은 자리를 비워 둡니다.")


def _eps_bases(out: dict, con: dict, quarters: list[dict], adjusted: list[dict],
               q_ends: list[str], y_ends: list[str]) -> None:
    """실적 표의 희석EPS 칸도 **기준마다 따로** 만든다.

    차트는 이미 GAAP·조정을 따로 그리는데 표는 한 줄뿐이었다. 그 한 줄이
    **확정은 GAAP, 추정은 조정 컨센**이라 기준이 섞여 있었다 — 차트에서 없앤
    바로 그 문제가 표에 남아 있었던 것이다. 주식보상이 큰 회사는 그 경계에서
    값이 껑충 뛴다.

    그래서 두 벌을 만들어 화면이 고르게 한다. 재료는 차트가 쓰던 것과 **같다**.

      GAAP     EDGAR 희석 EPS. **컨센 칸은 비운다** — 애널리스트는 GAAP 을
               추정하지 않는다. 비우는 대신 이유를 적고 조정 탭을 가리킨다.
      조정      야후 ``Reported EPS``(회사가 보도자료에서 발표하는 값) +
               야후 컨센. 확정과 추정이 **같은 기준**이라 경계가 매끈하다.
    """
    m = out["metrics"].get("희석EPS")
    if m is None:
        return
    gaap_rows = m.get("quarters") or []
    adj_rows = fundamentals.with_growth(
        [{"end": q["end"], "val": q["val"]} for q in adjusted][-TABLE_QUARTERS:])

    bases = {}
    if gaap_rows:
        bases["gaap"] = {
            "label": BASIS_LABEL["gaap"], "source": "보고값(EDGAR 희석 EPS)",
            "quarters": gaap_rows, "count": len(gaap_rows),
            "latest": gaap_rows[-1]["end"],
            "estimates": consensus.empty_forecast(
                "애널리스트는 GAAP EPS 를 추정하지 않습니다 — 컨센은 회사가 "
                "보도자료에서 발표하는 **조정(non-GAAP)** 기준입니다. 여기에 그 "
                "값을 붙이면 확정은 GAAP, 추정은 조정이 되어 기준이 섞입니다. "
                "추정치는 **조정 탭**에서 보세요.")}
    if adj_rows:
        bases["adjusted"] = {
            "label": BASIS_LABEL["adjusted"],
            "source": "야후 발표 EPS(회사 보도자료 기준 · 컨센과 같은 기준)",
            "quarters": adj_rows, "count": len(adj_rows),
            "latest": adj_rows[-1]["end"],
            "estimates": consensus.forecast(con, "eps", q_ends, y_ends)}
    if not bases:
        return

    default = "adjusted" if "adjusted" in bases else "gaap"
    m["bases"] = bases
    m["basis"] = default
    # 기준을 모르는 클라이언트도 **섞이지 않은** 한 벌을 보게 한다.
    for key in ("quarters", "source", "estimates", "count", "latest"):
        m[key] = bases[default][key]
    m["basis_note"] = (
        "GAAP 과 조정(non-GAAP)은 다른 값입니다. 조정 쪽이 컨센과 같은 기준이라 "
        "확정→추정 경계가 매끈하고, GAAP 쪽은 컨센이 없어 추정 칸이 비어 있습니다.")


def _adjusted(quarters: list[dict], con: dict) -> list[dict]:
    """야후가 발표일마다 실어 주는 **조정 EPS** 로 같은 분기 계열을 다시 만든다.

    ``Reported EPS`` 는 회사가 보도자료에서 발표하고 컨센과 대조되는 값이다 —
    즉 **컨센과 같은 기준**이다. 이미 발표일을 쓰려고 받아 오던 데이터인데
    숫자는 버리고 있었다. 실측(2026-09-19)으로 NVDA 는 49분기(2014년~)가 온다.

    발표일이 안 붙은 분기(EDGAR 제출일로 물러선 분기)는 조정값을 모르므로
    버린다 — 없는 값을 GAAP 으로 메우면 그게 다시 기준 섞임이다.
    """
    rep = {a["date"]: a.get("reported_eps") for a in (con.get("announcements") or [])}
    out = []
    for q in quarters:
        v = rep.get(q.get("announced"))
        if v is None:
            continue
        out.append({**q, "val": v, "first_val": v, "basis": "adjusted"})
    return out if len(out) >= 8 else []          # 너무 짧으면 쓸모가 없다


def _editable(quarters: list[dict], est: dict, con: dict,
              fy_ends: list[str]) -> dict:
    """분기 EPS 를 손으로 고칠 때 화면이 검사에 쓸 재료.

    규칙은 하나다 — **한 회계연도 안에서 (확정 분기 합 + 손으로 넣은 값 합)이
    그 해 FY 컨센을 넘으면 안 된다.** 그러려면 화면이 세 가지를 알아야 한다:
    각 추정 분기가 어느 회계연도에 속하는지, 그 해에 이미 확정된 합이 얼마인지,
    그 해 FY 컨센이 얼마인지.
    """
    bounds = sorted(x for x in (forwardper._d(e) for e in fy_ends or []) if x)
    actual = {q["end"]: q["val"] for q in quarters if q.get("val") is not None}
    eps = consensus.eps_estimates(con)
    first_future = forwardper._d(sorted(est)[0]) if est else None

    years = {}
    for i, key in enumerate(("0y", "+1y")):
        fy = forwardper._fy_for(key, bounds, first_future)
        if fy is None:
            continue
        lo = forwardper.add_months(fy, -12)
        booked = sum(v for e, v in actual.items()
                     if lo < forwardper._d(e) <= fy)
        years[fy.isoformat()] = {
            "label": f"FY{fy.year}", "total": eps.get(key),
            "booked": round(booked, 6),
            "quarters": sorted(e for e in est
                               if lo < forwardper._d(e) <= fy),
        }
    return {"years": years,
            "quarters": {e: {"val": v.get("val"), "fy": next(
                (f for f, y in years.items() if e in y["quarters"]), None)}
                for e, v in est.items()}}


BASIS_LABEL = {"gaap": "GAAP (EDGAR 희석 EPS)",
               "adjusted": "조정 non-GAAP (야후 발표 EPS · 컨센과 같은 기준)"}


def _one_basis(name: str, quarters: list[dict], con: dict, fy_ends: list[str],
               dates: list[str], close: list[float]) -> dict:
    """한 기준의 분기 계열 → 창 → PER 계열 → 차트 묶음."""
    known = {q["end"]: q["val"] for q in quarters if q.get("val") is not None}
    future = forwardper.project_ends(quarters[-1]["end"], 8)
    est = forwardper.fill_estimates(future, consensus.eps_estimates(con),
                                    fy_ends, known)
    season = forwardper.seasonal_weights(known, fy_ends)
    windows = forwardper.forward_windows(quarters, est)
    series = forwardper.per_series(dates, close, windows)
    ch = _chart(series, windows, quarters, con, est, season)
    ch["editable"] = _editable(quarters, est, con, fy_ends)
    ch["eps_basis"] = name
    ch["eps_basis_label"] = BASIS_LABEL[name]
    ch["eps_quarters"] = len(quarters)
    return ch


def _eps_rows(facts: dict) -> dict[str, dict]:
    """희석 EPS 분기 계열(Q4 역산 포함)."""
    q = fundamentals.collect(facts, fundamentals.EPS_TAGS, *fundamentals.QUARTER_DAYS)
    if not q:
        return {}
    a = fundamentals.collect(facts, fundamentals.EPS_TAGS, *fundamentals.ANNUAL_DAYS)
    return fundamentals.derive_q4(q, a)


def _chart(series: list[dict], windows: list[dict], quarters: list[dict],
           con: dict, est: dict, season: tuple) -> dict:
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
        # ends 를 같이 싣는다 — 브라우저가 분기 EPS 를 손으로 고쳤을 때
        # **다시 받지 않고** 그 자리에서 PER 을 다시 계산하려면 각 창이 어느
        # 분기들을 덮는지 알아야 한다.
        "marks": [{"announced": w["from"], "to": w["to"],
                   "basis_end": w["basis_end"],
                   "confirmed": w["confirmed"], "eps": w["eps"],
                   "estimated": w["estimated"],
                   "ends": [r["end"] for r in w["quarters"]],
                   "source": w.get("announced_source")} for w in windows],
        # 분기별 EPS(확정 + 추정) — 위 계산의 재료.
        "values": {**{q["end"]: q.get("val") for q in quarters},
                   **{e: v.get("val") for e, v in est.items()}},
        "quarters": [{"end": q["end"], "announced": q.get("announced"),
                      "source": q.get("announced_source"), "eps": q.get("val")}
                     for q in quarters],
        "estimates": [{"end": e, "eps": None if v.get("val") is None else round(v["val"], 4),
                       "source": v["source"], "weight": v.get("weight"),
                       "note": v.get("note")}
                      for e, v in sorted(est.items())],
        "consensus_sources": con.get("sources") or [],
        "shares": con.get("shares"),
        "market_cap": con.get("market_cap"),
        "basis": "실적발표일",
        "season": {"mode": season[1], "weights": {str(k): round(v, 4)
                                                  for k, v in season[0].items()},
                   "why": season[2]},
        "note": (
            "계단은 실적발표일에 밟습니다. 기준일(분기말)에 밟으면 아직 공개되지 "
            "않은 실적으로 그 사이 주가를 나누게 되기 때문입니다. 기준일은 같이 "
            "표시만 합니다. 과거 구간은 '그때 시장이 기대하던 PER' 이 아니라 "
            "'지나고 보니 그때 주가가 실제 향후 4분기 이익의 몇 배였나' 입니다 — "
            "과거 시점의 그 당시 컨센은 무료로 구할 수 없습니다."),
    }
