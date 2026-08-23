#!/usr/bin/env python3
"""Fetch FRED rate series (nominal / TIPS real / breakeven / term premium).

Pulls daily series from FRED's key-free CSV endpoint and writes an aligned
date table + a window summary to data/fred_rates.json. Used to verify whether
the real yield stayed flat while breakeven rose around the Aug-2026 buyback.

Series: DGS10 (nominal 10Y), DFII10 (real 10Y TIPS), T10YIE (10Y breakeven),
DGS30 (nominal 30Y), ACMTP10 (ACM 10Y term premium).

Run where fred.stlouisfed.org is reachable (GitHub Actions; sandbox blocks it).

  python tools/fred_rates.py 2026-07-15
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "fred_rates.json"
SERIES = {
    "명목10Y": "DGS10",
    "실질10Y(TIPS)": "DFII10",
    "기대인플레10Y": "T10YIE",
    "명목30Y": "DGS30",
    "텀프리미엄10Y(ACM)": "ACMTP10",
}


def _get(url: str, timeout: int = 30, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 suh-dh"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def fetch(series_id: str, cosd: str) -> dict[str, float]:
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
           f"?id={series_id}&cosd={cosd}")
    txt = _get(url)
    out: dict[str, float] = {}
    for line in txt.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        d, v = parts[0], parts[1].strip()
        if v in (".", ""):
            continue
        try:
            out[d] = float(v)
        except ValueError:
            continue
    return out


def main() -> None:
    cosd = sys.argv[1] if len(sys.argv) > 1 else "2026-07-15"
    data: dict[str, dict[str, float]] = {}
    for label, sid in SERIES.items():
        try:
            data[label] = fetch(sid, cosd)
        except Exception as e:
            data[label] = {}
            print(f"  {sid}: {e}")
        time.sleep(0.2)

    all_dates = sorted({d for s in data.values() for d in s})
    table = []
    for d in all_dates:
        row = {"date": d}
        for label in SERIES:
            row[label] = data[label].get(d)
        table.append(row)

    summary = {}
    for label in SERIES:
        s = data[label]
        if not s:
            summary[label] = {"error": "no data"}
            continue
        ds = sorted(s)
        first, last = ds[0], ds[-1]
        summary[label] = {
            "first_date": first, "first": s[first],
            "last_date": last, "last": s[last],
            "change": round(s[last] - s[first], 3),
            "min": min(s.values()), "max": max(s.values()),
        }

    OUT.write_text(json.dumps(
        {"_generated": date.today().isoformat(), "cosd": cosd,
         "summary": summary, "table": table}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"→ {OUT} ({len(all_dates)} dates)")


if __name__ == "__main__":
    main()
