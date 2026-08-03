"""SQLAlchemy models for the eai subsystem (spec §20).

Faithful to the spec's table list; columns are focused on what the 6-company
MVP pipeline reads/writes, with JSON columns for the richer LLM payloads so the
schema stays stable while prompts evolve. Raw LLM output is always kept
alongside derived fields for reproducibility (spec §20).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# =========================== Universe / companies ===========================

class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    cik: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str] = mapped_column(String(8), default="US")
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    universe_types: Mapped[list["CompanyUniverseType"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    signal_roles: Mapped[list["CompanySignalRole"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    value_chain_positions: Mapped[list["CompanyValueChainPosition"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class CompanyUniverseType(Base):
    __tablename__ = "company_universe_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    universe_type: Mapped[str] = mapped_column(String(16))  # core|specialist|dynamic
    tracked_quarters: Mapped[int] = mapped_column(Integer, default=2)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    company: Mapped[Company] = relationship(back_populates="universe_types")


class CompanySignalRole(Base):
    __tablename__ = "company_signal_roles"
    __table_args__ = (UniqueConstraint("company_id", "role", name="uq_company_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    role: Mapped[str] = mapped_column(String(48))

    company: Mapped[Company] = relationship(back_populates="signal_roles")


class CompanyValueChainPosition(Base):
    __tablename__ = "company_value_chain_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    position: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship(back_populates="value_chain_positions")


class UniverseChangeHistory(Base):
    __tablename__ = "universe_change_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(24))  # add|remove|promote|demote
    reason: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[str] = mapped_column(String(32), default="system")
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IncrementalInformationScore(Base):
    __tablename__ = "incremental_information_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    components: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_version: Mapped[str] = mapped_column(String(16))
    is_experimental: Mapped[bool] = mapped_column(Boolean, default=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# =========================== Documents / transcripts ========================

class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    doc_type: Mapped[str] = mapped_column(String(32))  # transcript|earnings_release|10q|...
    source: Mapped[str] = mapped_column(String(64))
    source_identifier: Mapped[str | None] = mapped_column(String(256))
    source_url: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    license_note: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TranscriptDocument(TimestampMixin, Base):
    __tablename__ = "transcript_documents"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", "fiscal_quarter", name="uq_transcript_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_quarter: Mapped[int] = mapped_column(Integer)
    calendar_year: Mapped[int | None] = mapped_column(Integer)
    calendar_quarter: Mapped[int | None] = mapped_column(Integer)
    call_date: Mapped[str | None] = mapped_column(String(32))
    event_date: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(8), default="en")
    is_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer)
    # Point-in-time bookkeeping (spec §5) — prevents look-ahead in cross-company.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list["TranscriptVersion"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )


class TranscriptVersion(Base):
    __tablename__ = "transcript_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcript_documents.id"))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    raw_storage_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    transcript: Mapped[TranscriptDocument] = relationship(back_populates="versions")
    paragraphs: Mapped[list["TranscriptParagraph"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    speakers: Mapped[list["Speaker"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class Speaker(Base):
    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_version_id: Mapped[int] = mapped_column(ForeignKey("transcript_versions.id"))
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(24))  # operator|ceo|cfo|other_management|analyst
    company: Mapped[str | None] = mapped_column(String(128))

    version: Mapped[TranscriptVersion] = relationship(back_populates="speakers")


class TranscriptParagraph(Base):
    __tablename__ = "transcript_paragraphs"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_version_id: Mapped[int] = mapped_column(ForeignKey("transcript_versions.id"))
    paragraph_id: Mapped[str] = mapped_column(String(64), index=True)  # NVDA_2026Q2_QA_CFO_015
    section_type: Mapped[str] = mapped_column(String(24))
    speaker_name: Mapped[str | None] = mapped_column(String(128))
    speaker_role: Mapped[str | None] = mapped_column(String(24))
    speaker_company: Mapped[str | None] = mapped_column(String(128))
    sequence_number: Mapped[int] = mapped_column(Integer)
    exact_text_en: Mapped[str] = mapped_column(Text)
    normalized_text_en: Mapped[str] = mapped_column(Text)
    preceding_question_id: Mapped[str | None] = mapped_column(String(64))
    answer_to_question_id: Mapped[str | None] = mapped_column(String(64))
    paragraph_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Optional cached Korean translation (filled by a translate step when an LLM
    # is available; null until then — the UI shows the English original).
    translation_ko: Mapped[str | None] = mapped_column(Text)

    version: Mapped[TranscriptVersion] = relationship(back_populates="paragraphs")


# =========================== Financials =====================================

class FinancialMetric(Base):
    __tablename__ = "financial_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_period: Mapped[str] = mapped_column(String(16))  # e.g. FY2026Q2
    metric_id: Mapped[str] = mapped_column(String(64))
    metric_name: Mapped[str] = mapped_column(String(128))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str | None] = mapped_column(String(8))
    gaap_or_non_gaap: Mapped[str | None] = mapped_column(String(16))
    actual_or_guidance: Mapped[str] = mapped_column(String(16), default="actual")
    period_start: Mapped[str | None] = mapped_column(String(32))
    period_end: Mapped[str | None] = mapped_column(String(32))
    comparison_basis: Mapped[str | None] = mapped_column(String(32))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    source_page: Mapped[str | None] = mapped_column(String(32))
    source_paragraph_id: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")


class GuidanceMetric(Base):
    __tablename__ = "guidance_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_period: Mapped[str] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(32))  # revenue|eps|gross_margin
    unit: Mapped[str | None] = mapped_column(String(16))
    guidance_mid: Mapped[float | None] = mapped_column(Float)
    guidance_low: Mapped[float | None] = mapped_column(Float)
    guidance_high: Mapped[float | None] = mapped_column(Float)
    consensus: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(24), default="verified")


# =========================== Jobs / analysis ================================

class AnalysisJob(TimestampMixin, Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))  # ingest|analyze_call|batch|cross_company
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    resumable: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


class ChunkAnalysis(Base):
    __tablename__ = "chunk_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_jobs.id"))
    transcript_version_id: Mapped[int] = mapped_column(ForeignKey("transcript_versions.id"))
    chunk_ref: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    raw_llm_output: Mapped[dict | None] = mapped_column(JSON)
    model_id: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    ontology_version: Mapped[str | None] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TopicMentionRow(Base):
    __tablename__ = "topic_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    transcript_version_id: Mapped[int] = mapped_column(ForeignKey("transcript_versions.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_quarter: Mapped[int] = mapped_column(Integer)
    section_type: Mapped[str] = mapped_column(String(24))
    speaker_role: Mapped[str | None] = mapped_column(String(24))
    topic_id: Mapped[str] = mapped_column(String(64), index=True)
    topic_category: Mapped[str | None] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16))
    intensity: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    management_initiated: Mapped[bool] = mapped_column(Boolean, default=False)
    analyst_initiated: Mapped[bool] = mapped_column(Boolean, default=False)
    numeric_support: Mapped[bool] = mapped_column(Boolean, default=False)
    guidance_related: Mapped[bool] = mapped_column(Boolean, default=False)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # full TopicMention
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)


class CallSummary(Base):
    __tablename__ = "call_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    transcript_version_id: Mapped[int] = mapped_column(ForeignKey("transcript_versions.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_quarter: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # CallSynthesis
    model_id: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class QuarterlyComparison(Base):
    __tablename__ = "quarterly_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    from_period: Mapped[str] = mapped_column(String(16))
    to_period: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # QoQComparison
    model_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CrossCompanyTheme(Base):
    __tablename__ = "cross_company_themes"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_id: Mapped[str] = mapped_column(String(64), index=True)
    theme_name_en: Mapped[str] = mapped_column(String(256))
    theme_name_ko: Mapped[str] = mapped_column(String(256))
    analysis_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    theme_score: Mapped[float | None] = mapped_column(Float)
    score_status: Mapped[str] = mapped_column(String(32), default="ok")  # ok|data_insufficient
    is_experimental: Mapped[bool] = mapped_column(Boolean, default=True)
    maturity_label: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # full theme incl. metrics
    score_version: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    components: Mapped[list["ThemeComponent"]] = relationship(
        back_populates="theme", cascade="all, delete-orphan"
    )


class ThemeComponent(Base):
    __tablename__ = "theme_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_row_id: Mapped[int] = mapped_column(ForeignKey("cross_company_themes.id"))
    name: Mapped[str] = mapped_column(String(64))  # breadth|momentum|...
    raw_value: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)
    weighted: Mapped[float | None] = mapped_column(Float)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)

    theme: Mapped[CrossCompanyTheme] = relationship(back_populates="components")


class InvestmentTheme(Base):
    __tablename__ = "investment_themes"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_row_id: Mapped[int | None] = mapped_column(ForeignKey("cross_company_themes.id"))
    investment_theme: Mapped[str] = mapped_column(String(256))
    conviction: Mapped[str] = mapped_column(String(16), default="low")
    narrative_confirmation_status: Mapped[str | None] = mapped_column(String(48))
    is_experimental: Mapped[bool] = mapped_column(Boolean, default=True)
    maturity_label: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# =========================== Evidence =======================================

class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_type: Mapped[str] = mapped_column(String(48))  # topic_mention|theme|investment_theme
    claim_id: Mapped[int] = mapped_column(Integer, index=True)
    paragraph_id: Mapped[str] = mapped_column(String(64), index=True)
    exact_quote_en: Mapped[str] = mapped_column(Text)
    translation_ko: Mapped[str | None] = mapped_column(Text)
    quote_start_offset: Mapped[int | None] = mapped_column(Integer)
    quote_end_offset: Mapped[int | None] = mapped_column(Integer)
    paragraph_hash: Mapped[str | None] = mapped_column(String(64))
    evidence_reason: Mapped[str | None] = mapped_column(Text)

    verification: Mapped["EvidenceVerification | None"] = relationship(
        back_populates="evidence", uselist=False, cascade="all, delete-orphan"
    )


class EvidenceVerification(Base):
    __tablename__ = "evidence_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence_links.id"))
    verification_method: Mapped[str] = mapped_column(String(24))
    verification_status: Mapped[str] = mapped_column(String(24))
    numeric_check: Mapped[dict | None] = mapped_column(JSON)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    evidence: Mapped[EvidenceLink] = relationship(back_populates="verification")


# =========================== Versions / audit / cost ========================

class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    ontology_version: Mapped[str] = mapped_column(String(16), index=True)
    topic_id: Mapped[str] = mapped_column(String(64), index=True)
    name_en: Mapped[str] = mapped_column(String(128))
    name_ko: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="active")  # active|new_topic_candidate


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(16), unique=True)
    stage: Mapped[str | None] = mapped_column(String(24))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OntologyVersion(Base):
    __tablename__ = "ontology_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(16), unique=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ScoreVersion(Base):
    __tablename__ = "score_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(16), unique=True)
    classification_rule_version: Mapped[str | None] = mapped_column(String(16))
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserCorrection(Base):
    __tablename__ = "user_corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(48))
    target_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(48))
    original_value: Mapped[dict | None] = mapped_column(JSON)
    corrected_value: Mapped[dict | None] = mapped_column(JSON)
    corrected_by: Mapped[str] = mapped_column(String(64))
    correction_reason: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    ontology_version: Mapped[str | None] = mapped_column(String(16))
    model_id: Mapped[str | None] = mapped_column(String(64))
    corrected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelUsage(Base):
    __tablename__ = "model_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str | None] = mapped_column(String(24))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    ontology_version: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    processing_time: Mapped[float] = mapped_column(Float, default=0.0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProviderError(Base):
    __tablename__ = "provider_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    error_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), default="default")
    name: Mapped[str] = mapped_column(String(128))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
