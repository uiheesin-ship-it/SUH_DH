"""Multi-period base search (spec §3, §5, §6) and per-period flatness evaluation.

For each of the 8 look-back windows we slice the LAST n adjusted closes (that is
the base; everything before it is "prior" data used only by activity.py, so the
base window and the historical-activity window never overlap — no look-ahead).
We compute every flatness metric, score it against the period's own thresholds,
decide whether it passes the base thresholds, and classify the base status.

`select_bases` returns all qualifying periods sorted by Flatness Score so the
orchestrator can keep the best plus a few runner-up periods (spec §17).
"""

from __future__ import annotations

from . import metrics
from .config import PERIODS, thresholds_for
from .scoring import flatness_grade, flatness_score


def base_status(current_close: float, q10: float | None, q90: float | None,
                cfg: dict) -> str:
    """Active Flat Base / Exited Upward / Exited Downward (spec §6)."""
    st = cfg["status"]
    if q10 is None or q90 is None or current_close is None:
        return "Unknown"
    lower = q10 * float(st["lower_mult"])
    upper = q90 * float(st["upper_mult"])
    if current_close > upper:
        return "Exited Upward"
    if current_close < lower:
        return "Exited Downward"
    return "Active Flat Base"


def evaluate_period(closes, highs, lows, n: int, current_close: float,
                    cfg: dict) -> dict | None:
    """Evaluate a single base length ``n``. Returns None if history is too short."""
    total = len(closes)
    if total < n or n < 20:
        return None
    win_c = closes[total - n:]
    win_h = highs[total - n:]
    win_l = lows[total - n:]

    th = thresholds_for(n, cfg)
    cband = metrics.close_band(win_c)
    drift = metrics.base_drift(win_c)
    contain = metrics.containment_ratio(win_c)
    center = metrics.center_shift(win_c)
    out_ratio = metrics.outlier_ratio(win_c)
    out_days = metrics.outlier_days(win_c)
    daily_vol = metrics.mean_abs_daily_return(win_c)   # avg |daily return| in base
    raw_range = metrics.raw_high_low_range(win_h, win_l, win_c)
    q10 = metrics.quantile(win_c, 0.10)
    q90 = metrics.quantile(win_c, 0.90)
    med = metrics.median(win_c)
    cur_pos = metrics.current_position(current_close, win_c)

    scores = flatness_score(cband, drift, contain, center, out_ratio, th, cfg)

    # Base-threshold pass = every §5 metric within its per-period limit.
    def _le(v, lim):
        return v is not None and abs(v) <= float(lim)

    def _ge(v, lim):
        return v is not None and v >= float(lim)

    base_pass = bool(
        _le(cband, th["close_band"]) and _le(drift, th["base_drift"]) and
        _ge(contain, th["containment"]) and _le(center, th["center_shift"]) and
        _le(out_ratio, th["outlier_ratio"])
    )

    # "Dead / deal-pinned" guard: a base whose average daily move is essentially
    # zero isn't a real consolidation — it's a merger-arb price locked at the
    # deal value (or a delisting-frozen name). Those score ~perfect on flatness
    # but are dead money, so they don't count as a valid flat base.
    min_dv = float(cfg.get("min_base_daily_vol", 0.0) or 0.0)
    too_dead = bool(min_dv > 0 and daily_vol is not None and daily_vol < min_dv)

    # Status band optionally ignores the most recent few days so a fresh 1-3 day
    # poke through the band doesn't rewrite the base boundaries (spec §6).
    excl = int(cfg["status"].get("exclude_recent_days", 0) or 0)
    if excl > 0 and n - excl >= 4:
        sc = win_c[:n - excl]
        sq10 = metrics.quantile(sc, 0.10)
        sq90 = metrics.quantile(sc, 0.90)
    else:
        sq10, sq90 = q10, q90
    status = base_status(current_close, sq10, sq90, cfg)

    return {
        "base_days": n,
        "base_start_idx": total - n,     # index into the full series (for prior data)
        "close_band": _r(cband, 4),
        "raw_high_low_range": _r(raw_range, 4),
        "base_drift": _r(drift, 4),
        "containment_ratio": _r(contain, 4),
        "center_shift": _r(center, 4),
        "outlier_days": out_days,
        "outlier_ratio": _r(out_ratio, 4),
        "base_daily_vol": _r(daily_vol, 5),
        "too_dead": too_dead,
        "current_position": _r(cur_pos, 4),
        "base_low_q10": _r(q10, 4),
        "base_high_q90": _r(q90, 4),
        "base_median": _r(med, 4),
        "base_pass": base_pass,
        "base_status": status,
        **scores,
        "flatness_grade": flatness_grade(scores["flatness_score"], cfg),
    }


def select_bases(closes, highs, lows, current_close, cfg: dict) -> list[dict]:
    """Evaluate every period; return those meeting the base thresholds, best
    Flatness Score first (spec §3: pick the highest-scoring qualifying period)."""
    out = []
    for n in PERIODS:
        ev = evaluate_period(closes, highs, lows, n, current_close, cfg)
        if ev is not None:
            out.append(ev)
    # A period qualifies only if it passes the flatness thresholds AND isn't
    # dead/deal-pinned (near-zero daily movement). Excluding dead periods here
    # means a stock pinned across all its windows drops out entirely.
    qualifying = [e for e in out if e["base_pass"] and not e.get("too_dead")]
    qualifying.sort(key=lambda e: e["flatness_score"], reverse=True)
    return qualifying


def _r(v, nd):
    return round(v, nd) if v is not None else None
