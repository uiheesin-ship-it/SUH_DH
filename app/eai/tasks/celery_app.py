"""Celery app + tasks for durable batch analysis (spec §2, §9, §11).

MVP runs batches inline/async; for 50+ companies the same orchestration runs
here as durable tasks (Redis broker). Each task opens its own async session and
bridges to the async pipeline via asyncio.run. Failures on one company do not
abort the batch (handled inside services.jobs.run_batch).
"""

from __future__ import annotations

import asyncio

from celery import Celery

from .. import config

celery_app = Celery("eai", broker=config.settings().redis_url,
                    backend=config.settings().redis_url)
celery_app.conf.update(task_track_started=True, task_acks_late=True,
                       worker_prefetch_multiplier=1)


def _run(coro):
    return asyncio.run(coro)


@celery_app.task(name="eai.run_batch", bind=True)
def run_batch_task(self, tickers: list[str] | None = None, job_id: int | None = None):
    from ..db import sessionmaker
    from ..models import AnalysisJob
    from ..services import jobs
    from sqlalchemy import select

    async def _job():
        async with sessionmaker()() as s:
            job = None
            if job_id is not None:
                job = (await s.execute(select(AnalysisJob).where(
                    AnalysisJob.id == job_id))).scalar_one_or_none()
            return await jobs.run_batch(s, tickers, job)

    return _run(_job())


@celery_app.task(name="eai.analyze_company", bind=True)
def analyze_company_task(self, ticker: str):
    from ..db import sessionmaker
    from ..services import jobs, universe

    async def _job():
        async with sessionmaker()() as s:
            await universe.seed_universe(s)
            company = await universe.get_company(s, ticker)
            if company is None:
                return {"status": "unknown_ticker", "ticker": ticker}
            await jobs.ingest_company(s, company)
            return {"status": "ingested", "ticker": ticker}

    return _run(_job())
