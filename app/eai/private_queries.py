"""Read queries for the private 4-tab app (full transcripts, search, bundle).

These serve the transcript *text* itself, so they live behind auth. All data
comes from the DB (transcript_paragraphs), which persists independently of the
LLM — so collection + browsing + download keep working even when the LLM/API
credits are exhausted (spec §6 minimum: collection & download must work).
"""

from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    CallSummary,
    Company,
    TranscriptDocument,
    TranscriptParagraph,
)


def _period_label(fy: int, fq: int) -> str:
    return f"FY{fy}Q{fq}"


# ------------------------------ left panel ---------------------------------

async def companies_by_sector(session: AsyncSession) -> list[dict]:
    """Sectors → companies, each with which periods have transcripts (tab ①)."""
    companies = list((await session.execute(select(Company).order_by(Company.sector, Company.ticker))).scalars())
    # periods that actually have transcripts, per company
    rows = (await session.execute(
        select(TranscriptDocument.company_id, TranscriptDocument.fiscal_year,
               TranscriptDocument.fiscal_quarter))).all()
    periods: dict[int, list[list[int]]] = {}
    for cid, fy, fq in rows:
        periods.setdefault(cid, []).append([fy, fq])
    for v in periods.values():
        v.sort(reverse=True)

    by_sector: dict[str, list[dict]] = {}
    for c in companies:
        by_sector.setdefault(c.sector or "기타", []).append({
            "ticker": c.ticker, "name": c.name,
            "has_transcripts": bool(periods.get(c.id)),
            "periods": periods.get(c.id, []),
        })
    return [{"sector": s, "companies": cs} for s, cs in by_sector.items()]


async def available_periods(session: AsyncSession, ticker: str) -> list[dict]:
    docs = list((await session.execute(
        select(TranscriptDocument).where(TranscriptDocument.ticker == ticker.upper())
        .order_by(TranscriptDocument.fiscal_year.desc(),
                  TranscriptDocument.fiscal_quarter.desc()))).scalars())
    return [{"fiscal_year": d.fiscal_year, "fiscal_quarter": d.fiscal_quarter,
             "call_date": d.call_date, "has_text": d.current_version_id is not None}
            for d in docs]


# ------------------------------ full transcript ----------------------------

async def full_transcript(session: AsyncSession, ticker: str, fy: int, fq: int) -> dict | None:
    """Ordered paragraphs (English original + Korean translation if cached)."""
    doc = (await session.execute(select(TranscriptDocument).where(
        TranscriptDocument.ticker == ticker.upper(),
        TranscriptDocument.fiscal_year == fy,
        TranscriptDocument.fiscal_quarter == fq))).scalar_one_or_none()
    if doc is None or doc.current_version_id is None:
        return None
    paras = list((await session.execute(select(TranscriptParagraph).where(
        TranscriptParagraph.transcript_version_id == doc.current_version_id
    ).order_by(TranscriptParagraph.sequence_number))).scalars())
    company = (await session.execute(select(Company).where(
        Company.id == doc.company_id))).scalar_one_or_none()
    any_ko = any(p.translation_ko for p in paras)
    return {
        "ticker": doc.ticker, "company": company.name if company else doc.ticker,
        "fiscal_year": fy, "fiscal_quarter": fq, "call_date": doc.call_date,
        "korean_available": any_ko,
        "paragraphs": [{
            "paragraph_id": p.paragraph_id, "section_type": p.section_type,
            "speaker_name": p.speaker_name, "speaker_role": p.speaker_role,
            "text_en": p.exact_text_en, "text_ko": p.translation_ko,
        } for p in paras],
    }


# ------------------------------ search -------------------------------------

async def search_transcripts(session: AsyncSession, query: str, *, limit: int = 50,
                             ticker: str | None = None) -> dict:
    """Google-like search over all stored transcripts (English or Korean).

    Case-insensitive substring match over paragraph text, ranked by number of
    query-term hits, returning a snippet with the matched terms highlighted.
    """
    q = (query or "").strip()
    if not q:
        return {"query": q, "count": 0, "results": []}
    terms = [t for t in re.split(r"\s+", q) if t]

    conds = []
    for t in terms:
        like = f"%{t}%"
        conds.append(or_(func.lower(TranscriptParagraph.exact_text_en).like(func.lower(like)),
                         func.lower(func.coalesce(TranscriptParagraph.translation_ko, "")).like(func.lower(like))))
    stmt = (select(TranscriptParagraph, TranscriptDocument.ticker,
                   TranscriptDocument.fiscal_year, TranscriptDocument.fiscal_quarter)
            .join(TranscriptDocument,
                  TranscriptDocument.current_version_id == TranscriptParagraph.transcript_version_id))
    for c in conds:
        stmt = stmt.where(c)  # AND of all terms
    if ticker:
        stmt = stmt.where(TranscriptDocument.ticker == ticker.upper())
    stmt = stmt.limit(limit * 3)  # over-fetch, then rank

    rows = (await session.execute(stmt)).all()
    scored = []
    for p, tk, fy, fq in rows:
        hay = f"{p.exact_text_en}\n{p.translation_ko or ''}".lower()
        hits = sum(hay.count(t.lower()) for t in terms)
        scored.append((hits, p, tk, fy, fq))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for hits, p, tk, fy, fq in scored[:limit]:
        results.append({
            "ticker": tk, "fiscal_year": fy, "fiscal_quarter": fq,
            "paragraph_id": p.paragraph_id, "speaker_name": p.speaker_name,
            "speaker_role": p.speaker_role, "section_type": p.section_type,
            "hits": hits, "snippet_en": _snippet(p.exact_text_en, terms),
            "snippet_ko": _snippet(p.translation_ko, terms) if p.translation_ko else None,
        })
    return {"query": q, "count": len(results), "results": results}


def _snippet(text: str | None, terms: list[str], window: int = 160) -> str | None:
    if not text:
        return None
    low = text.lower()
    pos = -1
    for t in terms:
        i = low.find(t.lower())
        if i >= 0:
            pos = i
            break
    if pos < 0:
        return text[:window]
    start = max(0, pos - window // 2)
    end = min(len(text), pos + window // 2)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


# ------------------------------ bundle download ----------------------------

async def bundle_text(session: AsyncSession, tickers: list[str], periods: list[str]) -> str:
    """Assemble selected companies × periods into ONE plain-text document.

    ``periods`` are "YYYYQn" calendar labels (matching fiscal_year/quarter here).
    Missing (not-yet-collected) combos are noted, never silently dropped.
    """
    wanted_periods = set()
    for p in periods:
        try:
            y, qq = p.upper().split("Q")
            wanted_periods.add((int(y), int(qq)))
        except ValueError:
            continue

    out: list[str] = []
    for ticker in [t.upper() for t in tickers]:
        for (fy, fq) in sorted(wanted_periods, reverse=True):
            data = await full_transcript(session, ticker, fy, fq)
            header = f"{'='*70}\n{ticker}  FY{fy} Q{fq}\n{'='*70}\n"
            if data is None:
                out.append(header + "(수집된 컨콜 원문이 없습니다 / transcript not collected)\n")
                continue
            out.append(header)
            if data.get("call_date"):
                out.append(f"Call date: {data['call_date']}\n")
            for p in data["paragraphs"]:
                spk = p.get("speaker_name") or ""
                role = p.get("speaker_role") or ""
                out.append(f"\n[{spk} — {role}] ({p['section_type']})\n{p['text_en']}\n")
            out.append("\n\n")
    return "".join(out)
