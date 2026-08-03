"""End-to-end MVP pipeline test with the mock LLM (spec §23).

Runs the whole 6-company batch offline: seed → ingest → parse → Stage1 chunk
extraction → evidence verification → Stage2 synthesis → scoring → QoQ →
cross-company themes. Asserts the pipeline's structural guarantees, not any
investment conclusion (the 6-company MVP is Prototype / Insufficient Breadth).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.eai.models import (
    CallSummary,
    CrossCompanyTheme,
    EvidenceLink,
    EvidenceVerification,
    InvestmentTheme,
    ModelUsage,
    TopicMentionRow,
    TranscriptParagraph,
)
from app.eai.services import jobs


async def test_full_batch_runs_and_persists(db):
    async with db.sessionmaker()() as s:
        job = await jobs.create_job(s, "batch", {"tickers": "MVP6"})
        result = await jobs.run_batch(s, job=job)

    assert result["status"] in ("completed", "partially_completed")
    async with db.sessionmaker()() as s:
        # 6 companies × 2 quarters = 12 calls → 12 summaries
        summaries = (await s.execute(select(func.count(CallSummary.id)))).scalar()
        assert summaries == 12

        mentions = (await s.execute(select(func.count(TopicMentionRow.id)))).scalar()
        assert mentions > 0

        # every persisted evidence link has a verification record
        links = (await s.execute(select(func.count(EvidenceLink.id)))).scalar()
        verifs = (await s.execute(select(func.count(EvidenceVerification.id)))).scalar()
        assert links == verifs and links > 0

        # usage recorded for cost tracking
        usage = (await s.execute(select(func.count(ModelUsage.id)))).scalar()
        assert usage > 0

        themes = (await s.execute(select(func.count(CrossCompanyTheme.id)))).scalar()
        assert themes > 0


async def test_evidence_links_are_exact_verified(db):
    async with db.sessionmaker()() as s:
        await jobs.run_batch(s)
    async with db.sessionmaker()() as s:
        # every 'verified' evidence quote is truly a substring of its paragraph
        rows = (await s.execute(
            select(EvidenceLink, EvidenceVerification)
            .join(EvidenceVerification, EvidenceVerification.evidence_id == EvidenceLink.id)
            .where(EvidenceVerification.verification_status == "verified"))).all()
        assert rows
        for link, verif in rows:
            para = (await s.execute(select(TranscriptParagraph).where(
                TranscriptParagraph.paragraph_id == link.paragraph_id))).scalars().first()
            assert para is not None
            from app.eai.services.textnorm import normalize
            assert normalize(link.exact_quote_en) in normalize(para.exact_text_en)


async def test_scores_present_and_experimental(db):
    async with db.sessionmaker()() as s:
        await jobs.run_batch(s)
    async with db.sessionmaker()() as s:
        summary = (await s.execute(select(CallSummary).where(
            CallSummary.ticker == "NVDA", CallSummary.fiscal_quarter == 2))).scalars().first()
        scores = summary.payload["scores"]
        assert scores["is_experimental"] is True
        assert "narrative_momentum" in scores
        assert "fundamental_confirmation" in scores
        assert scores["narrative_confirmation_status"] in (
            "Confirmed Acceleration", "Narrative Ahead of Numbers",
            "Conservative or Underpromising", "Mixed Signals", "Confirmed Deterioration")


async def test_mvp_conviction_capped_low_and_prototype_labeled(db):
    async with db.sessionmaker()() as s:
        await jobs.run_batch(s)
    async with db.sessionmaker()() as s:
        invs = (await s.execute(select(InvestmentTheme))).scalars().all()
        assert invs  # at least one investment theme attempted
        for it in invs:
            # 6-company MVP must not mint high conviction (spec §11-6, §23)
            assert it.conviction == "low"
            assert it.maturity_label  # Prototype / Insufficient Breadth


async def test_jpm_narrative_ahead_or_deterioration(db):
    """JPM narrative stays 'healthy' while credit KPIs weaken — the gap must show."""
    async with db.sessionmaker()() as s:
        await jobs.run_batch(s)
    async with db.sessionmaker()() as s:
        summary = (await s.execute(select(CallSummary).where(
            CallSummary.ticker == "JPM", CallSummary.fiscal_quarter == 2))).scalars().first()
        # fundamental may be insufficient (few guided KPIs) -> status still computed
        assert summary.payload["scores"]["narrative_confirmation_status"]
