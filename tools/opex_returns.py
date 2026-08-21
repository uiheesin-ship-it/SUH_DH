#!/usr/bin/env python3
"""US monthly options-expiration (3rd Friday) return windows for 3 indices.

Fetches daily closes from Stooq (key-free CSV) for Nasdaq-100 (^ndq),
S&P 500 (^spx) and PHLX Semiconductor (^sox), finds the last N monthly
options-expiration dates (3rd Friday, mapped to the nearest trading day), and
for each computes the return on D-1 / D0(당일) / D+1 / D+3 / D+7 — both as that
trading day's single-day return and cumulative from the D0 close.

Run where stooq.com is reachable (GitHub Actions; the sandbox blocks it).

  python tools/opex_returns.py 6
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "opex_returns.json"
# Yahoo Finance index symbols.
SYMBOLS = {"나스닥100": "^NDX", "S&P500": "^GSPC", "필라델피아반도체": "^SOX"}


def _get(url: str, timeout: int = 30, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        for host in ("query1", "query2"):
            try:
                u = url.replace("query1", host)
                req = urllib.request.Request(u, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/124.0 Safari/537.36"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read().decode("utf-8", "ignore")
            except Exception as e:
                last = e
        time.sleep(2 * (i + 1))
    raise last


def fetch_closes(sym: str) -> list[tuple[str, float]]:
    """[(YYYY-MM-DD, close)] ascending, from the Yahoo chart API."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(sym)}?range=2y&interval=1d")
    js = json.loads(_get(url))
    res = js["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    rows: list[tuple[str, float]] = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append((d, float(c)))
    rows.sort()
    return rows


def third_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    first_fri = 1 + (4 - d.weekday()) % 7          # Fri == weekday 4
    return date(y, m, first_fri + 14)


def recent_opex(n_back: int = 12) -> list[date]:
    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(n_back):
        out.append(third_friday(y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return sorted(out)


def pos_for(dates: list[str], target: date) -> int | None:
    """Index of the trading day == target, else nearest earlier within 4 days."""
    t = target.isoformat()
    lo, hi = 0, len(dates) - 1
    # dates ascending; find rightmost <= t
    best = None
    for i, d in enumerate(dates):
        if d <= t:
            best = i
        else:
            break
    if best is None:
        return None
    # only accept if within 4 calendar days of target
    y, mo, da = (int(x) for x in dates[best].split("-"))
    if (target - date(y, mo, da)).days > 4:
        return None
    return best


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    result: dict[str, object] = {"_generated": date.today().isoformat(), "n": n, "indices": {}}
    for label, sym in SYMBOLS.items():
        try:
            rows = fetch_closes(sym)
        except Exception as e:
            result["indices"][label] = {"error": str(e)}
            continue
        dates = [d for d, _ in rows]
        closes = [c for _, c in rows]
        recs = []
        for opex in recent_opex(14):
            p = pos_for(dates, opex)
            if p is None or p + 7 >= len(closes) or p - 1 < 0:
                continue

            def daily(i):
                return round((closes[i] / closes[i - 1] - 1) * 100, 2)

            def cum(i):
                return round((closes[i] / closes[p] - 1) * 100, 2)

            recs.append({
                "opex": dates[p],
                "d_minus1": daily(p - 1),
                "d0": daily(p),
                "d_plus1": daily(p + 1),
                "d_plus3": daily(p + 3),
                "d_plus7": daily(p + 7),
                "cum_d1": cum(p + 1),
                "cum_d3": cum(p + 3),
                "cum_d7": cum(p + 7),
            })
        recs = recs[-n:]
        result["indices"][label] = {"symbol": sym, "count": len(recs), "rows": recs}
        print(f"{label} ({sym}): {len(recs)} opex windows")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
