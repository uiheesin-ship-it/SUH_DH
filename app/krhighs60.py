"""Korean 60-trading-day-high screener — the 60일 variant of app/krhighs.py.

Identical universe, data source, exclusions and output shape as ``krhighs``;
the ONLY difference is the look-back window: a stock qualifies when today's high
is the highest of the last 60 trading days (≈3 months) instead of 52 weeks.
Everything else (KRX listing, Yahoo .KS/.KQ bars, sector→industry grouping) is
reused from ``krhighs`` so the two stay in lock-step.
"""

from __future__ import annotations

import os
import time

from . import cache
from .krhighs import _demo, _demo_rows, _yahoo_symbol, kr_universe
from .screener import group_by_sector

KRHIGHS60_TTL = float(os.environ.get("SUH_DH_KRHIGHS60_TTL", "600"))
# Look-back window in trading days. 60 ≈ 3 months.
WINDOW = int(os.environ.get("SUH_DH_KR60_WINDOW", "60"))
# How strict "new high" is (1.0 = today's high must equal/exceed the window peak).
NEAR_RATIO = float(os.environ.get("SUH_DH_KR60_NEAR_HIGH", "1.0"))


def _made_new_high(bars: dict) -> bool:
    """True if today's high is the highest of the last ``WINDOW`` trading days."""
    high = bars.get("high") or []
    if len(high) < WINDOW:               # need a full window to be meaningful
        return False
    window = high[-WINDOW:]
    prior = window[:-1] or window
    today = high[-1]
    peak_prior = max((p for p in prior if p is not None), default=None)
    if today is None or peak_prior is None:
        return False
    return today >= peak_prior * NEAR_RATIO


def _fetch_live() -> list[dict]:
    from .base import data as basedata  # reuse the proven Yahoo/Stooq bar fetcher

    out: list[dict] = []
    for r in kr_universe():
        sym = _yahoo_symbol(r["code"], r["market"])
        try:
            bars = basedata.fetch_bars(sym)
        except Exception:
            continue
        if not bars or not bars.get("high"):
            continue
        if not _made_new_high(bars):
            continue
        close = bars.get("close") or []
        price = close[-1] if close else r.get("price")
        change = r.get("change_pct")
        if change is None and len(close) >= 2 and close[-2]:
            change = round((close[-1] / close[-2] - 1) * 100, 2)
        out.append({
            "ticker": r["code"],
            "company": r["name"],
            "sector": r.get("sector") or r["market"],
            "industry": r.get("industry"),
            "market": r["market"],
            "yahoo": sym,
            "market_cap": r.get("market_cap"),
            "price": round(price, 2) if price is not None else None,
            "change_pct": change,
        })
        time.sleep(0.15)  # be gentle with Yahoo
    return out


def fetch_new_highs() -> list[dict]:
    def producer():
        return _demo_rows() if _demo() else _fetch_live()

    return cache.get_or_set("kr_new_highs_60", KRHIGHS60_TTL, producer,
                            cache_when=lambda r: bool(r) or _demo())


def get_dashboard() -> dict:
    rows = fetch_new_highs()
    return {
        "count": len(rows),
        "sectors": group_by_sector(rows),
        "demo": _demo(),
        "market_cap_currency": "KRW",
    }
