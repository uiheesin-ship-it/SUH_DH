"""Financial data provider abstraction (spec §6.2).

Fundamental Confirmation must use official, verified numbers — NOT figures the
LLM pulled from the transcript (spec §6.2, §13). When a transcript-extracted
KPI conflicts with the official source, the official one wins and the delta is
flagged. The MVP ships a curated-JSON provider (reusing the repo's existing
data/guidance.json convention) plus manual upload.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerifiedKPI:
    ticker: str
    fiscal_period: str
    metric_id: str
    metric_name: str
    value: float | None = None
    unit: str | None = None
    currency: str | None = None
    gaap_or_non_gaap: str | None = None
    actual_or_guidance: str = "actual"
    yoy_growth: float | None = None
    comparison_basis: str | None = None
    source_page: str | None = None
    source_paragraph_id: str | None = None
    published_at: str | None = None
    confidence: float = 1.0
    verification_status: str = "verified"


@dataclass
class GuidanceMetricDTO:
    ticker: str
    fiscal_period: str
    metric: str
    unit: str | None = None
    guidance_mid: float | None = None
    guidance_low: float | None = None
    guidance_high: float | None = None
    consensus: float | None = None
    note: str | None = None
    sources: list = field(default_factory=list)
    published_at: str | None = None
    verification_status: str = "verified"
