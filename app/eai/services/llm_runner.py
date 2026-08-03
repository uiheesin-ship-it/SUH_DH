"""Run an LLM stage with validation → repair → retry, and usage accounting.

Validation order (spec §15): provider structured output → Pydantic schema →
enum/range (enforced by the schema) → (evidence checked later in code). On a
validation failure we send a *repair request* containing only the errors, up
to ``max_retries``; if still invalid we return status failed/needs_manual_review
and never fabricate data (spec §8, §15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from .. import config
from ..providers.llm import LLMUnavailable
from ..providers.llm.base import LLMResult

T = TypeVar("T", bound=BaseModel)


@dataclass
class StageOutcome:
    model: BaseModel | None
    status: str                      # ok | failed | needs_manual_review | unavailable
    usage: list[dict] = field(default_factory=list)
    error: str | None = None


def run_stage(provider, tier: str, system: str, user: str, schema_model: Type[T], *,
              stage: str, temperature: float | None = None) -> StageOutcome:
    max_retries = int(config.cfg().get("llm", {}).get("max_retries", 3))
    schema = schema_model.model_json_schema()
    versions = config.versions()
    usages: list[dict] = []
    cur_user = user
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        try:
            result: LLMResult = provider.complete(
                tier, system, cur_user, schema=schema, temperature=temperature,
                cache_prefix=True,
            )
        except LLMUnavailable as e:
            # No usable LLM — surface clearly, never fake analysis (spec §8).
            return StageOutcome(model=None, status="unavailable", usage=usages, error=str(e))

        usages.append(_usage_row(result, stage, versions, attempt))

        try:
            model = schema_model.model_validate(result.data)
            return StageOutcome(model=model, status="ok", usage=usages)
        except ValidationError as ve:
            last_error = _short_errors(ve)
            cur_user = (
                f"{user}\n\nYour previous JSON was invalid. Fix ONLY these errors and "
                f"return valid {schema_model.__name__} JSON again:\n{last_error}"
            )

    status = "needs_manual_review"
    return StageOutcome(model=None, status=status, usage=usages, error=last_error)


def _usage_row(result: LLMResult, stage: str, versions: dict, attempt: int) -> dict:
    return {
        "model_id": result.model_id, "provider": result.provider, "stage": stage,
        "prompt_version": versions["prompt_version"],
        "ontology_version": versions["ontology_version"],
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "estimated_cost": result.estimated_cost, "processing_time": result.processing_time,
        "retry_count": attempt, "cache_hit": result.cache_hit, "status": result.status,
    }


def _short_errors(ve: ValidationError) -> str:
    lines = []
    for err in ve.errors()[:12]:
        loc = ".".join(str(x) for x in err["loc"])
        lines.append(f"- {loc}: {err['msg']}")
    return "\n".join(lines)
