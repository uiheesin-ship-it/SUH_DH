"""Curated-JSON financial provider (spec §6.2).

Reads verified KPIs and guidance-vs-consensus from
app/eai/fixtures/financials/<TICKER>.json. Mirrors the repo's existing
data/guidance.json convention (hand-curated numbers with source links), which
is the right pattern because the free APIs don't carry point-in-time guidance
and consensus.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import GuidanceMetricDTO, VerifiedKPI

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "financials"


class GuidanceJSONProvider:
    name = "guidance_json"

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self.dir = fixture_dir or FIXTURE_DIR

    def _load(self, ticker: str) -> dict:
        path = self.dir / f"{ticker.upper()}.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def fetch_kpis(self, ticker: str, fiscal_period: str | None = None) -> list[VerifiedKPI]:
        data = self._load(ticker)
        out = []
        for row in data.get("kpis", []):
            if fiscal_period and row.get("fiscal_period") != fiscal_period:
                continue
            out.append(VerifiedKPI(ticker=ticker.upper(), **{
                k: row.get(k) for k in (
                    "fiscal_period", "metric_id", "metric_name", "value", "unit", "currency",
                    "gaap_or_non_gaap", "actual_or_guidance", "yoy_growth", "comparison_basis",
                    "source_page", "source_paragraph_id", "published_at", "confidence",
                    "verification_status") if k in row}))
        return out

    def fetch_guidance(self, ticker: str, fiscal_period: str | None = None) -> list[GuidanceMetricDTO]:
        data = self._load(ticker)
        out = []
        for row in data.get("guidance", []):
            if fiscal_period and row.get("fiscal_period") != fiscal_period:
                continue
            out.append(GuidanceMetricDTO(ticker=ticker.upper(), **{
                k: row.get(k) for k in (
                    "fiscal_period", "metric", "unit", "guidance_mid", "guidance_low",
                    "guidance_high", "consensus", "note", "sources", "published_at",
                    "verification_status") if k in row}))
        return out
