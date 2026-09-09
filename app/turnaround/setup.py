"""Bottom setup — 20 points on the question "is the decline actually over?"

Not the Minervini template with the signs flipped. Requiring price above a
rising 200-day here would only find stocks that already completed their
turnaround, which is the opposite of the goal: at the right edge of a bottom
base the 200-day is usually still overhead and still sloping down. What has to
be true instead is weaker and earlier —

    decel        the 200-day slope has flattened out (it may still be negative)
    ma_recover   price has climbed back toward, or through, its averages
    rs_repair    the RS line has stopped making lows inside the base

All three give partial credit. A name 15% under a barely-falling 200-day with a
repaired RS line is exactly the shape we want and would score zero under any
pass/fail template.
"""

from __future__ import annotations

import math

from ..base import metrics as bmetrics


def _ramp(x: float | None, full: float, zero: float) -> float | None:
    if x is None or not math.isfinite(x) or full == zero:
        return None
    return float(min(1.0, max(0.0, (x - zero) / (full - zero))))


def _slope(series, lookback: int) -> float | None:
    """Fractional change of an SMA over ``lookback`` bars (not log slope — this
    reads directly as "the 200-day fell 4% over the last 40 days")."""
    now = bmetrics.value_n_days_ago(series, 0)
    then = bmetrics.value_n_days_ago(series, lookback)
    if now is None or then is None or then <= 0:
        return None
    return now / then - 1.0


def rs_repair(closes, bench_closes, base_start_idx: int) -> float | None:
    """RS line now vs its lowest point inside the base window.

    Measured against the base's own RS low rather than a market-wide percentile:
    a bottom-base name is near the bottom of any percentile ranking by
    construction, so the only informative question is whether it has stopped
    losing ground *within* the base.
    """
    if not bench_closes:
        return None
    rl = bmetrics.rs_line(closes, bench_closes)
    if not rl:
        return None
    # rs_line trims to the shorter tail, so re-anchor the base start to it.
    offset = len(closes) - len(rl)
    start = max(0, base_start_idx - offset)
    seg = [v for v in rl[start:] if v is not None]
    if len(seg) < 5:
        return None
    lo = min(seg)
    last = seg[-1]
    if lo is None or lo <= 0 or last is None:
        return None
    return last / lo - 1.0


def compute(closes, window: dict, cfg: dict, bench_closes=None) -> dict:
    s = cfg["setup"]
    w = s["weights"]
    price = closes[-1]

    sma50_series = bmetrics.sma_series(closes, 50)
    sma200_series = bmetrics.sma_series(closes, 200)
    sma50 = bmetrics.value_n_days_ago(sma50_series, 0)
    sma200 = bmetrics.value_n_days_ago(sma200_series, 0)

    slope50 = _slope(sma50_series, int(s["slope_lookback_fast"]))
    slope200 = _slope(sma200_series, int(s["slope_lookback_slow"]))

    s_decel = _ramp(slope200, float(s["slope200_full"]), float(s["slope200_zero"]))
    if s_decel is None:
        # No 200-day yet (recent listing): fall back to the 50-day slope so a
        # young name is judged on the trend it does have, not failed for age.
        s_decel = _ramp(slope50, float(s["slope50_full"]), float(s["slope50_zero"]))

    r50 = (price / sma50 - 1.0) if (sma50 and sma50 > 0 and price) else None
    r200 = (price / sma200 - 1.0) if (sma200 and sma200 > 0 and price) else None
    s_r50 = _ramp(r50, 0.02, -0.10)
    s_r200 = _ramp(r200, 0.00, -0.20)
    parts = [p for p in (s_r50, s_r200) if p is not None]
    s_recover = (sum(parts) / len(parts)) if parts else None

    rsr = rs_repair(closes, bench_closes, int(window["base_start_idx"]))
    s_rs = _ramp(rsr, float(s["rs_repair_full"]), 0.0)

    def _n(x):
        return 0.5 if x is None else x

    weight = float(cfg["score"]["setup_weight"])
    pts = weight * (
        float(w["decel"]) * _n(s_decel)
        + float(w["ma_recover"]) * _n(s_recover)
        + float(w["rs_repair"]) * _n(s_rs)
    )

    return {
        "sma50": sma50,
        "sma200": sma200,
        "sma50_slope": round(slope50, 4) if slope50 is not None else None,
        "sma200_slope": round(slope200, 4) if slope200 is not None else None,
        "price_vs_sma50": round(r50, 4) if r50 is not None else None,
        "price_vs_sma200": round(r200, 4) if r200 is not None else None,
        "rs_repair": round(rsr, 4) if rsr is not None else None,
        "setup_decel_score": round(weight * float(w["decel"]) * _n(s_decel), 2),
        "setup_recover_score": round(weight * float(w["ma_recover"]) * _n(s_recover), 2),
        "setup_rs_score": round(weight * float(w["rs_repair"]) * _n(s_rs), 2),
        "setup_score": round(pts, 2),
    }
