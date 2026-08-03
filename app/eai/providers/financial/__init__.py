"""Financial data provider factory (spec §6.2)."""

from __future__ import annotations

from ... import config
from .base import GuidanceMetricDTO, VerifiedKPI  # noqa: F401


def get_financial_provider(name: str | None = None):
    name = name or config.provider_name("financial")
    if name == "guidance_json":
        from .guidance_json import GuidanceJSONProvider
        return GuidanceJSONProvider()
    raise ValueError(f"Unknown financial provider: {name}")
