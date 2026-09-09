"""Combine the four axes into the 0-100 Turnaround Score and a grade.

Each axis module already emits points on its own configured scale (edge 30,
quality 40, setup 20, trigger 10), so this is a sum rather than a re-weighting —
keeping the weights in one place, next to the metric that earns them, instead of
splitting them between the module and a central scorer.
"""

from __future__ import annotations


def total(quality: dict, edge: dict, setup: dict, trigger: dict) -> float:
    return round(
        float(quality.get("quality_score") or 0)
        + float(edge.get("edge_score") or 0)
        + float(setup.get("setup_score") or 0)
        + float(trigger.get("trigger_score") or 0),
        1,
    )


def grade(score: float | None, cfg: dict) -> str:
    g = cfg["grades"]
    if score is None:
        return "none"
    if score >= float(g["prime"]):
        return "prime"
    if score >= float(g["high"]):
        return "high"
    if score >= float(g["watch"]):
        return "watch"
    return "weak"


def stage(edge: dict, trigger: dict) -> str:
    """Coarse label for where in its life the setup is — the column a reader
    scans first. Ordered by how close the base is to resolving."""
    status = edge.get("pivot_status")
    if edge.get("extended"):
        return "지나감"
    if status == "broken_out" or trigger.get("trigger_fresh"):
        return "전환신호"
    if status == "ready":
        return "오른쪽끝"
    if status == "watch":
        return "다지는중"
    return "이른편"
