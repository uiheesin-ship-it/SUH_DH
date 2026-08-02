"""Prior-trend tag (spec §7) and category acceptance (spec §8).

The prior trend is a *tag only* — it never enters the Flatness Score and never
hard-filters a name. It just describes whether the flat base followed a run-up
(Continuation), a decline (Turnaround), or neither (Neutral). Section 8 then
applies stricter acceptance to Neutral/Turnaround bases so a brief pause inside
an ongoing slide isn't mistaken for a real turnaround base.
"""

from __future__ import annotations


def prior_trend(closes, base_start_idx: int, cfg: dict) -> dict:
    """representative_prior_return = the larger-in-magnitude of the prior 60d and
    120d returns measured up to the base start; classify into a Base Category."""
    pt = cfg["prior_trend"]
    rets: dict[int, float | None] = {}
    for lb in pt["lookbacks"]:
        lb = int(lb)
        rets[lb] = _prior_return(closes, base_start_idx, lb)

    r60 = rets.get(60)
    r120 = rets.get(120)
    candidates = [(abs(r), r) for r in (r60, r120) if r is not None]
    representative = max(candidates, key=lambda t: t[0])[1] if candidates else None

    if representative is None:
        category = "Neutral Flat Base"
    elif representative >= float(pt["continuation_min"]):
        category = "Continuation Flat Base"
    elif representative <= float(pt["turnaround_max"]):
        category = "Turnaround Flat Base"
    else:
        category = "Neutral Flat Base"

    return {
        "prior_60d_return": _r(r60, 4),
        "prior_120d_return": _r(r120, 4),
        "representative_prior_return": _r(representative, 4),
        "base_category": category,
    }


def _prior_return(closes, base_start_idx: int, lookback: int) -> float | None:
    """base_start_close / close_{lookback}_days_before_base_start - 1."""
    ref_idx = base_start_idx - lookback
    if ref_idx < 0 or base_start_idx >= len(closes):
        return None
    start = closes[base_start_idx]
    ref = closes[ref_idx]
    if ref is None or ref <= 0 or start is None:
        return None
    return start / ref - 1.0


def acceptance_check(base: dict, category: str, hist: dict, cfg: dict) -> tuple[bool, list[str]]:
    """Apply the §8 category-specific acceptance rules. Returns (accepted, reasons
    for rejection)."""
    acc = cfg["acceptance"]
    reasons: list[str] = []
    n = base["base_days"]
    score = base["flatness_score"]

    if category == "Continuation Flat Base":
        c = acc["continuation"]
        if n < int(c["min_len"]):
            reasons.append(f"기간 {n}<{c['min_len']}일")
        if score < float(c["min_score"]):
            reasons.append(f"점수 {score}<{c['min_score']}")
    else:  # Neutral or Turnaround — stricter
        c = acc["turnaround_neutral"]
        if n < int(c["min_len"]):
            reasons.append(f"기간 {n}<{c['min_len']}일")
        if score < float(c["min_score"]):
            reasons.append(f"점수 {score}<{c['min_score']}")
        if (base["containment_ratio"] or 0) < float(c["min_containment"]):
            reasons.append(f"밀집도<{c['min_containment']}")
        if abs(base["base_drift"] or 0) > float(c["max_drift"]):
            reasons.append(f"드리프트>{c['max_drift']}")
        if abs(base["center_shift"] or 0) > float(c["max_center_shift"]):
            reasons.append(f"중심이동>{c['max_center_shift']}")
        if c.get("require_historical_activity") and not hist.get("historical_activity_pass"):
            reasons.append("과거활동성 미달")

    return (len(reasons) == 0, reasons)


def _r(v, nd):
    return round(v, nd) if v is not None else None
