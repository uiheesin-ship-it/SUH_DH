#!/usr/bin/env python3
"""컨센서스를 공짜로 얼마나 받을 수 있나 — 실측.

12M forward PER 에서 컨센이 필요한 구간은 생각보다 **좁다**. 정의를 그대로
따라가 보면 알 수 있다: 과거 시점 T 의 forward PER 은 "T 시점 시총 ÷ T 이후
4개 분기 이익"인데, T 가 1년보다 예전이면 그 4개 분기는 **이미 다 발표됐다.**
그러니 컨센이 필요한 건 마지막 1년 남짓, 즉 **오늘 기준 향후 4개 분기**뿐이다.
과거 시점의 그 당시 컨센(point-in-time)은 필요 없다 — 무료로는 구할 수도 없다.

그래서 이 프로브가 확인할 것은 하나다: **오늘 기준 향후 4개 분기 EPS 컨센을
무료로 몇 개나 받을 수 있나.** 야후(yfinance)가 내주는 네 갈래를 다 열어 본다.

  earnings_estimate     0q/+1q/0y/+1y — 분기 2개 + 연간 2개
  get_earnings_dates()  발표 예정일마다 EPS Estimate — 분기별로 더 멀리 갈 수도
  calendar              다음 발표일 + EPS 추정
  info                  forwardEps / forwardPE / sharesOutstanding

분기 컨센이 4개까지 안 나오면 연간(0y/+1y)을 섞어 만들어야 한다 —
blended forward EPS = w×FY0 + (1−w)×FY1. 그게 되는지도 같이 본다.
"""

from __future__ import annotations

import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")

TICKERS = ["AAPL", "MU", "JPM", "APPS", "CEG", "PLD", "ARM", "SMCI"]


def log(m=""):
    print(m, flush=True)


def show_frame(name, df):
    if df is None or getattr(df, "empty", True):
        log(f"    {name:22} —")
        return 0
    try:
        rows = [f"{i}={df.loc[i].to_dict()}" for i in df.index]
    except Exception:  # noqa: BLE001
        rows = [str(df)]
    log(f"    {name:22} {len(df)}행")
    for r in rows[:8]:
        log(f"      {r}")
    return len(df)


def main():
    import yfinance as yf

    tickers = [a for a in sys.argv[1:] if not a.startswith("-")] or TICKERS
    tally = {}
    for t in tickers:
        log(f"\n■ {t}")
        tk = yf.Ticker(t)

        # 1) 분기·연간 EPS 컨센
        try:
            ee = tk.earnings_estimate
        except Exception as e:  # noqa: BLE001
            ee, _ = None, log(f"    earnings_estimate 실패: {type(e).__name__}")
        n_ee = show_frame("earnings_estimate", ee)

        try:
            re_ = tk.revenue_estimate
        except Exception:  # noqa: BLE001
            re_ = None
        show_frame("revenue_estimate", re_)

        # 2) 발표 예정일별 EPS 추정 — 분기 컨센을 더 멀리 볼 수 있나
        fut = past = 0
        try:
            ed = tk.get_earnings_dates(limit=32)
            if ed is not None and not ed.empty:
                cols = list(ed.columns)
                est = "EPS Estimate" if "EPS Estimate" in cols else None
                rep = "Reported EPS" if "Reported EPS" in cols else None
                for idx, row in ed.iterrows():
                    has_est = est and row[est] == row[est]
                    has_rep = rep and row[rep] == row[rep]
                    if has_est and not has_rep:
                        fut += 1
                    elif has_rep:
                        past += 1
                log(f"    earnings_dates         {len(ed)}행 · 미발표+추정있음 {fut} · 발표완료 {past}")
                log(f"      컬럼 {cols}")
                for idx, row in list(ed.iterrows())[:6]:
                    log(f"      {idx.date() if hasattr(idx, 'date') else idx}  {row.to_dict()}")
        except Exception as e:  # noqa: BLE001
            log(f"    earnings_dates 실패: {type(e).__name__}: {e}")

        # 3) 달력
        try:
            cal = tk.calendar
            log(f"    calendar               {cal}")
        except Exception as e:  # noqa: BLE001
            log(f"    calendar 실패: {type(e).__name__}")

        # 4) info 의 단건 숫자들
        try:
            info = tk.info or {}
            keys = ["forwardEps", "trailingEps", "forwardPE", "trailingPE",
                    "sharesOutstanding", "marketCap", "currentPrice"]
            log("    info                   " + ", ".join(
                f"{k}={info.get(k)}" for k in keys))
        except Exception as e:  # noqa: BLE001
            log(f"    info 실패: {type(e).__name__}")

        tally[t] = {"quarterly_consensus": fut, "estimate_rows": n_ee}

    log("\n── 요약 ──────────────────────────────────────────")
    log(f"{'티커':8} {'미래분기 컨센':>14} {'earnings_estimate 행':>22}")
    for t, v in tally.items():
        log(f"{t:8} {v['quarterly_consensus']:>14} {v['estimate_rows']:>22}")
    need = [t for t, v in tally.items() if v["quarterly_consensus"] < 4]
    log(f"\n분기 컨센이 4개 미만인 종목: {len(need)}/{len(tally)} — {' '.join(need) or '없음'}")
    log("4개 미만이면 연간(0y/+1y)을 가중 혼합해 메워야 한다.")
    log("\n야후가 주는 건 매출과 EPS 뿐이다 — 영업이익·순이익 컨센과 내후년(+2y)은 없다.")

    probe_fmp(tickers)
    probe_alphavantage(tickers)


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# 2차: 영업이익·순이익 컨센을 어디서 받나
#
# 야후는 **매출과 EPS 만** 준다(0q·+1q·0y·+1y). 영업이익 컨센은 아예 없고,
# 순이익도 없다(EPS × 주식수로 만들 수는 있지만 그건 계산값이다). 그리고
# 내후년(+2y)이 없다.
#
# 이 저장소에는 이미 두 곳의 키가 걸려 있다 — 실적 컨콜 수집에 쓰던 것이다.
#   EAI_TRANSCRIPT_API_KEY    Financial Modeling Prep
#   EAI_ALPHAVANTAGE_API_KEY  Alpha Vantage
#
# FMP 의 analyst-estimates 는 estimatedRevenue / estimatedEbit(영업이익) /
# estimatedNetIncome / estimatedEps 를 **연도별·분기별로** 준다. 요금제에 따라
# 막혀 있을 수 있어서 실제로 열리는지 재 본다. 키는 절대 찍지 않는다.
# ---------------------------------------------------------------------------
import os
import urllib.parse
import urllib.request

FMP_FIELDS = ["estimatedRevenueAvg", "estimatedEbitAvg", "estimatedEbitdaAvg",
              "estimatedNetIncomeAvg", "estimatedEpsAvg",
              "numberAnalystEstimatedRevenue", "numberAnalystsEstimatedEps"]


def _json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "SUH_DH-probe"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _hide(e):
    """예외 문구에 쿼리스트링(=키)이 섞여 나오지 않게 한다."""
    return f"{type(e).__name__}: {str(e).split('?')[0][:120]}"


def probe_fmp(tickers):
    key = os.environ.get("EAI_TRANSCRIPT_API_KEY", "").strip()
    log("\n\n══ FMP analyst-estimates ══════════════════════════════")
    if not key:
        log("  키 없음(EAI_TRANSCRIPT_API_KEY) — 건너뜁니다")
        return
    for t in tickers[:4]:
        for label, url in [
            ("v3 annual", f"https://financialmodelingprep.com/api/v3/analyst-estimates/{t}?period=annual&limit=8"),
            ("v3 quarter", f"https://financialmodelingprep.com/api/v3/analyst-estimates/{t}?period=quarter&limit=8"),
            ("stable annual", f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={t}&period=annual&limit=8"),
            ("stable quarter", f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={t}&period=quarter&limit=8"),
        ]:
            try:
                rows = _json(url + "&apikey=" + urllib.parse.quote(key))
            except Exception as e:  # noqa: BLE001
                log(f"  {t:6} {label:15} ✕ {_hide(e)}")
                continue
            if isinstance(rows, dict):
                msg = rows.get("Error Message") or rows.get("message") or str(rows)[:120]
                log(f"  {t:6} {label:15} ✕ {msg[:110]}")
                continue
            if not rows:
                log(f"  {t:6} {label:15} — 빈 응답")
                continue
            dates = sorted(r.get("date", "") for r in rows)
            have = [f for f in FMP_FIELDS if rows[0].get(f) not in (None, 0)]
            log(f"  {t:6} {label:15} {len(rows)}행 · {dates[0]} ~ {dates[-1]}")
            log(f"  {'':6} {'':15} 채워진 필드: {', '.join(have) or '없음'}")
            log(f"  {'':6} {'':15} 예시: " +
                json.dumps({k: rows[-1].get(k) for k in ["date"] + FMP_FIELDS},
                           ensure_ascii=False)[:220])
        time.sleep(1.0)


def probe_alphavantage(tickers):
    key = os.environ.get("EAI_ALPHAVANTAGE_API_KEY", "").strip()
    log("\n\n══ Alpha Vantage EARNINGS_ESTIMATES ═══════════════════")
    if not key:
        log("  키 없음(EAI_ALPHAVANTAGE_API_KEY) — 건너뜁니다")
        return
    for t in tickers[:2]:
        url = ("https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES"
               f"&symbol={t}&apikey={urllib.parse.quote(key)}")
        try:
            d = _json(url)
        except Exception as e:  # noqa: BLE001
            log(f"  {t:6} ✕ {_hide(e)}")
            continue
        if "estimates" not in d:
            log(f"  {t:6} ✕ {json.dumps(d, ensure_ascii=False)[:180]}")
            continue
        rows = d["estimates"]
        log(f"  {t:6} {len(rows)}행 · 키: {sorted(rows[0])[:12]}")
        for r in rows[:4]:
            log(f"  {'':6} {json.dumps(r, ensure_ascii=False)[:200]}")
        time.sleep(15)      # 무료 플랜은 분당 5회
