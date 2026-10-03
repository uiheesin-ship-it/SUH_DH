"""Alternate universe source: the key-free Nasdaq stock screener API.

Finviz throttles the GitHub-Actions datacenter IP, which collapses the candidate
universe (명단). The snapshot/bootstrap fallbacks in ``universe_cache`` only reuse
the LAST-GOOD ticker list, so while Finviz is down the 명단 stops updating daily
(only prices refresh). This module is a true *alternate upstream*: a different
host (api.nasdaq.com) with different anti-bot behaviour, already proven reachable
from the runner in ``app/earnings.py``. One call returns the full US-listed
screener (symbol / name / sector / industry / market cap / price / country), so
when Finviz collapses the screeners can rebuild a FRESH daily universe instead of
freezing the old list.

Only stdlib (urllib + json) — no new dependency. The request idiom (browser UA +
Accept header) mirrors ``app/earnings.py:_fetch_nasdaq``.

The rows are mapped to the same candidate-dict shape the screeners' Finviz path
produces, so the downstream filters/exclusions and ``_build_record`` consume them
unchanged. Nasdaq has no "above 50/200-day" field, so the stock universe comes
back unfiltered by moving average — below-MA names are scored low by the trend
template, not dropped, which is the desired behaviour for a fresh daily 명단.
"""

from __future__ import annotations

import json as _json
import time
import urllib.request

# api.nasdaq.com screener. tableonly=true + limit=0 + download=true returns every
# listed row in one shot (no pagination). assetclass picks stocks vs ETFs.
_BASE = "https://api.nasdaq.com/api/screener/{kind}?tableonly=true&limit=0&download=true"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
_RETRIES = 3
_TIMEOUT = 20


def _to_float(v) -> float | None:
    """Parse Nasdaq's money/number strings: "$1,234.56", "1,234,567,890",
    "N/A", "--", "", or a bare number. Returns None when not a finite number."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if f == f else None
    s = str(v).strip()
    if not s or s in ("N/A", "--", "NA", "nan"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        f = float(s)
    except ValueError:
        return None
    if f != f:   # NaN
        return None
    return -f if neg else f


def _rows_from_payload(payload: dict) -> list[dict]:
    """Pull the row list out defensively — Nasdaq has shipped the rows under a
    few different shapes (data.rows / data.table.rows / data.data.rows)."""
    data = (payload or {}).get("data") or {}
    for path in (("rows",), ("table", "rows"), ("data", "rows")):
        node = data
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, list) and node:
            return node
    return []


def _map_row(r: dict, *, is_etf: bool) -> dict | None:
    """Map one Nasdaq screener row to a candidate dict. Returns None for rows
    with no ticker or no market cap (unusable for the cap-based filters)."""
    sym = (r.get("symbol") or r.get("Symbol") or "").strip().upper()
    if not sym or "^" in sym or "/" in sym:   # drop warrants/units/odd classes
        return None
    mc = _to_float(r.get("marketCap") or r.get("MarketCap"))
    if mc is None or mc <= 0:
        return None
    price = _to_float(r.get("lastsale") or r.get("lastSalePrice")
                      or r.get("lastSale") or r.get("price"))
    name = r.get("name") or r.get("companyName") or r.get("Name")
    sector = r.get("sector") or r.get("Sector") or "Unknown"
    industry = r.get("industry") or r.get("Industry")
    country = r.get("country") or r.get("Country")
    return {
        "ticker": sym,
        "company": name,
        "sector": sector or "Unknown",
        "industry": industry if industry and str(industry) != "nan" else None,
        "market_cap": mc,
        "price": price,
        "country": country,
        "is_etf": bool(is_etf),
        "from_ipo_pass": False,
    }


def fetch(kind: str = "stocks") -> list[dict]:
    """Fetch the Nasdaq screener for ``kind`` ("stocks" or "etf") and return a
    list of candidate dicts. Returns [] on any failure (blocked/throttled/parse),
    so the caller falls through to the snapshot/bootstrap tiers.
    """
    kind = "etf" if str(kind).lower() in ("etf", "etfs") else "stocks"
    url = _BASE.format(kind=kind)
    payload = None
    for attempt in range(_RETRIES):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                payload = _json.loads(resp.read().decode("utf-8", "replace"))
            break
        except Exception:
            payload = None
            if attempt < _RETRIES - 1:
                time.sleep(2 * (attempt + 1))   # 2s, 4s
    if not payload:
        return []

    rows_raw = _rows_from_payload(payload)
    is_etf = (kind == "etf")
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows_raw:
        rec = _map_row(r, is_etf=is_etf)
        if rec is None or rec["ticker"] in seen:
            continue
        seen.add(rec["ticker"])
        out.append(rec)
    return out
