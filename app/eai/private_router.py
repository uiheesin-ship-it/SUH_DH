"""Private API for the login-gated 4-tab app (spec: transcripts stay private).

All /api/eai/private/* endpoints require a bearer token from /api/eai/login.
They serve full transcript text, search, and bundle download — the features
that must NOT be on the public static site.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from . import auth, private_queries as pq
from .db import get_session

router = APIRouter(prefix="/api/eai", tags=["eai-private"])


class LoginBody(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginBody):
    return {"token": auth.login(body.password)}


@router.get("/private/companies", dependencies=[Depends(auth.require_auth)])
async def companies(session: AsyncSession = Depends(get_session)):
    return {"sectors": await pq.companies_by_sector(session)}


@router.get("/private/periods/{ticker}", dependencies=[Depends(auth.require_auth)])
async def periods(ticker: str, session: AsyncSession = Depends(get_session)):
    return {"ticker": ticker.upper(), "periods": await pq.available_periods(session, ticker)}


@router.get("/private/transcript/{ticker}/{fy}/{fq}",
            dependencies=[Depends(auth.require_auth)])
async def transcript(ticker: str, fy: int, fq: int,
                     session: AsyncSession = Depends(get_session)):
    data = await pq.full_transcript(session, ticker, fy, fq)
    if data is None:
        raise HTTPException(status_code=404,
                            detail="이 기간의 컨콜 원문이 아직 수집되지 않았습니다.")
    return data


@router.get("/private/company/{ticker}/evolution",
            dependencies=[Depends(auth.require_auth)])
async def evolution(ticker: str, session: AsyncSession = Depends(get_session)):
    return await pq.company_evolution(session, ticker)


@router.get("/private/investment-points", dependencies=[Depends(auth.require_auth)])
async def investment_points(session: AsyncSession = Depends(get_session)):
    return {"points": await pq.investment_points(session)}


@router.get("/private/search", dependencies=[Depends(auth.require_auth)])
async def search(q: str, ticker: str | None = None, limit: int = 50,
                 session: AsyncSession = Depends(get_session)):
    return await pq.search_transcripts(session, q, ticker=ticker, limit=limit)


@router.post("/private/download", dependencies=[Depends(auth.require_auth)])
async def download(tickers: list[str] = Body(...), periods: list[str] = Body(...),
                   format: str = Body("txt"),
                   session: AsyncSession = Depends(get_session)):
    """Bundle selected companies × periods into ONE file (txt or docx)."""
    if not tickers or not periods:
        raise HTTPException(status_code=400, detail="기업과 기간을 하나 이상 선택하세요.")
    text = await pq.bundle_text(session, tickers, periods)
    fname = f"transcripts_{'_'.join(t.upper() for t in tickers[:3])}"
    if len(tickers) > 3:
        fname += f"_and_{len(tickers)-3}_more"

    if format == "docx":
        content, media, ext = _to_docx(text), (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), "docx"
    else:
        content, media, ext = text.encode("utf-8"), "text/plain; charset=utf-8", "txt"

    return StreamingResponse(
        io.BytesIO(content), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}.{ext}"'})


def _to_docx(text: str) -> bytes:
    try:
        from docx import Document  # python-docx, optional
    except Exception as e:  # pragma: no cover - optional dep
        raise HTTPException(status_code=501,
                            detail="docx 지원에는 python-docx 설치가 필요합니다. txt를 사용하세요.") from e
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
