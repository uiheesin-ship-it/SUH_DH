"""Flatness Score (spec §11) and grade (spec §12).

100 points, split across five components, each clipped to [0,1] against the
*per-period* allowed limits so a short 20-day base is not flattered relative to a
120-day base. The score is PURE base geometry — no prior returns, no historical
activity, no volume/ATR/MA/RS/sector/fundamentals ever enter here.
"""

from __future__ import annotations


def _clip01(x: float) -> float:
    if x != x:            # NaN
        return 0.0
    return 0.0 if x < 0 else 1.0 if x > 1 else float(x)


def flatness_score(close_band: float | None, base_drift: float | None,
                   containment: float | None, center_shift: float | None,
                   outlier_ratio: float | None, thresholds: dict, cfg: dict) -> dict:
    """Return the five sub-scores and their total (0..100).

    A missing metric contributes 0 for that component rather than aborting."""
    sc = cfg["score"]
    max_band = float(thresholds["close_band"])
    max_drift = float(thresholds["base_drift"])
    max_center = float(thresholds["center_shift"])

    range_score = float(sc["range_weight"]) * (
        _clip01(1.0 - (close_band / max_band)) if close_band is not None and max_band > 0 else 0.0)
    slope_score = float(sc["slope_weight"]) * (
        _clip01(1.0 - (abs(base_drift) / max_drift)) if base_drift is not None and max_drift > 0 else 0.0)
    c_floor = float(sc["containment_floor"])
    c_span = float(sc["containment_span"])
    containment_score = float(sc["containment_weight"]) * (
        _clip01((containment - c_floor) / c_span) if containment is not None and c_span > 0 else 0.0)
    center_score = float(sc["center_weight"]) * (
        _clip01(1.0 - (center_shift / max_center)) if center_shift is not None and max_center > 0 else 0.0)
    out_scale = float(sc["outlier_scale"])
    outlier_score = float(sc["outlier_weight"]) * (
        _clip01(1.0 - (outlier_ratio / out_scale)) if outlier_ratio is not None and out_scale > 0 else 0.0)

    total = range_score + slope_score + containment_score + center_score + outlier_score
    return {
        "range_score": round(range_score, 2),
        "slope_score": round(slope_score, 2),
        "containment_score": round(containment_score, 2),
        "center_score": round(center_score, 2),
        "outlier_score": round(outlier_score, 2),
        "flatness_score": round(total, 2),
    }


def flatness_grade(score: float | None, cfg: dict) -> str:
    if score is None:
        return "Not Flat"
    g = cfg["grades"]
    if score >= float(g["very_flat"]):
        return "Very Flat"
    if score >= float(g["flat"]):
        return "Flat"
    if score >= float(g["moderate"]):
        return "Moderately Flat"
    return "Not Flat"
