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

import bisect
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from . import cache, charts, demo_data

EARNINGS_TTL = float(os.environ.get("SUH_DH_EARNINGS_TTL", "1800"))

# Show only the most recent N reported quarters (plus any upcoming preview),
# and average the D+N drift over the most recent M of them.
MAX_QUARTERS = int(os.environ.get("SUH_DH_MAX_QUARTERS", "8"))
SUMMARY_WINDOW = int(os.environ.get("SUH_DH_SUMMARY_WINDOW", "6"))

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


def _estimate_next_q(df) -> float | None:
    """Pull the next-quarter (+1q) consensus 'avg' from a yfinance estimate frame."""
    if df is None:
        return None
    try:
        index = list(getattr(df, "index", []))
        if "+1q" not in index:
            return None
        row = df.loc["+1q"]
        val = row.get("avg") if hasattr(row, "get") else row["avg"]
        return _num(val)
    except Exception:
        return None


def forward_consensus(ticker: str) -> dict:
    """Snapshot the current next-quarter consensus (revenue + EPS) for a ticker.

    This is the automatable half of the guidance column: run it shortly *before*
    an earnings date (e.g. from the daily build) to capture the point-in-time
    consensus the company's guidance will be compared against. Uses yfinance
    forward estimates; fields are None when the source has no data.
    """
    ticker = ticker.upper().strip()
    if _demo():
        return demo_data.demo_forward_consensus(ticker)
    import yfinance as yf

    tk = yf.Ticker(ticker)
    out = {
        "ticker": ticker,
        "captured": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    for key, attrs in (
        ("revenue_consensus", ("revenue_estimate", "get_revenue_estimate")),
        ("eps_consensus", ("earnings_estimate", "get_earnings_estimate")),
    ):
        df = None
        for attr in attrs:
            try:
                obj = getattr(tk, attr, None)
                df = obj() if callable(obj) else obj
            except Exception:
                df = None
            if df is not None:
                break
        out[key] = _estimate_next_q(df)
    return out


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
    import time as _time

    import yfinance as yf

    tk = yf.Ticker(ticker)
    # Yahoo intermittently throttles/blocks (esp. from cloud IPs). Retry a few
    # times with a short backoff before giving up.
    df = None
    for attempt in range(3):
        try:
            df = tk.get_earnings_dates(limit=limit)
        except Exception:
            df = None
        if df is not None and not df.empty:
            break
        _time.sleep(0.8 * (attempt + 1))
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
        # Keep any upcoming (preview) quarter plus the most recent MAX_QUARTERS
        # reported ones — rows are already newest-first.
        upcoming_rows = [r for r in rows if r["upcoming"]]
        past_rows = [r for r in rows if not r["upcoming"]]
        rows = upcoming_rows + past_rows[:MAX_QUARTERS]
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

    # Don't pin an empty result (likely a transient Yahoo block) — retry next call.
    return cache.get_or_set(
        f"earnings:{ticker}:{limit}", EARNINGS_TTL, producer,
        cache_when=lambda v: _demo() or v.get("count", 0) > 0,
    )


# --------------------------------------------------------------------------- #
# Post-earnings price drift (D-1 / report day / D+N returns)
# --------------------------------------------------------------------------- #
# Trading-day offsets after the report close, matching the attached table.
DRIFT_OFFSETS = (1, 7, 30, 60)
# Trading-day windows BEFORE the report (pre-earnings run-up).
PRE_OFFSETS = (7,)


def _pct(base, later) -> float | None:
    b = _num(base)
    l = _num(later)
    if b is None or l is None or b == 0:
        return None
    return round((l - b) / b * 100, 1)


def drift_returns(
    dates: list[str], closes: list, report_date: str,
    offsets=DRIFT_OFFSETS, pre_offsets=PRE_OFFSETS,
) -> dict | None:
    """Price reaction around an earnings date, in *trading days*.

    ``dates`` must be ascending ``YYYY-MM-DD`` trading days with parallel
    ``closes``. D0 is the report day's close (the last trading day on or before
    ``report_date``); ``prev1_pct`` is the report-day move (D-1→D0), each
    ``d{n}`` is the return from D0 to n trading days later, and each
    ``pre_returns['d-{n}']`` is the run-up over the n trading days into D0
    (close n days before → D0). Returns None when there isn't a prior trading
    day to anchor on.
    """
    if not dates or not closes:
        return None
    idx = bisect.bisect_right(dates, report_date) - 1
    if idx < 1 or idx >= len(closes):
        return None
    d0 = _num(closes[idx])
    dm1 = _num(closes[idx - 1])
    out = {
        "d0_date": dates[idx],
        "d_minus1_close": dm1,
        "d0_close": d0,
        "prev1_pct": _pct(dm1, d0),  # the report-day move itself
        "pre_returns": {},
        "returns": {},
    }
    for n in pre_offsets:
        j = idx - n
        out["pre_returns"][f"d-{n}"] = _pct(closes[j], d0) if j >= 0 else None
    for n in offsets:
        j = idx + n
        out["returns"][f"d{n}"] = _pct(d0, closes[j]) if j < len(closes) else None
    return out


def _drift_summary(drifts: list[dict], offsets=DRIFT_OFFSETS) -> dict:
    """Average return and up-count per offset across reported quarters."""
    summary = {}
    for n in offsets:
        vals = [d["returns"].get(f"d{n}") for d in drifts]
        vals = [v for v in vals if v is not None]
        summary[f"d{n}"] = {
            "avg": round(sum(vals) / len(vals), 1) if vals else None,
            "up": sum(1 for v in vals if v > 0),
            "n": len(vals),
        }
    return summary


def get_drift(ticker: str, offsets=DRIFT_OFFSETS) -> dict:
    """Earnings table joined with the post-earnings price drift per quarter."""
    ticker = ticker.upper().strip()

    def producer():
        earnings = get_earnings(ticker)
        chart = charts.get_chart(ticker, "max")
        dates = chart.get("dates") or []
        closes = chart.get("close") or []
        quarters = []
        for q in earnings["quarters"]:
            drift = (
                drift_returns(dates, closes, q["date"], offsets)
                if q["reported"]
                else None
            )
            quarters.append({**q, "drift": drift})
        # Average the drift over only the most recent SUMMARY_WINDOW quarters
        # that have price data (quarters are newest-first).
        recent_drifts = [q["drift"] for q in quarters if q["drift"]][:SUMMARY_WINDOW]
        return {
            "ticker": ticker,
            "offsets": list(offsets),
            "summary_window": len(recent_drifts),
            "quarters": quarters,
            "summary": _drift_summary(recent_drifts, offsets),
        }

    # Don't pin an empty table (transient upstream failure) — let it retry.
    return cache.get_or_set(
        f"drift:{ticker}", EARNINGS_TTL, producer,
        cache_when=lambda v: _demo() or bool(v.get("quarters")),
    )
