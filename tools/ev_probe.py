#!/usr/bin/env python3
"""EV 재료가 EDGAR 에 실제로 있나 — 태그별 실측.

EV = 시총 + 총차입금 − 현금성자산 + 비지배지분 + 우선주.
야후의 분기 재무상태표는 **7분기**밖에 안 준다(실측). 5년을 그리려면 EDGAR 를
써야 하는데, 회사마다 쓰는 태그가 다르다. 어느 태그가 실제로 몇 분기나
잡히는지 재고, 그 조합이 야후의 현재 enterpriseValue 와 맞는지 대조한다.

산정 기준(📏 산정 기준 모달과 같아야 한다):
  전환사채·단기사채·CP·리스부채 = 포함
  현금 + 단기투자 = 차감
  비지배지분·우선주 = 가산
  연금부채 = 제외
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# 후보 태그. 앞에서부터 잡히는 것을 쓰되, 몇 개나 잡히는지 다 본다.
GROUPS = {
    "장기차입금(비유동)": ["LongTermDebtNoncurrent", "LongTermDebt",
                       "LongTermDebtAndCapitalLeaseObligations"],
    "장기차입금(유동)": ["LongTermDebtCurrent",
                     "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "단기차입금·CP": ["ShortTermBorrowings", "CommercialPaper",
                   "OtherShortTermBorrowings"],
    "전환사채": ["ConvertibleNotesPayable", "ConvertibleDebtNoncurrent",
              "ConvertibleNotesPayableCurrent"],
    "리스부채(비유동)": ["OperatingLeaseLiabilityNoncurrent",
                    "FinanceLeaseLiabilityNoncurrent"],
    "리스부채(유동)": ["OperatingLeaseLiabilityCurrent",
                  "FinanceLeaseLiabilityCurrent"],
    "현금": ["CashAndCashEquivalentsAtCarryingValue",
           "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "단기투자": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
              "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "비지배지분": ["MinorityInterest", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "우선주": ["PreferredStockValue"],
    "발행주식수": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    "연금부채(제외 확인용)": ["DefinedBenefitPlanFundedStatusOfPlan"],
}


def log(m=""):
    print(m, flush=True)


def instants(facts, tag):
    """재무상태표 항목은 **시점**값이라 start 가 없다(또는 end 와 같다)."""
    node = (facts.get("facts") or {}).get("us-gaap", {}).get(tag) or {}
    out = {}
    for series in (node.get("units") or {}).values():
        for f in series:
            if f.get("start") and f.get("start") != f.get("end"):
                continue
            end, val, filed = f.get("end"), f.get("val"), f.get("filed") or ""
            if end is None or val is None:
                continue
            cur = out.get(end)
            if cur is None or filed >= cur[1]:
                out[end] = (val, filed)
    return {e: v for e, (v, _) in out.items()}


def main():
    from app import secdata

    tickers = [a for a in sys.argv[1:] if not a.startswith("-")] or \
              ["AAPL", "NVDA", "CEG", "PLD"]
    for t in tickers:
        log(f"\n■ {t}")
        try:
            cik, meta, facts = secdata.fetch(t)
        except Exception as e:  # noqa: BLE001
            log(f"   ✕ {type(e).__name__}: {e}")
            continue
        picked = {}
        for label, tags in GROUPS.items():
            found = []
            for tag in tags:
                d = instants(facts, tag)
                if d:
                    found.append((tag, len(d), max(d), d[max(d)]))
            if not found:
                log(f"   {label:20} — 없음")
                continue
            for tag, n, last, v in found:
                log(f"   {label:20} {tag:52} {n:3}분기 · 최근 {last} {v:,.0f}")
            picked[label] = found[0][3]

        # 조합해 본 EV 를 야후의 현재 값과 대조
        debt = sum(picked.get(k, 0) for k in
                   ("장기차입금(비유동)", "장기차입금(유동)", "단기차입금·CP",
                    "리스부채(비유동)", "리스부채(유동)"))
        cash = sum(picked.get(k, 0) for k in ("현금", "단기투자"))
        log(f"   {'→ 차입금 합':20} {debt:,.0f}")
        log(f"   {'→ 현금 합':20} {cash:,.0f}")
        log(f"   {'→ 순부채':20} {debt - cash:,.0f}")
        try:
            import yfinance as yf
            info = yf.Ticker(t).info or {}
            log(f"   {'야후 대조':20} totalDebt={info.get('totalDebt'):,} "
                f"totalCash={info.get('totalCash'):,} "
                f"enterpriseValue={info.get('enterpriseValue'):,}")
        except Exception as e:  # noqa: BLE001
            log(f"   야후 대조 ✕ {type(e).__name__}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
