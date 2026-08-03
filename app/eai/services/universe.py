"""Seed and query the company universe from eai_config.yaml (spec §3)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import config
from ..models import (
    Company,
    CompanySignalRole,
    CompanyUniverseType,
    CompanyValueChainPosition,
)


async def seed_universe(session: AsyncSession) -> list[Company]:
    """Create/refresh companies from config. Idempotent by ticker."""
    created = []
    for row in config.universe():
        ticker = row["ticker"].upper()
        existing = (await session.execute(
            select(Company).where(Company.ticker == ticker))).scalar_one_or_none()
        if existing is None:
            company = Company(
                ticker=ticker, name=row.get("name", ticker), sector=row.get("sector"),
                industry=row.get("industry"), country=row.get("country", "US"),
            )
            session.add(company)
            await session.flush()
        else:
            company = existing
            company.name = row.get("name", company.name)
            company.sector = row.get("sector", company.sector)
            company.industry = row.get("industry", company.industry)

        # universe type
        ut = (await session.execute(select(CompanyUniverseType).where(
            CompanyUniverseType.company_id == company.id))).scalars().first()
        if ut is None:
            session.add(CompanyUniverseType(
                company_id=company.id, universe_type=row.get("universe_type", "core"),
                tracked_quarters=int(row.get("tracked_quarters", 2))))
        else:
            ut.universe_type = row.get("universe_type", ut.universe_type)
            ut.tracked_quarters = int(row.get("tracked_quarters", ut.tracked_quarters))

        # signal roles (replace set)
        await _sync_roles(session, company.id, row.get("signal_roles", []))
        await _sync_positions(session, company.id, row.get("value_chain_positions", []))
        created.append(company)
    await session.commit()
    return created


async def _sync_roles(session: AsyncSession, company_id: int, roles: list[str]) -> None:
    have = {r.role for r in (await session.execute(select(CompanySignalRole).where(
        CompanySignalRole.company_id == company_id))).scalars()}
    for role in roles:
        if role not in have:
            session.add(CompanySignalRole(company_id=company_id, role=role))


async def _sync_positions(session: AsyncSession, company_id: int, positions: list[str]) -> None:
    have = {p.position for p in (await session.execute(select(CompanyValueChainPosition).where(
        CompanyValueChainPosition.company_id == company_id))).scalars()}
    for pos in positions:
        if pos not in have:
            session.add(CompanyValueChainPosition(company_id=company_id, position=pos))


async def get_company(session: AsyncSession, ticker: str) -> Company | None:
    return (await session.execute(
        select(Company)
        .options(selectinload(Company.universe_types),
                 selectinload(Company.signal_roles),
                 selectinload(Company.value_chain_positions))
        .where(Company.ticker == ticker.upper()))).scalar_one_or_none()


async def all_companies(session: AsyncSession) -> list[Company]:
    return list((await session.execute(
        select(Company)
        .options(selectinload(Company.universe_types),
                 selectinload(Company.signal_roles),
                 selectinload(Company.value_chain_positions))
        .order_by(Company.ticker))).scalars())
