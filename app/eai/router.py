"""FastAPI routes for the eai subsystem (spec §18, §21, §22).

Mounted under /api/eai/* by app/main.py. Read endpoints power the Korean UI;
write endpoints seed the universe, upload transcripts, and run analysis jobs.
Heavy batches run as background asyncio tasks for the MVP; Celery is the
durable queue for 50+ companies (later phase).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import config
from .db import create_all, get_session, sessionmaker
from .models import AnalysisJob, Company
from .services import ingest, jobs, pipeline, queries, universe
from .services.evidence import build_index

router = APIRouter(prefix="/api/eai", tags=["eai"])


async def init_eai() -> None:
    """Create tables (MVP; prod uses Alembic) and recover interrupted jobs."""
    await create_all()
    async with sessionmaker()() as s:
        await jobs.recover_incomplete(s)


def include_private(app_or_router) -> None:
    """Attach the login-gated private API (transcripts/search/download)."""
    from .private_router import router as private
    app_or_router.include_router(private)


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0",
            "llm_provider": config.provider_name("llm"),
            "transcript_provider": config.provider_name("transcript"),
            "maturity": config.maturity()["mvp_label"]}


@router.get("/ontology")
async def get_ontology():
    from . import ontology
    return {"version": config.versions()["ontology_version"],
            "topics": list(ontology.topics().values())}


@router.post("/seed")
async def seed(session: AsyncSession = Depends(get_session)):
    companies = await universe.seed_universe(session)
    return {"seeded": [c.ticker for c in companies]}


@router.get("/companies")
async def companies(session: AsyncSession = Depends(get_session)):
    return {"companies": await queries.list_companies(session)}


@router.get("/companies/{ticker}")
async def company(ticker: str, session: AsyncSession = Depends(get_session)):
    data = await queries.company_detail(session, ticker)
    if data is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not found")
    return data


@router.get("/companies/{ticker}/mentions")
async def company_mentions(ticker: str, fiscal_year: int | None = None,
                           fiscal_quarter: int | None = None,
                           session: AsyncSession = Depends(get_session)):
    return {"mentions": await queries.company_mentions(
        session, ticker, fiscal_year, fiscal_quarter)}


@router.get("/themes")
async def themes(session: AsyncSession = Depends(get_session)):
    return {"themes": await queries.list_themes(session),
            "maturity": config.maturity()["mvp_label"]}


@router.get("/investment-themes")
async def investment_themes(session: AsyncSession = Depends(get_session)):
    return {"investment_themes": await queries.investment_board(session),
            "maturity": config.maturity()["mvp_label"]}


@router.get("/evidence/{claim_type}/{claim_id}")
async def evidence(claim_type: str, claim_id: int,
                   session: AsyncSession = Depends(get_session)):
    return {"evidence": await queries.evidence_for(session, claim_type, claim_id)}


@router.get("/usage")
async def usage(session: AsyncSession = Depends(get_session)):
    return await queries.usage_summary(session)


@router.get("/coverage")
async def coverage(session: AsyncSession = Depends(get_session)):
    return await queries.coverage_dashboard(session)


@router.get("/jobs")
async def list_jobs(session: AsyncSession = Depends(get_session)):
    rows = list((await session.execute(select(AnalysisJob).order_by(
        AnalysisJob.id.desc()))).scalars())
    return {"jobs": [{"id": j.id, "kind": j.kind, "status": j.status,
                      "scope": j.scope, "progress": j.progress, "error": j.error} for j in rows]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, session: AsyncSession = Depends(get_session)):
    job = (await session.execute(select(AnalysisJob).where(
        AnalysisJob.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"id": job.id, "kind": job.kind, "status": job.status, "scope": job.scope,
            "progress": job.progress, "error": job.error}


@router.post("/jobs/run-batch")
async def run_batch(tickers: str | None = None, wait: bool = False,
                    session: AsyncSession = Depends(get_session)):
    """Kick off the MVP batch. ?wait=true runs inline (mock is fast); otherwise
    it runs as a background task and returns the job id to poll."""
    ticker_list = [t.strip() for t in tickers.split(",")] if tickers else None
    job = await jobs.create_job(session, "batch", {"tickers": ticker_list or "all"})
    if wait:
        async with sessionmaker()() as s:
            job2 = (await s.execute(select(AnalysisJob).where(AnalysisJob.id == job.id))).scalar_one()
            result = await jobs.run_batch(s, ticker_list, job2)
        return {"job_id": job.id, "result": result}

    async def _bg(job_id: int):
        async with sessionmaker()() as s:
            j = (await s.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))).scalar_one()
            try:
                await jobs.run_batch(s, ticker_list, j)
            except Exception as e:  # never leave a job wedged in 'running'
                await jobs.set_status(s, j, "failed", str(e))

    asyncio.create_task(_bg(job.id))
    return {"job_id": job.id, "status": "queued"}


@router.post("/upload")
async def upload_transcript(file: UploadFile, ticker: str, fiscal_year: int,
                            fiscal_quarter: int, call_date: str | None = None,
                            session: AsyncSession = Depends(get_session)):
    """Manual transcript upload (.txt/.json/.pdf), ingested + version-checked."""
    from .providers.transcript.manual_upload import from_upload
    company = await universe.get_company(session, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not in universe; seed first")
    content = await file.read()
    try:
        raw = from_upload(filename=file.filename, content=content, ticker=ticker.upper(),
                          fiscal_year=fiscal_year, fiscal_quarter=fiscal_quarter,
                          call_date=call_date, company=company.name)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"parse failed: {e}"})
    version, created = await ingest.ingest_transcript(session, company, raw)
    return {"transcript_version_id": version.id, "created": created,
            "message": "ingested" if created else "duplicate (checksum match)"}
