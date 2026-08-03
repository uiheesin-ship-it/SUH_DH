"""Ingest a RawTranscript into the DB: dedup, versioning, paragraph structuring.

Dedup is by checksum (spec §6.1): re-ingesting identical content is a no-op;
changed content creates a NEW version (so only changed parts get re-analyzed
later). Also stores financial KPIs/guidance from the financial provider.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Company,
    GuidanceMetric,
    FinancialMetric,
    Speaker,
    TranscriptDocument,
    TranscriptParagraph,
    TranscriptVersion,
)
from ..providers.transcript.base import RawTranscript
from . import preprocess


def _parse(raw: RawTranscript) -> preprocess.ParsedTranscript:
    if raw.structured:
        payload = {
            "ticker": raw.ticker, "fiscal_year": raw.fiscal_year,
            "fiscal_quarter": raw.fiscal_quarter, "call_date": raw.call_date,
            "sections": raw.structured["sections"],
        }
        return preprocess.parse_structured(payload)
    if raw.raw_text is not None:
        return preprocess.parse_plaintext(
            raw.raw_text, raw.ticker, raw.fiscal_year, raw.fiscal_quarter, raw.call_date)
    raise ValueError("RawTranscript has neither structured nor raw_text")


async def ingest_transcript(session: AsyncSession, company: Company,
                            raw: RawTranscript) -> tuple[TranscriptVersion, bool]:
    """Return (version, created). created=False if the checksum already exists."""
    checksum = raw.checksum()

    doc = (await session.execute(select(TranscriptDocument).where(
        TranscriptDocument.company_id == company.id,
        TranscriptDocument.fiscal_year == raw.fiscal_year,
        TranscriptDocument.fiscal_quarter == raw.fiscal_quarter,
    ))).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    published = _parse_dt(raw.published_at) or _parse_dt(raw.call_date)
    if doc is None:
        doc = TranscriptDocument(
            company_id=company.id, ticker=company.ticker, fiscal_year=raw.fiscal_year,
            fiscal_quarter=raw.fiscal_quarter, call_date=raw.call_date, language=raw.language,
            published_at=published, retrieved_at=now,
            # analysis_as_of defaults to publication time so cross-company work
            # can't use anything disclosed later (spec §5).
            analysis_as_of=published or now,
        )
        session.add(doc)
        await session.flush()

    # dedup: same checksum already stored?
    existing = (await session.execute(select(TranscriptVersion).where(
        TranscriptVersion.transcript_id == doc.id,
        TranscriptVersion.checksum == checksum))).scalar_one_or_none()
    if existing is not None:
        return existing, False

    version_no = 1 + len((await session.execute(select(TranscriptVersion).where(
        TranscriptVersion.transcript_id == doc.id))).scalars().all())
    version = TranscriptVersion(transcript_id=doc.id, version_no=version_no, checksum=checksum)
    session.add(version)
    await session.flush()
    doc.current_version_id = version.id

    parsed = _parse(raw)
    for sp in parsed.speakers:
        session.add(Speaker(transcript_version_id=version.id, name=sp["name"],
                            role=sp["role"], company=sp.get("company")))
    for p in parsed.paragraphs:
        session.add(TranscriptParagraph(
            transcript_version_id=version.id, paragraph_id=p.paragraph_id,
            section_type=p.section_type, speaker_name=p.speaker_name,
            speaker_role=p.speaker_role, speaker_company=p.speaker_company,
            sequence_number=p.sequence_number, exact_text_en=p.exact_text_en,
            normalized_text_en=p.normalized_text_en,
            preceding_question_id=p.preceding_question_id,
            answer_to_question_id=p.answer_to_question_id, paragraph_hash=p.paragraph_hash))
    await session.commit()
    return version, True


async def store_financials(session: AsyncSession, company: Company, kpis, guidance) -> int:
    """Persist verified KPIs & guidance for a company. Returns rows written."""
    n = 0
    for k in kpis:
        session.add(FinancialMetric(
            company_id=company.id, ticker=company.ticker, fiscal_period=k.fiscal_period,
            metric_id=k.metric_id, metric_name=k.metric_name, value=k.value, unit=k.unit,
            currency=k.currency, gaap_or_non_gaap=k.gaap_or_non_gaap,
            actual_or_guidance=k.actual_or_guidance, comparison_basis=k.comparison_basis,
            source_page=k.source_page, source_paragraph_id=k.source_paragraph_id,
            published_at=_parse_dt(k.published_at), confidence=k.confidence,
            verification_status=k.verification_status))
        n += 1
    for g in guidance:
        session.add(GuidanceMetric(
            company_id=company.id, ticker=company.ticker, fiscal_period=g.fiscal_period,
            metric=g.metric, unit=g.unit, guidance_mid=g.guidance_mid, guidance_low=g.guidance_low,
            guidance_high=g.guidance_high, consensus=g.consensus, note=g.note, sources=g.sources,
            published_at=_parse_dt(g.published_at), verification_status=g.verification_status))
        n += 1
    await session.commit()
    return n


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None
