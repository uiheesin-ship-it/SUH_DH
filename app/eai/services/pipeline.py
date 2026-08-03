"""LLM analysis pipeline, Stage 1–5 (spec §11).

Never one giant request: each stage is a separate, validated LLM call. Code —
not the LLM — verifies evidence and computes every score. A failed chunk does
not abort the call; the job becomes partially_completed and the rest proceeds
(spec §2, §23).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from ..models import (
    CallSummary,
    ChunkAnalysis,
    Company,
    CrossCompanyTheme,
    EvidenceLink,
    EvidenceVerification,
    InvestmentTheme,
    ModelUsage,
    QuarterlyComparison,
    ThemeComponent,
    TopicMentionRow,
    TranscriptDocument,
    TranscriptParagraph,
    TranscriptVersion,
)
from ..providers.financial import get_financial_provider
from ..providers.llm import get_llm_provider
from ..schemas.llm_io import (
    ChunkExtraction,
    CallSynthesis,
    CrossCompanyThemeSet,
    InvestmentThemeLLM,
    QoQComparison,
)
from . import evidence as ev
from . import preprocess, scoring
from .llm_runner import run_stage


def fiscal_period(fy: int, fq: int) -> str:
    return f"FY{fy}Q{fq}"


async def _paragraph_rows(session: AsyncSession, version_id: int) -> list[TranscriptParagraph]:
    return list((await session.execute(select(TranscriptParagraph).where(
        TranscriptParagraph.transcript_version_id == version_id
    ).order_by(TranscriptParagraph.sequence_number))).scalars())


def _rows_to_parsed(rows: list[TranscriptParagraph], ticker: str, fy: int, fq: int,
                    call_date):
    parsed = preprocess.ParsedTranscript(ticker, fy, fq, call_date)
    for r in rows:
        parsed.paragraphs.append(preprocess.ParsedParagraph(
            paragraph_id=r.paragraph_id, section_type=r.section_type,
            speaker_name=r.speaker_name, speaker_role=r.speaker_role,
            speaker_company=r.speaker_company, sequence_number=r.sequence_number,
            exact_text_en=r.exact_text_en, normalized_text_en=r.normalized_text_en,
            preceding_question_id=r.preceding_question_id,
            answer_to_question_id=r.answer_to_question_id, paragraph_hash=r.paragraph_hash))
    return parsed


def _record_usage(session: AsyncSession, usages: list[dict]) -> None:
    for u in usages:
        session.add(ModelUsage(**u))


async def analyze_call(session: AsyncSession, company: Company, version: TranscriptVersion,
                       *, job=None) -> dict:
    """Run Stage 1 (chunk) + Stage 2 (synthesis) + code scoring for one call."""
    provider = get_llm_provider()
    doc = (await session.execute(select(TranscriptDocument).where(
        TranscriptDocument.id == version.transcript_id))).scalar_one()
    fy, fq = doc.fiscal_year, doc.fiscal_quarter
    doc.analysis_started_at = datetime.now(timezone.utc)

    rows = await _paragraph_rows(session, version.id)
    parsed = _rows_to_parsed(rows, company.ticker, fy, fq, doc.call_date)
    index = ev.build_index(rows)
    chunks = preprocess.build_chunks(parsed)
    meta = {"company": company.name, "ticker": company.ticker, "fiscal_year": fy,
            "fiscal_quarter": fq, "call_date": doc.call_date}

    para_by_id = {r.paragraph_id: r for r in rows}
    all_mentions: list[dict] = []
    chunk_failures = 0

    for chunk in chunks:
        payload_paras = [{
            "paragraph_id": pid,
            "text": para_by_id[pid].exact_text_en,
            "speaker_role": para_by_id[pid].speaker_role,
            "speaker_name": para_by_id[pid].speaker_name,
            "section_type": para_by_id[pid].section_type,
        } for pid in chunk.paragraph_ids if pid in para_by_id]

        from ..prompts import chunk_extraction
        system, user = chunk_extraction(meta, payload_paras)
        outcome = run_stage(provider, "fast", system, user, ChunkExtraction, stage="stage1")
        _record_usage(session, outcome.usage)

        ca = ChunkAnalysis(
            transcript_version_id=version.id, chunk_ref=chunk.chunk_ref,
            status=outcome.status, prompt_version=config.versions()["prompt_version"],
            ontology_version=config.versions()["ontology_version"],
            model_id=outcome.usage[-1]["model_id"] if outcome.usage else None,
            raw_llm_output=outcome.model.model_dump() if outcome.model else None,
            error=outcome.error)
        if job is not None:
            ca.job_id = job.id
        session.add(ca)

        if outcome.status == "unavailable":
            # No usable LLM — stop and surface (spec §8).
            await session.commit()
            return {"status": "llm_unavailable",
                    "message": "LLM analysis unavailable", "mentions": 0}
        if outcome.model is None:
            chunk_failures += 1
            continue

        for m in outcome.model.mentions:
            persisted = await _persist_mention(session, company, version, fy, fq, m, index)
            all_mentions.append(persisted)

    # ---- Stage 2: call synthesis ----
    from ..prompts import call_synthesis
    system, user = call_synthesis(meta, all_mentions)
    syn = run_stage(provider, "balanced", system, user, CallSynthesis, stage="stage2")
    _record_usage(session, syn.usage)

    scores = await _score_call(session, company, fy, fq, all_mentions)

    summary_payload = syn.model.model_dump() if syn.model else {"status": syn.status}
    summary_payload["scores"] = scores
    cs = CallSummary(company_id=company.id, transcript_version_id=version.id,
                     ticker=company.ticker, fiscal_year=fy, fiscal_quarter=fq,
                     payload=summary_payload,
                     model_id=syn.usage[-1]["model_id"] if syn.usage else None,
                     prompt_version=config.versions()["prompt_version"])
    session.add(cs)

    doc.analysis_completed_at = datetime.now(timezone.utc)
    await session.commit()

    status = "partially_completed" if chunk_failures else "completed"
    return {"status": status, "mentions": len(all_mentions),
            "chunk_failures": chunk_failures, "scores": scores}


async def _persist_mention(session, company, version, fy, fq, mention, index) -> dict:
    """Verify evidence, persist the mention + verified/flagged evidence links."""
    data = mention.model_dump()
    ev_items = [{"paragraph_id": e.get("paragraph_id"),
                 "exact_quote_en": e.get("exact_quote_en", "")} for e in data.get("evidence", [])]
    cv = ev.verify_claim(ev_items, index)
    has_verified = cv.has_verified_evidence
    insufficient = data.get("insufficient_evidence", False) or not has_verified

    row = TopicMentionRow(
        company_id=company.id, transcript_version_id=version.id, ticker=company.ticker,
        fiscal_year=fy, fiscal_quarter=fq, section_type=data["section_type"],
        speaker_role=data.get("speaker_role"), topic_id=data["topic_id"],
        topic_category=data.get("topic_category"), direction=data["direction"],
        intensity=data["intensity"], confidence=data["confidence"],
        management_initiated=data.get("management_initiated", False),
        analyst_initiated=data.get("analyst_initiated", False),
        numeric_support=data.get("numeric_support", False),
        guidance_related=data.get("guidance_related", False),
        insufficient_evidence=insufficient, payload=data, is_verified=has_verified)
    session.add(row)
    await session.flush()

    for res in cv.verified + cv.review:
        link = EvidenceLink(
            claim_type="topic_mention", claim_id=row.id, paragraph_id=res.paragraph_id,
            exact_quote_en=next((e["exact_quote_en"] for e in ev_items
                                 if e["paragraph_id"] == res.paragraph_id), ""),
            quote_start_offset=res.quote_start_offset, quote_end_offset=res.quote_end_offset,
            paragraph_hash=res.paragraph_hash, evidence_reason=res.reason)
        session.add(link)
        await session.flush()
        session.add(EvidenceVerification(
            evidence_id=link.id, verification_method=res.method,
            verification_status=res.status, numeric_check=res.numeric_check))

    data["_verified_evidence_count"] = cv.verified_count
    data["is_verified"] = has_verified
    return data


async def _score_call(session, company, fy, fq, mentions) -> dict:
    """Compute Narrative Momentum & Fundamental Confirmation separately (spec §13)."""
    cls = config.classification()
    sv = config.versions()["score_version"]

    # Only verified mentions feed the narrative score.
    verified_mentions = [m for m in mentions if m.get("is_verified")]
    narrative = scoring.narrative_momentum(verified_mentions, score_version=sv)

    fin = get_financial_provider()
    period = fiscal_period(fy, fq)
    kpis = [k.__dict__ for k in fin.fetch_kpis(company.ticker, period)]
    guidance = [g.__dict__ for g in fin.fetch_guidance(company.ticker, period)]
    fundamental = scoring.fundamental_confirmation(
        kpis, guidance, minimum_verified_kpi_count=cls["minimum_verified_kpi_count"],
        score_version=sv)

    classification = scoring.classify(
        narrative, fundamental, narrative_threshold=cls["narrative_threshold"],
        fundamental_threshold=cls["fundamental_threshold"])

    return {
        "narrative_momentum": _bd(narrative),
        "fundamental_confirmation": _bd(fundamental),
        "narrative_confirmation_status": classification["status"],
        "classification": classification,
        "score_version": sv,
        "classification_rule_version": cls["classification_rule_version"],
        "is_experimental": True,
        "verified_kpi_count": len([k for k in kpis if k.get("verification_status") == "verified"]),
    }


def _bd(b: scoring.ScoreBreakdown) -> dict:
    return {"score": b.score, "components": b.components, "weights": b.weights,
            "missing_component_count": b.missing_component_count, "status": b.status,
            "is_experimental": b.is_experimental, "extra": b.extra}


# ------------------------------ Stage 3: QoQ --------------------------------

async def compare_quarters(session: AsyncSession, company: Company) -> dict | None:
    """Compare the two most recent analyzed quarters (spec §11 Stage 3)."""
    docs = list((await session.execute(select(TranscriptDocument).where(
        TranscriptDocument.company_id == company.id
    ).order_by(TranscriptDocument.fiscal_year.desc(),
               TranscriptDocument.fiscal_quarter.desc()))).scalars())
    if len(docs) < 2:
        return None
    cur_doc, prev_doc = docs[0], docs[1]

    cur = await _mentions_for(session, company.id, cur_doc.fiscal_year, cur_doc.fiscal_quarter)
    prev = await _mentions_for(session, company.id, prev_doc.fiscal_year, prev_doc.fiscal_quarter)

    provider = get_llm_provider()
    meta = {"ticker": company.ticker,
            "current": fiscal_period(cur_doc.fiscal_year, cur_doc.fiscal_quarter),
            "previous": fiscal_period(prev_doc.fiscal_year, prev_doc.fiscal_quarter)}
    from ..prompts import qoq_comparison
    system, user = qoq_comparison(meta, cur, prev)
    outcome = run_stage(provider, "balanced", system, user, QoQComparison, stage="stage3")
    _record_usage(session, outcome.usage)
    if outcome.model is None:
        await session.commit()
        return {"status": outcome.status}

    qc = QuarterlyComparison(
        company_id=company.id, ticker=company.ticker, from_period=meta["previous"],
        to_period=meta["current"], payload=outcome.model.model_dump(),
        model_id=outcome.usage[-1]["model_id"] if outcome.usage else None)
    session.add(qc)
    await session.commit()
    return {"status": "completed", "payload": outcome.model.model_dump()}


async def _mentions_for(session, company_id, fy, fq) -> list[dict]:
    rows = (await session.execute(select(TopicMentionRow).where(
        TopicMentionRow.company_id == company_id, TopicMentionRow.fiscal_year == fy,
        TopicMentionRow.fiscal_quarter == fq, TopicMentionRow.is_verified.is_(True)))).scalars()
    return [r.payload for r in rows]
