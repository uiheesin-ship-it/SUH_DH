"""Analysis job state + batch orchestration (spec §2, §11, §22, §23).

Job status lives in the DB across the 8 states, so an interrupted run can be
recovered after a restart. A batch keeps going when one company/chunk fails
(partially_completed); nothing is silently dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AnalysisJob, Company
from ..providers.financial import get_financial_provider
from ..providers.transcript import get_transcript_provider
from . import ingest, pipeline, themes, universe


async def create_job(session: AsyncSession, kind: str, scope: dict) -> AnalysisJob:
    job = AnalysisJob(kind=kind, scope=scope, status="pending", progress={})
    session.add(job)
    await session.commit()
    return job


async def set_status(session: AsyncSession, job: AnalysisJob, status: str,
                     error: str | None = None) -> None:
    job.status = status
    if error:
        job.error = error
    await session.commit()


async def update_progress(session: AsyncSession, job: AnalysisJob, key: str, value) -> None:
    progress = dict(job.progress or {})
    progress[key] = value
    job.progress = progress
    await session.commit()


async def recover_incomplete(session: AsyncSession) -> list[int]:
    """Requeue jobs left running/queued by a crash (spec §2). Returns their ids."""
    stuck = list((await session.execute(select(AnalysisJob).where(
        AnalysisJob.status.in_(["running", "queued"])))).scalars())
    ids = []
    for job in stuck:
        job.status = "pending"
        ids.append(job.id)
    await session.commit()
    return ids


async def ingest_company(session: AsyncSession, company: Company) -> int:
    """Fetch recent transcripts + financials for one company. Returns #calls.

    Capped to the company's tracked_quarters (spec §5) and resilient per call:
    a transcript-source error on one quarter (e.g. an API hiccup) is recorded
    and skipped so the others still ingest (spec §23).
    """
    tprov = get_transcript_provider()
    fprov = get_financial_provider()

    limit = company.universe_types[0].tracked_quarters if company.universe_types else None
    refs = list(tprov.list_available(company.ticker))
    refs.sort(key=lambda r: (r.fiscal_year, r.fiscal_quarter), reverse=True)
    if limit:
        refs = refs[:limit]

    calls = 0
    for ref in refs:
        try:
            raw = tprov.fetch(ref)
            await ingest.ingest_transcript(session, company, raw)
        except Exception as e:  # keep going on a single bad quarter
            from ..models import ProviderError
            session.add(ProviderError(provider=getattr(tprov, "name", "?"),
                                      error_type="transcript_fetch",
                                      payload={"ticker": company.ticker,
                                               "period": f"{ref.fiscal_year}Q{ref.fiscal_quarter}",
                                               "error": str(e)}))
            await session.commit()
            continue
        period = pipeline.fiscal_period(ref.fiscal_year, ref.fiscal_quarter)
        kpis = fprov.fetch_kpis(company.ticker, period)
        guidance = fprov.fetch_guidance(company.ticker, period)
        if kpis or guidance:
            await ingest.store_financials(session, company, kpis, guidance)
        calls += 1
    return calls


async def run_batch(session: AsyncSession, tickers: list[str] | None = None,
                    job: AnalysisJob | None = None) -> dict:
    """End-to-end MVP batch: seed → ingest → analyze → QoQ → cross-company themes.

    Resilient: a failure on one company is recorded and the batch continues.
    """
    await universe.seed_universe(session)
    companies = await universe.all_companies(session)
    if tickers:
        wanted = {t.upper() for t in tickers}
        companies = [c for c in companies if c.ticker in wanted]

    if job is not None:
        await set_status(session, job, "running")

    results: dict[str, dict] = {}
    any_fail = False
    for company in companies:
        try:
            await ingest_company(session, company)
            from ..models import TranscriptVersion, TranscriptDocument
            versions = list((await session.execute(
                select(TranscriptVersion)
                .join(TranscriptDocument, TranscriptVersion.transcript_id == TranscriptDocument.id)
                .where(TranscriptDocument.company_id == company.id))).scalars())
            call_results = []
            for v in versions:
                r = await pipeline.analyze_call(session, company, v, job=job)
                call_results.append(r)
                if r.get("status") == "llm_unavailable":
                    results[company.ticker] = {"status": "llm_unavailable"}
                    if job is not None:
                        await set_status(session, job, "failed", "LLM analysis unavailable")
                    return {"status": "llm_unavailable", "results": results}
            qoq = await pipeline.compare_quarters(session, company)
            status = "partially_completed" if any(
                c.get("chunk_failures") for c in call_results) else "completed"
            results[company.ticker] = {"status": status, "calls": call_results, "qoq": qoq}
            if status == "partially_completed":
                any_fail = True
        except Exception as e:  # keep the batch alive (spec §23)
            any_fail = True
            results[company.ticker] = {"status": "failed", "error": str(e)}
        if job is not None:
            await update_progress(session, job, company.ticker, results[company.ticker]["status"])

    try:
        theme_result = await themes.build_themes(session, as_of=datetime.now(timezone.utc))
    except Exception as e:  # never crash the batch on a theme-stage error
        theme_result = {"status": "error", "error": str(e), "themes": 0}
    results["_themes"] = theme_result

    # A theme-stage LLM outage (e.g. invalid key with no company transcripts to
    # trip the earlier check) must also preserve the last good snapshot.
    if theme_result.get("status") == "unavailable":
        if job is not None:
            await set_status(session, job, "failed", "LLM analysis unavailable")
        return {"status": "llm_unavailable", "results": results}

    final = "partially_completed" if any_fail else "completed"
    if job is not None:
        await set_status(session, job, final)
    return {"status": final, "results": results}
