#!/usr/bin/env python3
"""EPS·EBITDA 를 **어느 기준**으로 모을 수 있나 — 실측.

지금 forward PER 에는 **기준이 섞여 있다.** 확정 구간은 EDGAR 의 GAAP 희석
EPS 이고, 추정 구간은 야후 컨센인데 애널리스트는 보통 **조정(non-GAAP) EPS**
를 추정한다. 주식보상이 큰 회사는 조정 EPS 가 GAAP 보다 훨씬 커서, 그 경계에서
PER 선이 인위적으로 꺾인다. 재 봐야 할 것:

  1. 과거 **조정 EPS** 를 무료로 받을 수 있나
     야후 get_earnings_dates 의 'Reported EPS' 가 컨센과 **같은 기준**으로
     발표된 실적이다. 몇 분기나 주는지가 관건.
  2. **정규화(normalized)** 손익 항목이 있나
     income_stmt 에 Normalized Income / Normalized EBITDA 행이 있나.
  3. EV/EBITDA 를 과거 시점까지 그릴 수 있나
     EV = 시총 + 순부채. 분기별 부채·현금이 나오나. EBITDA 는 몇 분기나.

키가 필요 없다. 측정 전용.
"""

from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

TICKERS = ["AAPL", "NVDA", "MU", "CEG"]
WANT_ROWS = ["Normalized Income", "Normalized EBITDA", "EBITDA", "Net Income",
             "Diluted EPS", "Basic EPS", "Operating Income", "Total Revenue",
             "Reconciled Depreciation", "Total Unusual Items"]
BS_ROWS = ["Total Debt", "Net Debt", "Cash And Cash Equivalents",
           "Cash Cash Equivalents And Short Term Investments",
           "Ordinary Shares Number", "Share Issued"]


def log(m=""):
    print(m, flush=True)


def frame(df, want, label):
    if df is None or getattr(df, "empty", True):
        log(f"   {label:26} —")
        return
    cols = [str(c)[:10] for c in df.columns]
    idx = list(df.index)
    hit = [r for r in want if r in idx]
    log(f"   {label:26} {len(idx)}행 × {len(cols)}기간 {cols}")
    log(f"   {'':26} 찾는 행: {hit or '없음'}")
    for r in hit[:6]:
        vals = [None if v != v else float(v) for v in df.loc[r].tolist()]
        shown = ", ".join("—" if v is None else f"{v:,.0f}" for v in vals[:6])
        log(f"   {'':26}   {r:28} {shown}")


def main():
    import yfinance as yf

    for t in [a for a in sys.argv[1:] if not a.startswith("-")] or TICKERS:
        log(f"\n■ {t}")
        tk = yf.Ticker(t)

        # 1) 컨센과 같은 기준으로 발표된 과거 실적
        try:
            ed = tk.get_earnings_dates(limit=40)
            if ed is not None and not ed.empty:
                rep = ed["Reported EPS"].dropna() if "Reported EPS" in ed else []
                est = ed["EPS Estimate"].dropna() if "EPS Estimate" in ed else []
                log(f"   {'earnings_dates':26} 발표된 조정 EPS {len(rep)}분기 "
                    f"· 추정 {len(est)}개")
                if len(rep):
                    d = [str(i)[:10] for i in rep.index[:3]]
                    log(f"   {'':26} 최근 {list(zip(d, [round(float(x), 2) for x in rep[:3]]))}")
                    log(f"   {'':26} 가장 오래된 것 {str(rep.index[-1])[:10]}")
        except Exception as e:  # noqa: BLE001
            log(f"   earnings_dates ✕ {type(e).__name__}")

        # 2) 정규화 손익
        for name, getter in [("quarterly_income_stmt", "quarterly_income_stmt"),
                             ("income_stmt(연간)", "income_stmt")]:
            try:
                frame(getattr(tk, getter), WANT_ROWS, name)
            except Exception as e:  # noqa: BLE001
                log(f"   {name:26} ✕ {type(e).__name__}")

        # 3) EV 재료
        try:
            frame(tk.quarterly_balance_sheet, BS_ROWS, "quarterly_balance_sheet")
        except Exception as e:  # noqa: BLE001
            log(f"   quarterly_balance_sheet   ✕ {type(e).__name__}")
        try:
            info = tk.info or {}
            keys = ["enterpriseValue", "enterpriseToEbitda", "enterpriseToRevenue",
                    "ebitda", "totalDebt", "totalCash", "marketCap",
                    "trailingEps", "forwardEps"]
            log("   " + "info".ljust(26) + ", ".join(
                f"{k}={info.get(k)}" for k in keys))
        except Exception as e:  # noqa: BLE001
            log(f"   info ✕ {type(e).__name__}")


if __name__ == "__main__":
    main()
