"""Historical Activity Filter (spec §9) and Chronically Low Volatility exclusion
(spec §10).

Both use ONLY the data BEFORE the base starts (closes[:base_start_idx]) — the
base window itself is never looked at here, so a genuinely flat *recent* base
does not make a stock look active, and a lively past does not leak into the
Flatness Score. Direction of past movement is intentionally ignored: a stock
that ran up and a stock that crashed both count as "active".
"""

from __future__ import annotations

from . import metrics


def historical_activity(closes, base_start_idx: int, current_base_close_band,
                        cfg: dict) -> dict:
    """Compute prior close-band activity, max absolute prior moves, base
    distinctness, the pass flag, and the chronic-low-vol flag."""
    ha = cfg["historical_activity"]
    clv = cfg["chronic_low_vol"]
    prior = list(closes[:base_start_idx])   # strictly pre-base

    short_w = int(ha["prior_short_window"])
    long_w = int(ha["prior_long_window"])
    prior_120 = prior[-short_w:] if len(prior) >= 1 else []
    prior_252 = prior[-long_w:] if len(prior) >= 1 else []

    prior_120_band = metrics.close_band(prior_120) if len(prior_120) >= 20 else None
    prior_252_band = metrics.close_band(prior_252) if len(prior_252) >= 20 else None

    lbs = ha.get("max_abs_lookbacks", [20, 60])
    max_abs = {}
    for lb in lbs:
        max_abs[lb] = metrics.max_abs_rolling_return(prior_252, int(lb))
    max_abs_20 = max_abs.get(20)
    max_abs_60 = max_abs.get(60)
    moves = [m for m in (max_abs_20, max_abs_60) if m is not None]
    max_abs_move = max(moves) if moves else None

    # base_distinctness = prior_252_close_band / current_base_close_band, guarded.
    distinctness = None
    if (prior_252_band is not None and current_base_close_band is not None
            and current_base_close_band > 1e-4):
        distinctness = prior_252_band / current_base_close_band

    # Not enough prior history to judge activity => flag as insufficient (do not
    # invent a pass; the orchestrator surfaces it as a reason).
    insufficient = prior_252_band is None and prior_120_band is None and max_abs_move is None

    def _ge(v, lim):
        return v is not None and v >= float(lim)

    passed = bool(
        _ge(prior_120_band, ha["min_prior_120_close_band"]) or
        _ge(max_abs_move, ha["min_max_abs_move"]) or
        _ge(distinctness, ha["min_base_distinctness"])
    )

    def _lt(v, lim):
        return v is not None and v < float(lim)

    # Chronically low vol: ALL of the four low-activity conditions hold.
    chronic = bool(
        not insufficient and
        _lt(prior_252_band, clv["max_prior_252_close_band"]) and
        _lt(max_abs_20, clv["max_abs_20d"]) and
        _lt(max_abs_60, clv["max_abs_60d"]) and
        _lt(distinctness, clv["max_base_distinctness"])
    )

    return {
        "prior_120_close_band": _r(prior_120_band, 4),
        "prior_252_close_band": _r(prior_252_band, 4),
        "max_abs_20d_return": _r(max_abs_20, 4),
        "max_abs_60d_return": _r(max_abs_60, 4),
        "max_abs_move": _r(max_abs_move, 4),
        "base_distinctness": _r(distinctness, 3),
        "historical_activity_pass": passed,
        "chronically_low_vol": chronic,
        "historical_activity_insufficient": insufficient,
    }


def _r(v, nd):
    return round(v, nd) if v is not None else None
