"""Earnings calendar + consensus surprise, via Yahoo (yfinance).

For a post-earnings drift study we first need two facts per report:

  1. *when* the company reported (the earnings date), and
  2. whether the actual EPS **beat / missed / matched** the analyst consensus.

yfinance's ``get_earnings_dates()`` returns both at once: a datetime index
plus ``EPS Estimate`` (the consensus going in), ``Reported EPS`` (the actual)
and a ``Surprise(%)`` column. We normalize that into a small JSON-friendly
list and tag each quarter beat/miss/inline ourselves (computed from estimate
vs reported, so the label never depends on yfinance's surprise convention).

Note: the consensus here is the **EPS** consensus (actual vs estimate), which
is fully automatable from the free source. Comparing forward *guidance* to
consensus — the qualitative call in many post-earnings tables — is not
reliably available for free and would need manual annotation.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone

from . import cache, demo_data

EARNINGS_TTL = float(os.environ.get("SUH_DH_EARNINGS_TTL", "1800"))

# A report within this band of the consensus counts as "in line" rather than a
# beat/miss — a tiny rounding-level surprise is not a real surprise.
INLINE_BAND_PCT = float(os.environ.get("SUH_DH_EARNINGS_INLINE_BAND", "0.5"))

# Korean labels for the UI, mirroring the style of the attached drift table.
RESULT_LABELS_KO = {
    "beat": "상회",
    "miss": "하회",
    "inline": "부합",
    "unknown": "발표예정",
}


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _num(x) -> float | None:
    """Coerce a value (incl. pandas NaN / None / strings) to float or None."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def surprise_pct(estimate, reported) -> float | None:
    """Percent surprise of reported EPS over the consensus estimate.

    ``(reported - estimate) / |estimate| * 100``. Returns None when either
    value is missing or the estimate is zero (surprise undefined).
    """
    est = _num(estimate)
    rep = _num(reported)
    if est is None or rep is None or est == 0:
        return None
    return round((rep - est) / abs(est) * 100, 2)


def classify(estimate, reported, inline_band: float = INLINE_BAND_PCT) -> str:
    """Tag a quarter: ``beat`` / ``miss`` / ``inline`` / ``unknown``.

    ``unknown`` means not yet reported (or no consensus to compare against).
    """
    if _num(reported) is None:
        return "unknown"
    sp = surprise_pct(estimate, reported)
    if sp is None:  # reported but no usable estimate
        return "unknown"
    if abs(sp) <= inline_band:
        return "inline"
    return "beat" if sp > 0 else "miss"


def _make_row(dt: datetime, estimate, reported, *, now: datetime) -> dict:
    est = _num(estimate)
    rep = _num(reported)
    result = classify(est, rep)
    return {
        "date": dt.strftime("%Y-%m-%d"),
        "datetime": dt.isoformat(timespec="seconds"),
        "eps_estimate": est,
        "reported_eps": rep,
        "surprise_pct": surprise_pct(est, rep),
        "result": result,
        "result_ko": RESULT_LABELS_KO[result],
        "reported": dt <= now and rep is not None,
        "upcoming": dt > now,
    }


def _fetch_live(ticker: str, limit: int) -> list[dict]:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    try:
        df = tk.get_earnings_dates(limit=limit)
    except Exception:
        return []
    if df is None or df.empty:
        return []

    cols = {c.lower(): c for c in df.columns}
    est_col = cols.get("eps estimate")
    rep_col = cols.get("reported eps")
    now = datetime.now(timezone.utc)

    rows: list[dict] = []
    for idx in df.index:
        try:
            dt = idx.to_pydatetime()
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        row = df.loc[idx]
        rows.append(
            _make_row(
                dt,
                row.get(est_col) if est_col else None,
                row.get(rep_col) if rep_col else None,
                now=now,
            )
        )
    # Newest first.
    rows.sort(key=lambda r: r["datetime"], reverse=True)
    return rows


def get_earnings(ticker: str, limit: int = 12) -> dict:
    """Recent (and next, if known) earnings with consensus-beat tags."""
    ticker = ticker.upper().strip()

    def producer():
        rows = (
            demo_data.demo_earnings(ticker)
            if _demo()
            else _fetch_live(ticker, limit)
        )
        reported = [r for r in rows if r["reported"]]
        beats = sum(1 for r in reported if r["result"] == "beat")
        return {
            "ticker": ticker,
            "count": len(rows),
            "reported_count": len(reported),
            "beat_count": beats,
            "quarters": rows,
        }

    return cache.get_or_set(f"earnings:{ticker}:{limit}", EARNINGS_TTL, producer)
