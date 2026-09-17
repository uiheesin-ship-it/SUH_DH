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
        d = getattr(idx, "date", None)
        out.append({
            "date": (d() if callable(d) else str(idx))[:10] if d else str(idx)[:10],
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
