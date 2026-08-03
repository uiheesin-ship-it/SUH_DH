"""Configuration for the Earnings-AI (eai) subsystem.

Secrets (DB URL, LLM API keys) come from the environment; everything else —
provider selection, model tiers, scoring weights, the company universe, and
version tags — comes from ``eai_config.yaml`` so they can be swapped without
code changes (spec §1-12, §20). Mirrors the existing config-driven pattern of
``config.yaml``/``flat_config.yaml`` in this repo.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = Path(os.environ.get("EAI_CONFIG_FILE") or (ROOT / "eai_config.yaml"))


class Settings(BaseSettings):
    """Environment-driven secrets/toggles (never hardcode keys, spec §8)."""

    model_config = SettingsConfigDict(env_prefix="EAI_", extra="ignore")

    # Default to a local SQLite file so the MVP runs with no Postgres server;
    # set EAI_DATABASE_URL to a postgresql+asyncpg://… URL in prod (docker/render).
    database_url: str = f"sqlite+aiosqlite:///{ROOT / 'eai.db'}"
    redis_url: str = "redis://localhost:6379/0"

    # Provider overrides (win over eai_config.yaml when set).
    llm_provider: str | None = None
    transcript_provider: str | None = None
    financial_provider: str | None = None
    storage_provider: str | None = None

    # Logical model tiers -> concrete IDs (spec §8; no model name hardcoded).
    fast_model: str | None = None
    balanced_model: str | None = None
    deep_model: str | None = None
    anthropic_api_key: str | None = None

    # Local object store root (MVP) / uploads.
    storage_dir: str = str(ROOT / "eai_storage")

    # Persistent LLM cache file (spec §9). Set to data/eai/llm_cache.json in CI so
    # the daily run only pays for new/changed calls. Empty = no persistent cache.
    llm_cache_file: str | None = None

    # Directory the DirectoryTranscriptProvider reads committed transcripts from.
    transcript_dir: str = str(ROOT / "data" / "eai" / "transcripts")


@functools.lru_cache
def settings() -> Settings:
    return Settings()


@functools.lru_cache
def _yaml() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def cfg() -> dict[str, Any]:
    """The parsed eai_config.yaml (empty dict if the file is absent)."""
    return _yaml()


def provider_name(kind: str) -> str:
    """Resolve which provider adapter to use for ``kind`` (env > yaml > default)."""
    env = getattr(settings(), f"{kind}_provider", None)
    if env:
        return env
    defaults = {
        "transcript": "mock",
        "financial": "guidance_json",
        "llm": "mock",
        "storage": "local",
    }
    return _yaml().get("providers", {}).get(kind, defaults[kind])


def model_for_tier(tier: str) -> str | None:
    """Concrete model id for a logical tier (spec §8). None if unconfigured."""
    s = settings()
    return {
        "fast": s.fast_model,
        "balanced": s.balanced_model,
        "deep": s.deep_model,
    }.get(tier)


def versions() -> dict[str, str]:
    v = _yaml().get("versions", {})
    return {
        "prompt_version": v.get("prompt_version", "p1"),
        "ontology_version": v.get("ontology_version", "onto1"),
        "score_version": v.get("score_version", "s1"),
    }


def quarter_weights() -> list[float]:
    return list(_yaml().get("quarter_weights", [0.40, 0.30, 0.20, 0.10]))


def classification() -> dict[str, Any]:
    d = {
        "classification_rule_version": "c1",
        "narrative_threshold": 0.60,
        "fundamental_threshold": 0.60,
        "minimum_verified_kpi_count": 3,
        "minimum_company_breadth": 3,
    }
    d.update(_yaml().get("classification", {}))
    return d


def theme_score_weights() -> dict[str, float]:
    d = {
        "breadth": 25,
        "momentum": 20,
        "intensity": 15,
        "persistence": 10,
        "value_chain_confirmation": 15,
        "numeric_confirmation": 15,
    }
    d.update(_yaml().get("theme_score_weights", {}))
    return d


def incremental_score_weights() -> dict[str, float]:
    d = {
        "new_topic_contribution": 20,
        "new_value_chain_position": 15,
        "independent_confirmation": 15,
        "contradictory_signal_contribution": 15,
        "numeric_specificity": 10,
        "transcript_information_density": 10,
        "existing_universe_redundancy": -10,
        "data_availability_reliability": 15,
    }
    d.update(_yaml().get("incremental_score_weights", {}))
    return d


def universe() -> list[dict[str, Any]]:
    return list(_yaml().get("universe", []))


def maturity() -> dict[str, Any]:
    d = {"high_conviction_min_companies": 20, "mvp_label": "Prototype / Insufficient Breadth"}
    d.update(_yaml().get("maturity", {}))
    return d


def reset_cache() -> None:
    """Clear cached config/settings (used by tests that patch env/yaml)."""
    _yaml.cache_clear()
    settings.cache_clear()
