"""증권사 컨센서스와 실적발표일 — 야후(yfinance)에서.

실측(tools/consensus_probe.py, 2026-09-17, 8종목)으로 확인한 것:

  earnings_estimate   4행 — 0q·+1q(분기 EPS), 0y·+1y(연간 EPS), 애널리스트 수까지.
                      **8/8 종목 전부** 나온다.
  revenue_estimate    같은 모양의 매출 컨센. 8/8.
  get_earnings_dates  과거 **실제 발표일** 12~50개 + 다가올 발표 예정일 1개.
                      12M forward PER 을 발표일 기준으로 밟으려면 이게 핵심이다.
  info                sharesOutstanding, marketCap, forwardEps.

중요한 한계: 분기 컨센은 **0q·+1q 둘뿐이다.** 12개월이면 네 분기가 필요하니
나머지 둘은 연간 추정에서 이미 아는 분기를 빼고 남은 분기에 나눠 만든다
(``forwardper.fill_estimates``). 그리고 여기서 받는 건 전부 **오늘자** 컨센이다.
과거 시점의 그 당시 컨센은 무료로 구할 수 없다 — 다행히 필요하지도 않다.
"""

from __future__ import annotations

import math
import os

from . import cache

CONSENSUS_TTL = float(os.environ.get("SUH_DH_CONSENSUS_TTL", "3600"))
# 0q/+1q/0y/+1y 는 yfinance 가 쓰는 행 이름 그대로다.
EPS_ROWS = ("0q", "+1q", "0y", "+1y")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _rows(df, field="avg") -> dict:
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for key in EPS_ROWS:
        if key not in df.index:
            continue
        try:
            row = df.loc[key]
        except Exception:  # noqa: BLE001
            continue
        v = _num(row.get(field))
        if v is None:
            continue
        out[key] = {"avg": v, "analysts": _num(row.get("numberOfAnalysts")),
                    "low": _num(row.get("low")), "high": _num(row.get("high"))}
    return out


def _day(idx) -> str:
    """pandas Timestamp(타임존 포함) → "YYYY-MM-DD".

    ``Timestamp.date`` 는 **메서드**다. 불러서 date 를 받은 다음 isoformat 해야
    한다. date 객체를 그대로 자르려 들면 TypeError 가 나고, 그 예외가 컨센
    전체를 날린다(실측: 6종목 모두 "컨센을 받지 못했습니다(TypeError)").
    """
    d = getattr(idx, "date", None)
    if callable(d):
        try:
            return d().isoformat()
        except Exception:  # noqa: BLE001
            pass
    return str(idx)[:10]


def _announcements(tk) -> list[dict]:
    """과거 실적발표일 + 다가올 예정일.

    ``Reported EPS`` 가 있으면 이미 발표된 분기, 없고 추정만 있으면 예정이다.
    """
    try:
        df = tk.get_earnings_dates(limit=40)
    except Exception:  # noqa: BLE001
        return []
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for idx, row in df.iterrows():
        out.append({
            "date": _day(idx),
            "eps_estimate": _num(row.get("EPS Estimate")),
            "reported_eps": _num(row.get("Reported EPS")),
        })
    return sorted(out, key=lambda r: r["date"])


def fetch(ticker: str) -> dict:
    """한 종목의 컨센·발표일·주식수. 실패해도 예외를 던지지 않는다.

    컨센이 없어도 확정 실적 구간(차트의 대부분)은 그릴 수 있어야 한다.
    그래서 조각마다 따로 막아 둔다 — 하나가 비어도 나머지는 산다.
    """
    def produce():
        import yfinance as yf

        tk = yf.Ticker(ticker)
        out = {"ticker": ticker.upper(), "eps": {}, "revenue": {},
               "announcements": [], "shares": None, "price": None,
               "sources": []}
        try:
            out["eps"] = _rows(tk.earnings_estimate)
            if out["eps"]:
                out["sources"].append("야후 earnings_estimate")
        except Exception:  # noqa: BLE001
            pass
        try:
            out["revenue"] = _rows(tk.revenue_estimate)
        except Exception:  # noqa: BLE001
            pass
        out["announcements"] = _announcements(tk)
        if out["announcements"]:
            out["sources"].append("야후 get_earnings_dates")
        try:
            info = tk.info or {}
            out["shares"] = _num(info.get("sharesOutstanding"))
            out["price"] = _num(info.get("currentPrice"))
            out["market_cap"] = _num(info.get("marketCap"))
        except Exception:  # noqa: BLE001
            pass
        return out

    return cache.get_or_set(f"consensus:{ticker.upper()}", CONSENSUS_TTL, produce,
                            cache_when=lambda v: bool(v.get("eps") or v.get("announcements")))


def eps_estimates(con: dict) -> dict:
    """``forwardper.fill_estimates`` 가 먹는 모양으로 줄인다."""
    return {k: v["avg"] for k, v in (con.get("eps") or {}).items()}


# --- 컨센 표 ----------------------------------------------------------------
# 실측(tools/consensus_probe.py, 2026-09-17, NVDA·AAPL·MU·JPM):
#
#   매출     야후 · Alpha Vantage 모두 **분기 2개 + 연간 2개**
#   EPS      야후 · Alpha Vantage 모두 **분기 2개 + 연간 2개**
#   영업이익  **어느 쪽에도 없다**
#   순이익    **어느 쪽에도 없다** (EPS × 주식수로 만들면 그건 계산값이다)
#   내후년    **어느 쪽에도 없다**
#
# Alpha Vantage 를 굳이 안 쓴다. 기간이 야후와 똑같고(분기 2·연간 2), 야후도
# 애널리스트 수와 고·저를 같이 주기 때문이다. AV 만의 이점은 추정치 변화 추이
# (7·30·60·90일 전)인데 API 키가 있어야 하고, 키는 배포 환경마다 따로 넣어야
# 한다. 키 없이 도는 쪽을 기본으로 둔다.
#
# 영업이익까지 채우려면 FMP 의 analyst-estimates(estimatedEbit·estimatedNetIncome)
# 가 필요하다. 그건 키가 있어야 열어 볼 수 있다.
Q_KEYS = ("0q", "+1q")
Y_KEYS = ("0y", "+1y")
YEAR_SLOTS = 3          # 올해·내년·내후년 — 칸은 늘 세 개, 없으면 없다고 쓴다


def _cell(row: dict | None, source: str) -> dict | None:
    if not row or row.get("avg") is None:
        return None
    return {"val": row["avg"], "low": row.get("low"), "high": row.get("high"),
            "analysts": row.get("analysts"), "source": source}


def forecast(con: dict, kind: str, q_ends: list[str], y_ends: list[str],
             scale: float = 1.0) -> dict:
    """컨센을 기간에 붙여 표로 만든다.

    ``kind`` 는 ``"revenue"`` 또는 ``"eps"``. 기간 끝날짜(``q_ends``·``y_ends``)는
    EDGAR 쪽에서 넘겨받는다 — 야후는 0q/+1q/0y/+1y 라는 **상대 이름**만 주고
    실제 날짜를 주지 않기 때문이다.

    ``scale`` 은 EPS 컨센을 금액으로 바꿀 때 쓴다(주식수를 곱한다). 그렇게 만든
    값은 보고된 컨센이 아니라 **계산값**이라 source 에 그대로 적는다.
    """
    src = (con or {}).get("revenue" if kind == "revenue" else "eps") or {}
    label = "야후 컨센" + ("(매출)" if kind == "revenue" else "(EPS)")
    if scale != 1.0:
        label += f" × 주식수 {scale:,.0f}"

    def take(key, end):
        c = _cell(src.get(key), label)
        if c and scale != 1.0:
            for f in ("val", "low", "high"):
                if c.get(f) is not None:
                    c[f] = c[f] * scale
        return {"end": end, **(c or {"val": None})}

    quarters = [take(k, e) for k, e in zip(Q_KEYS, q_ends)]
    years = []
    for i in range(YEAR_SLOTS):
        end = y_ends[i] if i < len(y_ends) else None
        key = Y_KEYS[i] if i < len(Y_KEYS) else None
        years.append(take(key, end) if key else {"end": end, "val": None})
    return {"quarters": [q for q in quarters if q.get("val") is not None],
            "years": years,
            "source": label if any(q.get("val") is not None for q in quarters + years) else "없음"}


def empty_forecast(reason: str) -> dict:
    """컨센을 어디서도 못 구하는 항목 — 칸은 만들되 없다고 쓴다."""
    return {"quarters": [], "years": [{"end": None, "val": None}] * YEAR_SLOTS,
            "source": "없음", "reason": reason}
