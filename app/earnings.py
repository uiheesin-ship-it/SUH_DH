"""Earnings calendar + consensus surprise, via Yahoo (yfinance).

For a post-earnings drift study we first need two facts per report:

  1. *when* the company reported (the earnings date), and
  2. whether the actual EPS **beat / missed / matched** the analyst consensus.

yfinance's ``get_earnings_dates()`` returns both at once: a datetime index
plus ``EPS Estimate`` (the consensus going in), ``Reported EPS`` (the actual)
and a ``Surprise(%)`` column. We normalize that into a small JSON-friendly
list and tag each quarter beat/miss/inline ourselves (computed from estimate
vs reported, so the label never depends on yfinance's surprise convention).

Note: the EPS check here (actual vs estimate) is fully automatable from the
free source. The *forward guidance vs consensus* call — the right-hand column
of many post-earnings tables — needs two numbers the free API does NOT hold:
the company's next-quarter guidance (from the earnings release/call) and the
**point-in-time** consensus for that quarter as of the report date. Those are
supplied through a small curated ``data/guidance.json`` annotation layer
(see ``classify_guidance`` / ``_load_guidance_entries``); this module just
classifies and merges them onto the matching quarter.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from . import cache, demo_data

EARNINGS_TTL = float(os.environ.get("SUH_DH_EARNINGS_TTL", "1800"))

# A report within this band of the consensus counts as "in line" rather than a
# beat/miss — a tiny rounding-level surprise is not a real surprise.
INLINE_BAND_PCT = float(os.environ.get("SUH_DH_EARNINGS_INLINE_BAND", "0.5"))

# Curated guidance-vs-consensus annotations (see module docstring). Override the
# path with SUH_DH_GUIDANCE_FILE; missing/invalid file just yields no guidance.
GUIDANCE_FILE = os.environ.get("SUH_DH_GUIDANCE_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "guidance.json"
)

# Korean labels for the EPS consensus result.
RESULT_LABELS_KO = {
    "beat": "상회",
    "miss": "하회",
    "inline": "부합",
    "unknown": "발표예정",
}

# Guidance-vs-consensus is graded on a wider scale (the table distinguishes a
# small beat from a blowout). Bands are (min surprise %, Korean label), checked
# high to low.
GUIDANCE_BANDS = [
    (15.0, "대폭상회"),
    (5.0, "상회"),
    (0.5, "소폭상회"),
    (-0.5, "부합"),
    (-5.0, "소폭하회"),
    (-15.0, "하회"),
    (float("-inf"), "대폭하회"),
]


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


def classify_guidance(guidance, consensus) -> tuple[float | None, str | None]:
    """Grade next-quarter guidance against the consensus at report time.

    Returns ``(surprise_pct, korean_label)`` where the label is one of
    대폭상회 / 상회 / 소폭상회 / 부합 / 소폭하회 / 하회 / 대폭하회. Returns
    ``(None, None)`` when either figure is missing or consensus is zero.
    """
    g = _num(guidance)
    c = _num(consensus)
    if g is None or c is None or c == 0:
        return None, None
    pct = round((g - c) / abs(c) * 100, 2)
    for threshold, label in GUIDANCE_BANDS:
        if pct >= threshold:
            return pct, label
    return pct, GUIDANCE_BANDS[-1][1]  # unreachable; -inf catches all


def _classify_entry(e: dict) -> dict:
    """Attach computed surprise + label to a raw guidance annotation."""
    pct, label = classify_guidance(e.get("guidance_mid"), e.get("consensus"))
    return {**e, "guidance_surprise_pct": pct, "guidance_result_ko": label}


def _index_guidance(entries: list[dict]) -> dict[str, list[dict]]:
    """Group classified guidance entries by the report date they were given."""
    by_date: dict[str, list[dict]] = {}
    for e in entries or []:
        rd = e.get("report_date")
        if rd:
            by_date.setdefault(rd, []).append(_classify_entry(e))
    return by_date


def _load_guidance_entries(ticker: str) -> list[dict]:
    path = Path(GUIDANCE_FILE)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get(ticker.upper(), []) if isinstance(data, dict) else []


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
        if _demo():
            rows = demo_data.demo_earnings(ticker)
            guidance = _index_guidance(demo_data.demo_guidance(ticker))
        else:
            rows = _fetch_live(ticker, limit)
            guidance = _index_guidance(_load_guidance_entries(ticker))
        for r in rows:
            # Guidance is announced at a report, for the *next* quarter, so it
            # hangs off the report-date row (matching the table layout).
            r["guidance"] = guidance.get(r["date"], [])
        reported = [r for r in rows if r["reported"]]
        beats = sum(1 for r in reported if r["result"] == "beat")
        return {
            "ticker": ticker,
            "count": len(rows),
            "reported_count": len(reported),
            "beat_count": beats,
            "guidance_count": sum(len(r["guidance"]) for r in rows),
            "quarters": rows,
        }

    return cache.get_or_set(f"earnings:{ticker}:{limit}", EARNINGS_TTL, producer)
