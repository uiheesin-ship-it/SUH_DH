"""Fetch US stocks making new 52-week highs and group them for the dashboard.

Primary source: Finviz screener "New High" signal (ta_newhigh) via the
``finvizfinance`` package. The Overview view conveniently returns ticker,
sector, industry, market cap, price and change in one request.
"""

from __future__ import annotations

import os

from . import cache, demo_data

# Finviz updates roughly with the market; a few minutes of caching is plenty
# and keeps us well under their rate limits.
HIGHS_TTL = float(os.environ.get("SUH_DH_HIGHS_TTL", "180"))


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _normalize_change(raw) -> float | None:
    """Finviz returns Change as a fraction (0.0523). Present it as percent."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    # Values are fractions (e.g. 0.0523 == 5.23%). Anything already large is
    # assumed to be a percentage already.
    return round(val * 100, 2) if abs(val) < 1.5 else round(val, 2)


def _fetch_live() -> list[dict]:
    from finvizfinance.screener.overview import Overview

    fos = Overview()
    fos.set_filter(signal="New High")
    df = fos.screener_view(order="Market Cap", ascend=False, verbose=0)
    if df is None or df.empty:
        return []

    rows: list[dict] = []
    for _, r in df.iterrows():
        industry = r.get("Industry")
        rows.append(
            {
                "ticker": r.get("Ticker"),
                "company": r.get("Company"),
                "sector": (r.get("Sector") or "Unknown") or "Unknown",
                "industry": industry if industry and str(industry) != "nan" else None,
                "market_cap": _to_float(r.get("Market Cap")),
                "price": _to_float(r.get("Price")),
                "change_pct": _normalize_change(r.get("Change")),
            }
        )
    return rows


def _to_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def fetch_new_highs() -> list[dict]:
    """Return a flat list of new-high stocks (cached)."""

    def producer():
        return demo_data.demo_new_highs() if _demo() else _fetch_live()

    return cache.get_or_set("new_highs", HIGHS_TTL, producer)


def group_by_sector(rows: list[dict]) -> list[dict]:
    """Group rows by sector -> industry, each sorted by market cap desc.

    Returns a list of sectors (sorted by total market cap) where each sector
    has either an ``industries`` list (sub-sectors) or, when no industry info
    exists, a flat ``stocks`` list.
    """
    sectors: dict[str, dict] = {}
    for row in rows:
        sec = row.get("sector") or "Unknown"
        sectors.setdefault(sec, {"sector": sec, "_industries": {}, "stocks": []})
        ind = row.get("industry")
        if ind:
            sectors[sec]["_industries"].setdefault(ind, []).append(row)
        else:
            sectors[sec]["stocks"].append(row)

    def mcap(x):
        return x.get("market_cap") or 0

    result = []
    for sec in sectors.values():
        industries = []
        for name, stocks in sec["_industries"].items():
            stocks.sort(key=mcap, reverse=True)
            industries.append(
                {
                    "industry": name,
                    "stocks": stocks,
                    "market_cap": sum(mcap(s) for s in stocks),
                    "count": len(stocks),
                }
            )
        industries.sort(key=lambda i: i["market_cap"], reverse=True)
        loose = sorted(sec["stocks"], key=mcap, reverse=True)
        total = sum(i["market_cap"] for i in industries) + sum(mcap(s) for s in loose)
        result.append(
            {
                "sector": sec["sector"],
                "industries": industries,
                "stocks": loose,  # stocks with no sub-sector
                "market_cap": total,
                "count": sum(i["count"] for i in industries) + len(loose),
            }
        )
    result.sort(key=lambda s: s["market_cap"], reverse=True)
    return result


def get_dashboard() -> dict:
    rows = fetch_new_highs()
    return {
        "count": len(rows),
        "sectors": group_by_sector(rows),
        "demo": _demo(),
    }
