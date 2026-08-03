"""Stage 4/5: cross-company themes & investment themes (spec §11, §14).

The LLM writes the qualitative theme; **code** computes the Theme Score from
Breadth/Momentum/Intensity/Persistence/Value-chain/Numeric confirmation and
decides conviction. Independent confirmation by DIFFERENT companies is what
moves breadth/value-chain — repeated mentions by one company do not (spec §14).

Look-ahead guard (spec §5): only transcripts whose ``analysis_as_of`` is on or
before the run's as-of are included.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import config
from ..models import (
    Company,
    CrossCompanyTheme,
    InvestmentTheme,
    ModelUsage,
    ThemeComponent,
    TopicMentionRow,
    TranscriptDocument,
    TranscriptVersion,
)
from ..providers.llm import get_llm_provider
from ..schemas.llm_io import CrossCompanyThemeSet, InvestmentThemeLLM
from . import scoring
from .llm_runner import run_stage


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive datetimes as UTC for safe comparison."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _verified_mentions(session: AsyncSession, as_of: datetime | None):
    q = (select(TopicMentionRow, TranscriptDocument.analysis_as_of, Company.sector, Company.name)
         .join(TranscriptVersion, TopicMentionRow.transcript_version_id == TranscriptVersion.id)
         .join(TranscriptDocument, TranscriptVersion.transcript_id == TranscriptDocument.id)
         .join(Company, TopicMentionRow.company_id == Company.id)
         .where(TopicMentionRow.is_verified.is_(True)))
    rows = (await session.execute(q)).all()
    out = []
    cutoff = _as_utc(as_of)
    for mention, as_of_dt, sector, name in rows:
        doc_as_of = _as_utc(as_of_dt)
        if cutoff is not None and doc_as_of is not None and doc_as_of > cutoff:
            continue  # look-ahead guard
        out.append({"m": mention, "sector": sector, "company_name": name})
    return out


def _components(group: list[dict], value_chain_positions: set[str], theme_direction: str,
                total_universe: int) -> dict:
    tickers = {g["m"].ticker for g in group}
    company_count = len(tickers)
    intensities = [g["m"].intensity for g in group]
    aligned = [g for g in group if g["m"].direction == theme_direction]
    numeric = [g for g in group if g["m"].numeric_support]

    # persistence: fraction of companies mentioning the topic in >=2 distinct quarters
    quarters_by_ticker: dict[str, set] = {}
    for g in group:
        quarters_by_ticker.setdefault(g["m"].ticker, set()).add(
            (g["m"].fiscal_year, g["m"].fiscal_quarter))
    persistent = sum(1 for qs in quarters_by_ticker.values() if len(qs) >= 2)

    return {
        "breadth": min(1.0, company_count / max(1, total_universe)),
        "momentum": (len(aligned) / len(group)) if group else 0.0,
        "intensity": (sum(intensities) / len(intensities) / 5.0) if intensities else 0.0,
        "persistence": (persistent / company_count) if company_count else 0.0,
        "value_chain_confirmation": min(1.0, len(value_chain_positions) / 3.0),
        "numeric_confirmation": (len(numeric) / len(group)) if group else 0.0,
        "_company_count": company_count,
        "_tickers": sorted(tickers),
        "_sectors": sorted({g["sector"] for g in group if g["sector"]}),
    }


async def build_themes(session: AsyncSession, as_of: datetime | None = None) -> dict:
    """Run Stage 4 + 5 and persist themes with code-computed scores."""
    mat = config.maturity()
    cls = config.classification()
    sv = config.versions()["score_version"]
    provider = get_llm_provider()

    mentions = await _verified_mentions(session, as_of)
    total_universe = len((await session.execute(select(Company.id))).scalars().all()) or 1

    # group by topic
    groups: dict[str, list[dict]] = {}
    for item in mentions:
        groups.setdefault(item["m"].topic_id, []).append(item)

    # value-chain positions per topic (from company metadata)
    vc_by_topic: dict[str, set] = {}
    from ..models import CompanyValueChainPosition
    vc_rows = (await session.execute(select(CompanyValueChainPosition))).scalars()
    vc_by_company: dict[int, set] = {}
    for r in vc_rows:
        vc_by_company.setdefault(r.company_id, set()).add(r.position)
    for topic_id, group in groups.items():
        s: set[str] = set()
        for g in group:
            s |= vc_by_company.get(g["m"].company_id, set())
        vc_by_topic[topic_id] = s

    # dominant direction per topic
    topic_groups_payload = {}
    for topic_id, group in groups.items():
        dirs = [g["m"].direction for g in group]
        dominant = max(set(dirs), key=dirs.count) if dirs else "neutral"
        topic_groups_payload[topic_id] = {
            "direction": dominant,
            "company_count": len({g["m"].ticker for g in group}),
            "value_chain_positions": sorted(vc_by_topic.get(topic_id, set())),
        }

    # ---- Stage 4: cross-company themes ----
    from ..prompts import cross_company
    system, user = cross_company(topic_groups_payload)
    outcome = run_stage(provider, "deep", system, user, CrossCompanyThemeSet, stage="stage4")
    for u in outcome.usage:
        session.add(ModelUsage(**u))
    if outcome.model is None:
        await session.commit()
        return {"status": outcome.status, "themes": 0}

    now = datetime.now(timezone.utc)
    persisted = []
    for theme in outcome.model.themes:
        topic_id = theme.theme_id.replace("theme_", "")
        group = groups.get(topic_id, [])
        if not group:
            continue
        comps = _components(group, vc_by_topic.get(topic_id, set()), theme.direction,
                            total_universe)
        company_count = comps.pop("_company_count")
        tickers = comps.pop("_tickers")
        sectors = comps.pop("_sectors")
        score = scoring.theme_score(
            comps, company_count=company_count,
            minimum_company_breadth=cls["minimum_company_breadth"], score_version=sv)

        maturity_label = (mat["mvp_label"]
                          if company_count < mat["high_conviction_min_companies"] else None)
        payload = theme.model_dump()
        payload.update({"companies_mentioning": tickers, "company_count": company_count,
                        "company_ratio": round(company_count / total_universe, 3),
                        "sectors_mentioning": sectors, "components": comps,
                        "theme_score_breakdown": score.components,
                        "score_status": score.status})

        row = CrossCompanyTheme(
            theme_id=theme.theme_id, theme_name_en=theme.theme_name_en,
            theme_name_ko=theme.theme_name_ko, analysis_as_of=as_of or now,
            theme_score=score.score, score_status=score.status,
            maturity_label=maturity_label, payload=payload, score_version=sv)
        session.add(row)
        await session.flush()
        for name, weight in (score.weights or {}).items():
            raw = comps.get(name)
            session.add(ThemeComponent(
                theme_row_id=row.id, name=name, raw_value=raw, weight=weight,
                weighted=(raw * weight) if raw is not None else None, missing=raw is None))
        persisted.append((row, theme, tickers, sectors))

    await session.commit()

    # ---- Stage 5: investment themes ----
    n_invest = 0
    for row, theme, tickers, sectors in persisted:
        system, user = _invest_prompt(theme, tickers, sectors)
        outc = run_stage(provider, "deep", system, user, InvestmentThemeLLM, stage="stage5")
        for u in outc.usage:
            session.add(ModelUsage(**u))
        if outc.model is None:
            continue
        # Conviction decided in CODE (spec §11-6): capped at MVP breadth.
        conviction = _conviction(row.theme_score, len(tickers), mat)
        payload = outc.model.model_dump()
        session.add(InvestmentTheme(
            theme_row_id=row.id, investment_theme=outc.model.investment_theme,
            conviction=conviction,
            narrative_confirmation_status=payload.get("suggested_narrative_confirmation_status"),
            maturity_label=row.maturity_label, payload=payload))
        n_invest += 1

    await session.commit()
    return {"status": "completed", "themes": len(persisted), "investment_themes": n_invest,
            "maturity": mat["mvp_label"] if total_universe < mat["high_conviction_min_companies"]
            else None}


def _invest_prompt(theme, tickers, sectors):
    from ..prompts import investment_theme
    return investment_theme({"theme_name_en": theme.theme_name_en,
                             "theme_name_ko": theme.theme_name_ko,
                             "companies": tickers, "sectors": sectors})


def _conviction(theme_score, company_count, mat) -> str:
    # High conviction is not allowed until the universe is broad enough (spec §11-6).
    if company_count < mat["high_conviction_min_companies"]:
        return "low"
    if theme_score is None:
        return "low"
    if theme_score >= 70:
        return "high"
    if theme_score >= 50:
        return "medium"
    return "low"
