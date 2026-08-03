"""Score computation — ALL in code, never emitted by the LLM (spec §1-5, §14).

Every score here is **Experimental** and must be surfaced as such in the UI,
alongside its weights, raw components, missing-component count, and version
(spec §13, §14). The LLM only supplies the raw qualitative components
(direction/intensity/etc.); this module turns those + verified numbers into
numbers.

Narrative Momentum and Fundamental Confirmation are computed **separately**
(spec §6, §13): a glowing narrative with weak numbers must not average into a
"fine" blended score — the gap is the signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config

_DIRECTION_VALUE = {"positive": 1.0, "neutral": 0.5, "mixed": 0.5, "negative": 0.0}


def _mean(xs: list[float], default: float = 0.0) -> float:
    return sum(xs) / len(xs) if xs else default


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# --------------------------- Narrative Momentum ----------------------------

@dataclass
class ScoreBreakdown:
    score: float | None
    components: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)
    missing_component_count: int = 0
    status: str = "ok"                 # ok | data_insufficient
    is_experimental: bool = True
    score_version: str = "s1"
    extra: dict = field(default_factory=dict)


def narrative_momentum(mentions: list[dict], *, score_version: str = "s1") -> ScoreBreakdown:
    """0..1 momentum of management's *narrative* (spec §13).

    ``mentions`` are TopicMention dicts for one company-quarter (or theme).
    """
    if not mentions:
        return ScoreBreakdown(score=None, status="data_insufficient",
                              missing_component_count=6, score_version=score_version)

    n = len(mentions)
    comp = {
        "direction": _mean([_DIRECTION_VALUE.get(m.get("direction", "neutral"), 0.5)
                            for m in mentions]),
        "intensity": _mean([min(5, max(0, m.get("intensity", 0))) / 5.0 for m in mentions]),
        "management_initiated": sum(1 for m in mentions if m.get("management_initiated")) / n,
        "exec_direct": sum(1 for m in mentions if m.get("speaker_role") in ("ceo", "cfo")) / n,
        "prepared_inclusion": sum(1 for m in mentions
                                  if m.get("section_type") == "prepared_remarks") / n,
        "forward_looking": sum(1 for m in mentions if m.get("forward_looking")) / n,
    }
    weights = {
        "direction": 0.25, "intensity": 0.20, "management_initiated": 0.15,
        "exec_direct": 0.15, "prepared_inclusion": 0.15, "forward_looking": 0.10,
    }
    score = _clamp01(sum(comp[k] * weights[k] for k in weights))
    return ScoreBreakdown(score=round(score, 4), components=comp, weights=weights,
                          score_version=score_version)


# ------------------------ Fundamental Confirmation -------------------------

def _map_growth(g: float | None) -> float | None:
    """Map a YoY growth rate to 0..1 (>= +20% → 1.0, <= -20% → 0.0)."""
    if g is None:
        return None
    return _clamp01((g + 0.20) / 0.40)


def fundamental_confirmation(verified_kpis: list[dict], guidance: list[dict], *,
                             minimum_verified_kpi_count: int = 3,
                             score_version: str = "s1") -> ScoreBreakdown:
    """0..1 confirmation from **verified** numbers only (spec §6.2, §13).

    If fewer than ``minimum_verified_kpi_count`` verified KPIs exist, do NOT
    force a score — return data_insufficient (spec §13).
    """
    verified = [k for k in verified_kpis if k.get("verification_status") == "verified"]
    if len(verified) < minimum_verified_kpi_count:
        return ScoreBreakdown(
            score=None, status="data_insufficient",
            components={"verified_kpi_count": len(verified)},
            extra={"minimum_verified_kpi_count": minimum_verified_kpi_count},
            missing_component_count=minimum_verified_kpi_count - len(verified),
            score_version=score_version,
        )

    growth_vals = [_map_growth(k.get("yoy_growth")) for k in verified]
    growth_vals = [g for g in growth_vals if g is not None]

    guide_vals = []
    for g in guidance:
        mid, cons = g.get("guidance_mid"), g.get("consensus")
        if mid is not None and cons:
            guide_vals.append(_map_growth((mid / cons) - 1.0))

    comp = {
        "kpi_growth": _mean(growth_vals) if growth_vals else None,
        "guidance_vs_consensus": _mean(guide_vals) if guide_vals else None,
        "verified_kpi_count": len(verified),
    }
    present = [comp["kpi_growth"], comp["guidance_vs_consensus"]]
    present = [p for p in present if p is not None]
    missing = 2 - len(present)
    score = _clamp01(_mean(present)) if present else None
    status = "ok" if present else "data_insufficient"
    return ScoreBreakdown(score=round(score, 4) if score is not None else None,
                          components=comp, missing_component_count=missing, status=status,
                          score_version=score_version)


# --------------------------- Classification --------------------------------

def classify(narrative: ScoreBreakdown, fundamental: ScoreBreakdown, *,
             narrative_threshold: float = 0.6,
             fundamental_threshold: float = 0.6) -> dict:
    """Narrative×Numbers → NarrativeConfirmationStatus (spec §13)."""
    if fundamental.score is None or fundamental.status == "data_insufficient":
        return {
            "status": "Mixed Signals",
            "reason": "insufficient_verified_kpi",
            "narrative_strong": (narrative.score or 0) >= narrative_threshold,
            "fundamental_available": False,
        }
    n_strong = (narrative.score or 0) >= narrative_threshold
    f_strong = fundamental.score >= fundamental_threshold
    if n_strong and f_strong:
        status = "Confirmed Acceleration"
    elif n_strong and not f_strong:
        status = "Narrative Ahead of Numbers"
    elif not n_strong and f_strong:
        status = "Conservative or Underpromising"
    else:
        status = "Confirmed Deterioration"
    return {"status": status, "narrative_strong": n_strong, "fundamental_strong": f_strong,
            "fundamental_available": True}


# ------------------------------ Theme Score --------------------------------

def theme_score(components: dict, *, weights: dict | None = None,
                minimum_company_breadth: int = 3, company_count: int | None = None,
                score_version: str = "s1") -> ScoreBreakdown:
    """Weighted theme score out of 100 (spec §14).

    ``components`` are each already normalized 0..1:
      breadth, momentum, intensity, persistence,
      value_chain_confirmation, numeric_confirmation.
    Frequency alone must not win — breadth/value-chain/numeric are weighted so
    independent cross-company confirmation dominates (spec §14). Missing
    components are NOT silently normalized away: the score is flagged
    data_insufficient rather than inflated.
    """
    weights = weights or config.theme_score_weights()
    required = list(weights.keys())
    missing = [k for k in required if components.get(k) is None]

    # Breadth gate: too few independent companies → don't present a real score.
    if company_count is not None and company_count < minimum_company_breadth:
        return ScoreBreakdown(
            score=None, status="data_insufficient", components=components, weights=weights,
            missing_component_count=len(missing),
            extra={"company_count": company_count,
                   "minimum_company_breadth": minimum_company_breadth},
            score_version=score_version,
        )
    if missing:
        return ScoreBreakdown(score=None, status="data_insufficient", components=components,
                              weights=weights, missing_component_count=len(missing),
                              score_version=score_version)

    total = sum(_clamp01(components[k]) * weights[k] for k in required)
    breakdown = {k: {"raw": round(_clamp01(components[k]), 4), "weight": weights[k],
                     "weighted": round(_clamp01(components[k]) * weights[k], 4)}
                 for k in required}
    return ScoreBreakdown(score=round(total, 2), components=breakdown, weights=weights,
                          extra={"company_count": company_count}, score_version=score_version)


# ------------------- Incremental Information Score (§4) --------------------

def incremental_information_score(components: dict, *, weights: dict | None = None,
                                  score_version: str = "s1") -> ScoreBreakdown:
    """Experimental incremental-info value of a company (spec §4).

    ``components`` each 0..1. Weights may be negative (e.g. redundancy). Result
    clamped to 0..100 and always flagged Experimental.
    """
    weights = weights or config.incremental_score_weights()
    present = {k: v for k, v in components.items() if v is not None}
    total = sum(_clamp01(present[k]) * weights.get(k, 0) for k in present)
    total = max(0.0, min(100.0, total))
    return ScoreBreakdown(score=round(total, 2), components=components, weights=weights,
                          score_version=score_version, is_experimental=True)
