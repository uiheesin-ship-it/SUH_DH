"""Pydantic v2 schemas for LLM structured output (spec §11, §15).

These are the *contracts* the LLM must satisfy at each stage. They are used
three ways:
  1. As the JSON Schema handed to the provider's structured-output / tool API.
  2. As the validator for the returned JSON (Pydantic → enum/range → evidence).
  3. As the shape persisted (raw) into ``chunk_analysis`` etc.

The LLM never emits final Theme/Incremental scores — those are computed in
code (spec §1-5, §14). It only emits the *raw* components below.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import (
    Direction,
    NarrativeConfirmationStatus,
    SectionType,
    SpeakerRole,
)


class Evidence(BaseModel):
    """A single citation. Verified in code against the paragraph text (spec §16)."""

    paragraph_id: str
    exact_quote_en: str = Field(min_length=1)
    translation_ko: str | None = None
    speaker_name: str | None = None
    speaker_role: SpeakerRole | None = None
    section_type: SectionType | None = None
    evidence_reason: str | None = None


# --------------------------- Stage 1: chunk extraction ----------------------

class TopicMention(BaseModel):
    company: str
    ticker: str
    fiscal_year: int
    fiscal_quarter: int = Field(ge=1, le=4)
    call_date: str | None = None
    section_type: SectionType
    speaker_name: str | None = None
    speaker_role: SpeakerRole | None = None

    topic_id: str
    topic_name_en: str
    topic_name_ko: str
    topic_category: str

    direction: Direction
    intensity: int = Field(ge=0, le=5)
    confidence: float = Field(ge=0.0, le=1.0)

    management_initiated: bool
    analyst_initiated: bool
    forward_looking: bool = False
    backward_looking: bool = False
    numeric_support: bool = False
    guidance_related: bool = False
    demand_related: bool = False
    pricing_related: bool = False
    capex_related: bool = False
    inventory_related: bool = False
    employment_related: bool = False
    risk_related: bool = False

    summary_ko: str
    evidence: list[Evidence] = Field(default_factory=list)
    insufficient_evidence: bool = False


class ChunkExtraction(BaseModel):
    """Stage-1 output for one chunk: zero or more topic mentions."""

    mentions: list[TopicMention] = Field(default_factory=list)


# --------------------------- Stage 2: call synthesis ------------------------

class CallSynthesis(BaseModel):
    executive_summary_ko: str
    key_topics: list[str] = Field(default_factory=list)
    management_priorities: list[str] = Field(default_factory=list)
    demand_signals: list[str] = Field(default_factory=list)
    pricing_signals: list[str] = Field(default_factory=list)
    capex_signals: list[str] = Field(default_factory=list)
    inventory_signals: list[str] = Field(default_factory=list)
    labor_signals: list[str] = Field(default_factory=list)
    guidance_signals: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    analyst_concerns: list[str] = Field(default_factory=list)
    evasive_or_weak_answers: list[str] = Field(default_factory=list)
    prepared_vs_qa_gap: str | None = None
    narrative_vs_numbers_gap: str | None = None
    key_quotes: list[Evidence] = Field(default_factory=list)


# --------------------------- Stage 3: QoQ comparison ------------------------

class QoQComparison(BaseModel):
    newly_emerging_topics: list[str] = Field(default_factory=list)
    accelerating_topics: list[str] = Field(default_factory=list)
    persistent_topics: list[str] = Field(default_factory=list)
    weakening_topics: list[str] = Field(default_factory=list)
    disappeared_topics: list[str] = Field(default_factory=list)
    tone_changes: str | None = None
    guidance_changes: str | None = None
    analyst_question_changes: str | None = None
    management_emphasis_changes: str | None = None
    narrative_vs_numbers_gap_changes: str | None = None
    unresolved_concerns: list[str] = Field(default_factory=list)
    key_kpi_changes: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


# --------------------------- Stage 4: cross-company theme -------------------

class CrossCompanyThemeLLM(BaseModel):
    """LLM-emitted *qualitative* part of a theme. Numeric scores come from code."""

    theme_id: str
    theme_name_en: str
    theme_name_ko: str
    theme_description_ko: str
    value_chain_positions: list[str] = Field(default_factory=list)
    direction: Direction
    leading_indicators: list[str] = Field(default_factory=list)
    lagging_indicators: list[str] = Field(default_factory=list)
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    contradictory_evidence: list[Evidence] = Field(default_factory=list)


class CrossCompanyThemeSet(BaseModel):
    themes: list[CrossCompanyThemeLLM] = Field(default_factory=list)


# --------------------------- Stage 5: investment theme ----------------------

class InvestmentThemeLLM(BaseModel):
    investment_theme: str
    why_it_is_emerging: str
    companies_supporting: list[str] = Field(default_factory=list)
    sectors_supporting: list[str] = Field(default_factory=list)
    value_chain_transmission: str | None = None
    direct_beneficiaries: list[str] = Field(default_factory=list)
    secondary_beneficiaries: list[str] = Field(default_factory=list)
    potential_losers: list[str] = Field(default_factory=list)
    management_evidence: list[Evidence] = Field(default_factory=list)
    numeric_evidence: list[Evidence] = Field(default_factory=list)
    contradictory_evidence: list[Evidence] = Field(default_factory=list)
    unconfirmed_assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    indicators_to_monitor: list[str] = Field(default_factory=list)
    next_quarter_checkpoints: list[str] = Field(default_factory=list)
    # conviction & narrative_confirmation_status are DECIDED IN CODE for the MVP
    # (spec §11-6): the LLM may *suggest* status but code caps conviction.
    suggested_narrative_confirmation_status: NarrativeConfirmationStatus | None = None
