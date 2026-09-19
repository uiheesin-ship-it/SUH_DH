"""국장 종목 하나의 분기 실적 + 12M forward PER 을 조립한다.

미장(app/quarterly.py)과 **같은 화면**이 그린다. 그래서 내는 모양을 똑같이
맞추고, 다른 것은 재료를 구하는 곳뿐이다.

  DART      분기 실적(매출·영업이익·순이익·EBITDA·EPS)   app/krdart.py
  DART      실적발표일(잠정실적 공시 → 정기보고서 접수)   app/krdart.py
  네이버     컨센(앞으로 한 분기 + 한 회계연도)            app/krconsensus.py
  네이버/KRX 주가                                          app/krdata.py

창을 만들고 PER 을 내는 규칙(app/forwardper.py)은 **한 줄도 안 고치고 그대로
쓴다.** 실적발표일에 계단을 밟는다는 생각, 계절성 배분, 실선/점선의 뜻이 시장과
무관하기 때문이다.

**컨센 지평이 미장보다 좁다.** 실측(2026-09-19, 3종목)으로 네이버는 앞으로
분기 **하나**, 연간 **하나**만 준다. 야후는 분기 2 + 연간 2 였다. 12개월이면 네
분기가 필요한데 올해 남은 분기까지밖에 안 채워지므로, 그다음 회계연도 분기는
**직전 해 같은 분기에 올해 성장률을 곱해** 만든다. 컨센이 아니라 가정이라
화면에 그렇게 적는다.
"""

from __future__ import annotations

from datetime import date

from . import forwardper, krconsensus, krdart, krdata, krfundamentals

TABLE_QUARTERS = 20        # 화면 표에 보여 줄 분기 수(5년)
PER_QUARTERS = 32          # PER 계산용 — 5년 앞을 보려면 더 뒤부터 있어야 한다
PRICE_YEARS = 5
# 국장 주가 기본 조회는 2.2년이다(스크리너가 그만큼만 쓴다). 5년을 그리려면
# 이 페이지에서만 더 길게 달라고 해야 한다.
PRICE_DAYS = 400 + 365 * PRICE_YEARS
# ③단계(직전 해 × 성장률)에서 쓸 수 있는 성장률의 범위.
#
# 실측(삼성전자 2026-09-19): 올해 FY 컨센 ÷ 작년 실적이 **7.25배**로 나왔다.
# 메모리 사이클 정점이라 실제로 그렇다. 그런데 그 배수를 **내년에도 그대로**
# 곱하면 2028년 분기 EPS 가 56만 원이 된다 — 컨센이 한 번도 말한 적 없는 숫자다.
# 한 해의 사이클 정점을 영구 성장률로 바꿔 쓰는 셈이라 쓸 수 없다.
#
# 범위 밖이면 성장률을 **1.0(성장 없음)** 으로 두고 그렇게 적는다. 값을 지어내는
# 것보다 "그 수준이 유지된다고 보았다" 가 방어 가능하고, 그 가정이 틀리면
# forward PER 이 **보수적으로**(높게) 나온다 — 낙관 쪽으로 틀리는 것보다 낫다.
GROWTH_BAND = (0.5, 2.0)


def _price(code: str) -> tuple[list[str], list[float]]:
    try:
        ch = krdata.kr_chart(code, days=PRICE_DAYS)
    except Exception:  # noqa: BLE001
        return [], []
    dates, close = ch.get("dates") or [], ch.get("close") or []
    if not dates:
        return [], []
    cutoff = f"{int(dates[-1][:4]) - PRICE_YEARS}{dates[-1][4:]}"
    keep = [i for i, d in enumerate(dates) if d >= cutoff]
    return [dates[i] for i in keep], [close[i] for i in keep]


def _fy_ends(reports: dict) -> list[str]:
    """회계연도 마지막 기준일 — 사업보고서의 실제 기간 끝에서 받는다.

    대부분 12월 결산이지만 3월·6월 결산도 있다. 보고서가 들고 있는 기간을 그대로
    쓰고, 앞으로 두 해만 12개월씩 더해 만든다.
    """
    ends = []
    for (year, reprt), rows in sorted(reports.items()):
        if reprt != "11011":
            continue
        e = krfundamentals.period_end(rows, year, reprt)
        if e:
            ends.append(e)
    if not ends:
        return []
    last = forwardper._d(ends[-1])
    return ends + [forwardper.add_months(last, 12).isoformat(),
                   forwardper.add_months(last, 24).isoformat()]


def _ym(end: str) -> str:
    """분기 기준일 → 네이버의 기간 키("2026-06-30" → "202606")."""
    return f"{end[:4]}{end[5:7]}"


def estimates(future: list[str], con: dict, fy_ends: list[str],
              known: dict[str, float], label: str = "희석EPS") -> tuple[dict, dict]:
    """미발표 분기를 채운다 — **세 단계**, 뒤로 갈수록 가정이 세진다.

    ① 네이버 분기 컨센이 있는 분기는 그대로 쓴다(앞으로 한 분기).
    ② 올해 FY 컨센이 있으면 잔여를 계절성 비중으로 나눠 그해 남은 분기에 배분한다
       (미장과 같은 규칙, app/forwardper.seasonal_weights).
    ③ 그다음 회계연도 분기는 **직전 해 같은 분기 × 올해 성장률**로 만든다.
           성장률 g = 올해 FY 컨센 ÷ 작년 FY 실적 합
       컨센이 아니라 가정이다. 미장은 연간 컨센을 둘 주니 여기까지 안 갔는데,
       국장은 하나뿐이라 안 그러면 가장 최근 1년이 통째로 빈다.

    셋 다 못 하면 그 분기는 비운다 — 지어내지 않는다.
    """
    qk, qe = krconsensus.series(con, "quarter", label)
    yk, ye = krconsensus.series(con, "annual", label)
    bounds = sorted(x for x in (forwardper._d(e) for e in fy_ends or []) if x)
    out: dict[str, dict] = {}
    why = {"분기 컨센": 0, "연간 컨센 계절성 배분": 0, "직전 해 × 성장률": 0}

    # ① 분기 컨센
    for end in future:
        v = qe.get(_ym(end))
        if v is not None:
            out[end] = {"val": float(v), "source": "네이버 분기 컨센"}
            why["분기 컨센"] += 1

    # ② 올해 FY 컨센의 잔여를 계절성으로
    first = forwardper._d(future[0]) if future else None
    fy = next((b for b in bounds if first and b >= first), None)
    w, mode, season_why = forwardper.seasonal_weights(known, fy_ends)
    if fy is not None:
        total = ye.get(_ym(fy.isoformat()))
        if total is not None:
            lo = forwardper.add_months(fy, -12)
            mine = [e for e in future if lo < forwardper._d(e) <= fy]
            booked = sum(v for e, v in known.items() if lo < forwardper._d(e) <= fy)
            booked += sum(r["val"] for e, r in out.items()
                          if lo < forwardper._d(e) <= fy and r.get("val") is not None)
            rest = [e for e in mine if e not in out]
            residual = float(total) - booked
            if rest and residual > 0:
                share = {e: w.get(forwardper._fq_pos(e, fy.isoformat()) or 0, 0.25)
                         for e in rest}
                denom = sum(share.values()) or 1.0
                for e in rest:
                    out[e] = {"val": residual * share[e] / denom,
                              "source": f"네이버 연간 컨센 {mode} 배분",
                              "weight": round(share[e] / denom, 4), "mode": mode}
                    why["연간 컨센 계절성 배분"] += 1
            elif rest:
                for e in rest:
                    out[e] = {"val": None, "source": "네이버 연간 컨센",
                              "note": "이미 확정된 분기 합이 연간 추정을 넘었습니다"}

    # ③ 그다음 회계연도 — 직전 해 같은 분기 × 올해 성장률
    growth = None
    if fy is not None:
        total = ye.get(_ym(fy.isoformat()))
        prev_fy = forwardper.add_months(fy, -12)
        lo = forwardper.add_months(prev_fy, -12)
        prev_sum = sum(v for e, v in known.items() if lo < forwardper._d(e) <= prev_fy)
        if total is not None and prev_sum > 0:
            growth = float(total) / prev_sum
    raw_growth, capped = growth, False
    if growth is not None and not (GROWTH_BAND[0] <= growth <= GROWTH_BAND[1]):
        growth, capped = 1.0, True
    label = ("성장 없음(올해 성장률 "
             f"{raw_growth:.2f}배는 내년까지 이어 쓰기엔 지나칩니다)") if capped \
        else (f"성장률 {growth:.2f}배" if growth is not None else "")
    for end in future:
        if end in out:
            continue
        back = forwardper.add_months(forwardper._d(end), -12).isoformat()
        base = known.get(back)
        if base is None:
            base = (out.get(back) or {}).get("val")
        if base is None or growth is None:
            continue
        out[end] = {"val": base * growth,
                    "source": f"직전 해 같은 분기 × {label}(가정)",
                    "assumed": True, "capped": capped}
        why["직전 해 × 성장률"] += 1

    return out, {"counts": why, "growth": None if growth is None else round(growth, 4),
                 "raw_growth": None if raw_growth is None else round(raw_growth, 4),
                 "growth_capped": capped, "growth_band": list(GROWTH_BAND),
                 "season_mode": mode, "season_why": season_why,
                 "season_weights": {str(k): round(v, 4) for k, v in w.items()}}


def build(code: str) -> dict:
    """종목코드 → 실적 표 + forward PER 차트."""
    d = krdart.fetch(code)
    reports = d["reports"]
    if not reports:
        raise LookupError(f"{code} 의 DART 정기보고서를 받지 못했습니다.")

    con = {}
    try:
        con = krconsensus.fetch(code)
    except Exception:  # noqa: BLE001
        pass

    metrics = krfundamentals.build_metrics(reports, TABLE_QUARTERS)
    fy_ends = _fy_ends(reports)
    out = {"market": "kr", "ticker": code, "code": code,
           "name": con.get("name"), "corp_code": d["corp_code"],
           "metrics": metrics, "notes": [],
           "currency": "KRW", "unit": "원"}
    # 컨센 칸은 차트가 안 그려져도 붙어야 한다 — 표만 보고 싶은 종목이 있다.
    _attach_forecast(out, con, fy_ends)

    eps = krfundamentals.income_series(reports, krfundamentals.EPS)
    rows = krfundamentals._series(eps, PER_QUARTERS)
    if len(rows) < 8:
        out["notes"].append(
            f"주당이익 분기가 {len(rows)}개뿐이라 forward PER 을 그릴 수 없습니다.")
        out["per"] = None
        return out

    # 잠정실적 공시일이 먼저 온다(krdart.announcements 가 그 순서로 준다).
    # 같은 분기에 둘이 붙으면 이른 쪽이 이긴다 — 시장이 먼저 아는 날이다.
    announced = [a["date"] for a in (d.get("announcements") or [])]
    quarters = forwardper.match_announcements(
        rows, announced, source="잠정실적 공시일(DART)",
        fallback="정기보고서 접수일(DART)")
    dates, close = _price(code)
    if not dates:
        out["notes"].append("주가를 받지 못해 forward PER 을 그릴 수 없습니다.")
        out["per"] = None
        return out

    known = {q["end"]: q["val"] for q in quarters if q.get("val") is not None}
    future = forwardper.project_ends(quarters[-1]["end"], 8)
    est, why = estimates(future, con, fy_ends, known)
    windows = forwardper.forward_windows(quarters, est)
    series = forwardper.per_series(dates, close, windows)
    out["per"] = _chart(series, windows, quarters, con, est, why, d)
    out["per_bases"] = {"reported": out["per"]}
    out["per_basis"] = "reported"
    return out


# 화면 항목 이름 → 네이버 행 이름(krconsensus.ROWS 에서 붙인 이름)
FORECAST_OF = ["매출", "영업이익", "당기순이익", "지배주주순이익", "희석EPS"]


def _attach_forecast(out: dict, con: dict, fy_ends: list[str]) -> None:
    """실적 표 오른쪽에 컨센 칸을 붙인다 — 미장과 같은 모양으로.

    다만 채워지는 칸이 훨씬 적다. 네이버는 앞으로 **분기 하나, 연간 하나**만
    준다(실측 2026-09-19). 칸은 미장과 똑같이 만들되 없는 곳은 비운다.
    **영업이익 컨센이 있다는 게 미장과 다른 점**이다 — 야후·Alpha Vantage 에는
    항목 자체가 없고 FMP 는 유료였는데, 네이버는 그냥 준다.
    """
    from . import consensus

    for label in FORECAST_OF:
        m = out["metrics"].get(label)
        if m is None:
            continue
        _, qe = krconsensus.series(con, "quarter", label)
        _, ye = krconsensus.series(con, "annual", label)
        quarters = [{"end": _end_of(k), "val": v, "source": "네이버 컨센(분기)"}
                    for k, v in sorted(qe.items())]
        years = []
        fy_future = [e for e in fy_ends if e >= (out["metrics"][label].get("latest") or "")]
        for i in range(consensus.YEAR_SLOTS):
            end = fy_future[i] if i < len(fy_future) else None
            v = ye.get(_ym(end)) if end else None
            years.append({"end": end, "val": v,
                          "source": "네이버 컨센(연간)" if v is not None else None})
        m["estimates"] = {
            "quarters": quarters, "years": years,
            "source": "네이버 컨센" if (quarters or any(y["val"] is not None for y in years))
                      else "없음"}
    out["forecast_note"] = (
        "컨센은 네이버에서 받습니다 — 실측(2026-09-19, 3종목)으로 **앞으로 한 "
        "분기와 한 회계연도**만 나옵니다. 미장(야후)은 분기 둘·연간 둘이라 국장이 "
        "더 좁습니다. 대신 **영업이익 컨센이 나옵니다** — 미장에서는 무료로 못 "
        "구하던 항목입니다. 내년·내후년 칸은 자리를 비워 둡니다.")


def _end_of(ym: str) -> str:
    """네이버 기간 키("202609") → 그 달의 마지막 날."""
    y, m = int(ym[:4]), int(ym[4:6])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - __import__("datetime").timedelta(days=1)).isoformat()


def _chart(series, windows, quarters, con, est, why, dart) -> dict:
    dates = [r["date"] for r in series]
    solid, dashed = [], []
    for r in series:
        v, ok = r.get("per"), r.get("confirmed")
        solid.append(v if ok else None)
        dashed.append(v if ok is False else None)
    for i in range(1, len(series)):
        if solid[i] is None and solid[i - 1] is not None and dashed[i] is not None:
            dashed[i - 1] = solid[i - 1]

    flash = sum(1 for q in quarters if q.get("announced_source") == "실적발표일(야후)")
    return {
        "metric": "per",
        "dates": dates,
        "close": [r["close"] for r in series],
        "per_confirmed": solid,
        "per_estimated": dashed,
        "marks": [{"announced": w["from"], "to": w["to"], "basis_end": w["basis_end"],
                   "confirmed": w["confirmed"], "eps": w["eps"],
                   "estimated": w["estimated"],
                   "ends": [r["end"] for r in w["quarters"]],
                   "source": w.get("announced_source")} for w in windows],
        "values": {**{q["end"]: q.get("val") for q in quarters},
                   **{e: v.get("val") for e, v in est.items()}},
        "quarters": [{"end": q["end"], "announced": q.get("announced"),
                      "source": q.get("announced_source"), "eps": q.get("val")}
                     for q in quarters],
        "estimates": [{"end": e, "eps": None if v.get("val") is None else round(v["val"], 1),
                       "source": v["source"], "weight": v.get("weight"),
                       "note": v.get("note")} for e, v in sorted(est.items())],
        "consensus_sources": con.get("sources") or [],
        "eps_basis": "reported",
        "eps_basis_label": "보고값 (DART 연결 희석주당이익)",
        "eps_quarters": len(quarters),
        "basis": "실적발표일(잠정실적 공시)",
        "season": {"mode": why["season_mode"],
                   "weights": why["season_weights"], "why": why["season_why"]},
        "kr_fill": why["counts"],
        "kr_growth": why["growth"],
        "kr_raw_growth": why["raw_growth"],
        "kr_growth_capped": why["growth_capped"],
        "kr_growth_band": why["growth_band"],
        "note": (
            "계단은 **잠정실적 공시일**에 밟습니다 — 정기보고서 접수일보다 2~5주 "
            "빠르고, 시장이 숫자를 아는 날은 그쪽입니다. 없으면 정기보고서 "
            "접수일로 물러섭니다. 네이버 컨센은 앞으로 **한 분기와 한 회계연도**만 "
            "주므로(실측 2026-09-19), 그다음 회계연도 분기는 직전 해 같은 분기에 "
            "올해 성장률을 곱해 만든 **가정치**입니다."),
    }
