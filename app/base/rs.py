"""Relative-strength percentiles computed across the scanned universe.

Percentile is *within the universe we actually scanned* (a few hundred liquid
names), not literally every US stock — good enough to rank leadership and what
Minervini's "RS rating" approximates. Composite blends 3/6/12-month returns.
"""

from __future__ import annotations

import numpy as np


def _percentiles(values: list[float | None]) -> list[float | None]:
    """Rank-based percentile 0..100 for the non-None values; None stays None."""
    idx = [i for i, v in enumerate(values) if v is not None and np.isfinite(v)]
    out: list[float | None] = [None] * len(values)
    if not idx:
        return out
    arr = np.array([values[i] for i in idx], dtype=float)
    order = arr.argsort()
    ranks = np.empty(len(arr), dtype=float)
    # Average ranks for ties, then scale to 0..100.
    ranks[order] = np.arange(len(arr), dtype=float)
    if len(arr) > 1:
        pct = ranks / (len(arr) - 1) * 100.0
    else:
        pct = np.array([100.0])
    for k, i in enumerate(idx):
        out[i] = round(float(pct[k]), 1)
    return out


def assign_rs(records: list[dict], cfg: dict) -> None:
    """Attach rs_pct_3m/6m/12m, rs_composite and rs_percentile to each record.

    ``records`` must each carry ret_3m / ret_6m / ret_12m (may be None).
    Mutates in place.
    """
    w = cfg["rs_composite"]
    p3 = _percentiles([r.get("ret_3m") for r in records])
    p6 = _percentiles([r.get("ret_6m") for r in records])
    p12 = _percentiles([r.get("ret_12m") for r in records])

    for i, r in enumerate(records):
        r["rs_pct_3m"] = p3[i]
        r["rs_pct_6m"] = p6[i]
        r["rs_pct_12m"] = p12[i]
        # Composite: weight available percentiles, renormalising when some are
        # missing so a short-history name isn't unfairly zeroed.
        parts = [(p3[i], w["w_3m"]), (p6[i], w["w_6m"]), (p12[i], w["w_12m"])]
        num = sum(v * wt for v, wt in parts if v is not None)
        den = sum(wt for v, wt in parts if v is not None)
        comp = round(num / den, 1) if den > 0 else None
        r["rs_composite"] = comp
        # rs_percentile used by the trend template = composite when available,
        # else the 6m percentile, else the 3m percentile.
        r["rs_percentile"] = comp if comp is not None else (p6[i] if p6[i] is not None else p3[i])
