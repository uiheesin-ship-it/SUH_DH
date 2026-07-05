"""Korean post-earnings price drift — 상승률 only (no consensus / EPS).

Korean quarterly earnings *dates* aren't available from the free APIs, so this
program anchors the drift on a curated per-ticker date list
(``data/kr_earnings.json``) and computes the same D-7 / report-day / D+N price
returns from Yahoo (yfinance) daily prices — reusing ``earnings.drift_returns``.
Unlike the US earnings program there is no EPS-beat or guidance column; this is
purely the price reaction around each reported quarter.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import cache, charts
from .earnings import (
    DRIFT_OFFSETS,
    EARNINGS_TTL,
    MAX_QUARTERS,
    SUMMARY_WINDOW,
    _drift_summary,
    drift_returns,
)

# Curated Korean earnings dates. Override with SUH_DH_KR_FILE; a missing/invalid
# file simply yields no Korean tickers.
KR_FILE = os.environ.get("SUH_DH_KR_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "kr_earnings.json"
)


def _load() -> dict:
    path = Path(KR_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def kr_meta(ticker: str) -> dict:
    entry = _load().get(ticker.upper(), {})
    return entry if isinstance(entry, dict) else {}


def kr_tickers() -> list[str]:
    return sorted(t for t in _load() if not t.startswith("_"))


def kr_groups() -> list[dict]:
    """Registered Korean tickers grouped by sector, in file (curation) order.

    Each group is ``{"sector": str, "items": [{"ticker","name"}, ...]}``. Korean
    tickers are numeric codes, so the display name matters — the frontend shows
    the company name and loads by ticker code.
    """
    data = _load()
    order: list[str] = []
    buckets: dict[str, list[dict]] = {}
    for t, meta in data.items():
        if t.startswith("_") or not isinstance(meta, dict):
            continue
        sector = meta.get("sector") or "기타"
        if sector not in buckets:
            buckets[sector] = []
            order.append(sector)
        buckets[sector].append({"ticker": t, "name": meta.get("name", t)})
    return [{"sector": s, "items": buckets[s]} for s in order]


def get_kr_drift(ticker: str, offsets=DRIFT_OFFSETS) -> dict:
    """Post-earnings price drift for one Korean ticker (curated dates)."""
    ticker = ticker.upper().strip()

    def producer():
        meta = kr_meta(ticker)
        raw_dates = [d for d in (meta.get("dates") or []) if d]
        # Newest first, most recent MAX_QUARTERS.
        raw_dates = sorted(set(raw_dates), reverse=True)
        chart = charts.get_chart(ticker, "max")
        pdates = chart.get("dates") or []
        closes = chart.get("close") or []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        quarters = []
        for rd in raw_dates:
            reported = rd <= today
            drift = drift_returns(pdates, closes, rd, offsets) if reported else None
            quarters.append(
                {"date": rd, "reported": reported, "upcoming": not reported, "drift": drift}
            )
        # Keep any upcoming preview + the most recent MAX_QUARTERS reported ones.
        upcoming = [q for q in quarters if q["upcoming"]]
        past = [q for q in quarters if q["reported"]]
        quarters = upcoming + past[:MAX_QUARTERS]

        recent_drifts = [q["drift"] for q in quarters if q["drift"]][:SUMMARY_WINDOW]
        return {
            "ticker": ticker,
            "name": meta.get("name", ticker),
            "sector": meta.get("sector"),
            "currency": "KRW",
            "offsets": list(offsets),
            "summary_window": len(recent_drifts),
            "quarters": quarters,
            "summary": _drift_summary(recent_drifts, offsets),
        }

    # Don't pin an empty/priceless table (transient Yahoo block) — let it retry.
    return cache.get_or_set(
        f"krdrift:{ticker}", EARNINGS_TTL, producer,
        cache_when=lambda v: any(q.get("drift") for q in v.get("quarters", [])),
    )
