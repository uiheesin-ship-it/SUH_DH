"""US 52-week-high list derived from the base-screener scan (Finviz-independent).

Finviz's "New High" signal screener (app/screener.py) keeps getting the GitHub
Actions runner blocked ("Finviz screener returned no data"), which froze the
published list for weeks. The base screener already fetches ~2 years of daily
bars for the whole US universe (its universe has a Finviz→Nasdaq/FDR→snapshot
fallback, so it survives a Finviz block), and app/base/screen.py now flags each
record's `new_high_52w` (today's close ≥ the prior 252-session closing high).
So we build the 52주 신고가 list straight from that scan's records — no extra
network, and it stays fresh as long as the base scan runs.

Rows match app/screener.get_dashboard() so the frontend/grouping is shared.
"""

from __future__ import annotations

from .screener import group_by_sector


def _row(r: dict) -> dict:
    return {
        "ticker": r.get("ticker"),
        "company": r.get("company_name"),
        "sector": r.get("sector") or "Unknown",
        "industry": r.get("industry"),
        "market_cap": r.get("market_cap"),
        "price": r.get("current_price"),
        "change_pct": r.get("change_pct"),
        "volume": r.get("last_volume"),
        "turnover": r.get("turnover"),
        "ath": False,   # true ATH is set later from each name's full-range chart
    }


def has_support(payload: dict) -> bool:
    """True if the base payload carries the new-high flag (post-upgrade scan)."""
    stocks = (payload or {}).get("stocks") or []
    return any("new_high_52w" in s for s in stocks)


def dashboard_from_base(payload: dict) -> dict:
    """Build the 52주 신고가 dashboard from a base-scan payload."""
    stocks = (payload or {}).get("stocks") or []
    rows = [_row(s) for s in stocks if s.get("new_high_52w")]
    # Data-as-of = latest price-bar date among the new-high names (what the
    # numbers actually reflect); drives the staleness badge on the page.
    asof = max((s.get("last_bar_date") for s in stocks if s.get("last_bar_date")),
               default=(payload or {}).get("data_asof"))
    return {
        "count": len(rows),
        "sectors": group_by_sector(rows),
        "demo": bool((payload or {}).get("demo")),
        "data_asof": asof,
        "source": "base-scan",
    }
