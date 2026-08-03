"""Read-side queries powering the API/UI (spec §18, §19, §21).

Pure data assembly from the DB — the Korean-facing UI consumes these; no LLM
calls here. Every score carries its experimental flag and version so the UI can
label it honestly (spec §13, §14).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from ..models import (
    CallSummary,
    Company,
    CompanySignalRole,
    CompanyUniverseType,
    CompanyValueChainPosition,
    CrossCompanyTheme,
    EvidenceLink,
    EvidenceVerification,
    InvestmentTheme,
    ModelUsage,
    QuarterlyComparison,
    TopicMentionRow,
)


async def universe_maturity() -> dict:
    mat = config.maturity()
    return {"mvp_label": mat["mvp_label"],
            "high_conviction_min_companies": mat["high_conviction_min_companies"]}


async def list_companies(session: AsyncSession) -> list[dict]:
    from .universe import all_companies
    out = []
    for c in await all_companies(session):
        ut = c.universe_types[0] if c.universe_types else None
        out.append({
            "ticker": c.ticker, "name": c.name, "sector": c.sector, "industry": c.industry,
            "universe_type": ut.universe_type if ut else None,
            "tracked_quarters": ut.tracked_quarters if ut else None,
            "signal_roles": [r.role for r in c.signal_roles],
            "value_chain_positions": [p.position for p in c.value_chain_positions],
        })
    return out


async def company_detail(session: AsyncSession, ticker: str) -> dict | None:
    from .universe import get_company
    c = await get_company(session, ticker)
    if c is None:
        return None
    summaries = list((await session.execute(select(CallSummary).where(
        CallSummary.company_id == c.id).order_by(
        CallSummary.fiscal_year.desc(), CallSummary.fiscal_quarter.desc()))).scalars())
    qoq = list((await session.execute(select(QuarterlyComparison).where(
        QuarterlyComparison.company_id == c.id).order_by(
        QuarterlyComparison.created_at.desc()))).scalars())
    ut = c.universe_types[0] if c.universe_types else None
    return {
        "ticker": c.ticker, "name": c.name, "sector": c.sector, "industry": c.industry,
        "universe_type": ut.universe_type if ut else None,
        "signal_roles": [r.role for r in c.signal_roles],
        "value_chain_positions": [p.position for p in c.value_chain_positions],
        "calls": [{
            "fiscal_year": s.fiscal_year, "fiscal_quarter": s.fiscal_quarter,
            "summary": s.payload, "scores": s.payload.get("scores"),
        } for s in summaries],
        "quarterly_comparisons": [{
            "from_period": q.from_period, "to_period": q.to_period, "payload": q.payload,
        } for q in qoq],
    }


async def company_mentions(session: AsyncSession, ticker: str, fiscal_year: int | None = None,
                           fiscal_quarter: int | None = None,
                           verified_only: bool = True) -> list[dict]:
    conds = [TopicMentionRow.ticker == ticker.upper()]
    if fiscal_year:
        conds.append(TopicMentionRow.fiscal_year == fiscal_year)
    if fiscal_quarter:
        conds.append(TopicMentionRow.fiscal_quarter == fiscal_quarter)
    if verified_only:
        conds.append(TopicMentionRow.is_verified.is_(True))
    rows = (await session.execute(select(TopicMentionRow).where(*conds))).scalars()
    return [r.payload for r in rows]


async def evidence_for(session: AsyncSession, claim_type: str, claim_id: int) -> list[dict]:
    rows = (await session.execute(
        select(EvidenceLink, EvidenceVerification)
        .outerjoin(EvidenceVerification, EvidenceVerification.evidence_id == EvidenceLink.id)
        .where(EvidenceLink.claim_type == claim_type,
               EvidenceLink.claim_id == claim_id))).all()
    return [{
        "paragraph_id": link.paragraph_id, "exact_quote_en": link.exact_quote_en,
        "translation_ko": link.translation_ko,
        "quote_start_offset": link.quote_start_offset, "quote_end_offset": link.quote_end_offset,
        "verification_status": v.verification_status if v else None,
        "verification_method": v.verification_method if v else None,
        "numeric_check": v.numeric_check if v else None,
    } for link, v in rows]


async def list_themes(session: AsyncSession) -> list[dict]:
    rows = list((await session.execute(select(CrossCompanyTheme).order_by(
        CrossCompanyTheme.theme_score.desc().nullslast()))).scalars())
    return [_theme_dict(t) for t in rows]


def _theme_dict(t: CrossCompanyTheme) -> dict:
    return {
        "theme_id": t.theme_id, "theme_name_en": t.theme_name_en,
        "theme_name_ko": t.theme_name_ko, "theme_score": t.theme_score,
        "score_status": t.score_status, "is_experimental": t.is_experimental,
        "maturity_label": t.maturity_label, "score_version": t.score_version,
        "payload": t.payload,
    }


async def investment_board(session: AsyncSession) -> list[dict]:
    rows = list((await session.execute(select(InvestmentTheme).order_by(
        InvestmentTheme.created_at.desc()))).scalars())
    return [{
        "investment_theme": r.investment_theme, "conviction": r.conviction,
        "narrative_confirmation_status": r.narrative_confirmation_status,
        "is_experimental": r.is_experimental, "maturity_label": r.maturity_label,
        "payload": r.payload,
    } for r in rows]


async def usage_summary(session: AsyncSession) -> dict:
    rows = list((await session.execute(select(ModelUsage))).scalars())
    total_in = sum(r.input_tokens for r in rows)
    total_out = sum(r.output_tokens for r in rows)
    total_cost = sum(r.estimated_cost for r in rows)
    cache_hits = sum(1 for r in rows if r.cache_hit)
    by_model: dict[str, dict] = {}
    for r in rows:
        m = by_model.setdefault(r.model_id, {"calls": 0, "input_tokens": 0,
                                             "output_tokens": 0, "estimated_cost": 0.0})
        m["calls"] += 1
        m["input_tokens"] += r.input_tokens
        m["output_tokens"] += r.output_tokens
        m["estimated_cost"] += r.estimated_cost
    return {
        "total_calls": len(rows), "input_tokens": total_in, "output_tokens": total_out,
        "estimated_cost": round(total_cost, 6),
        "cache_hit_rate": round(cache_hits / len(rows), 4) if rows else 0.0,
        "avg_processing_time": round(sum(r.processing_time for r in rows) / len(rows), 4)
        if rows else 0.0,
        "by_model": by_model,
    }


async def coverage_dashboard(session: AsyncSession) -> dict:
    """Universe coverage: companies per sector / signal-role / value-chain (spec §19)."""
    companies = list((await session.execute(select(Company))).scalars())
    by_sector: dict[str, int] = {}
    for c in companies:
        by_sector[c.sector or "?"] = by_sector.get(c.sector or "?", 0) + 1

    roles = (await session.execute(select(CompanySignalRole.role, func.count()).group_by(
        CompanySignalRole.role))).all()
    positions = (await session.execute(
        select(CompanyValueChainPosition.position, func.count()).group_by(
            CompanyValueChainPosition.position))).all()
    utypes = (await session.execute(select(CompanyUniverseType.universe_type, func.count()).group_by(
        CompanyUniverseType.universe_type))).all()

    # topics with only one confirming company (thin coverage)
    topic_companies = (await session.execute(
        select(TopicMentionRow.topic_id, func.count(func.distinct(TopicMentionRow.ticker)))
        .where(TopicMentionRow.is_verified.is_(True)).group_by(TopicMentionRow.topic_id))).all()
    single_company_topics = [t for t, n in topic_companies if n == 1]

    return {
        "total_companies": len(companies),
        "by_sector": by_sector,
        "by_signal_role": {r: n for r, n in roles},
        "by_value_chain": {p: n for p, n in positions},
        "by_universe_type": {u: n for u, n in utypes},
        "single_company_topics": single_company_topics,
        "maturity": config.maturity()["mvp_label"],
    }
