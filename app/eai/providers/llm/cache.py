"""Persistent LLM response cache (spec §9).

Wraps any LLMProvider. Same (tier, model, prompt_version, ontology_version,
system+user) → reuse the stored structured result instead of paying for the
call again. The cache is a plain JSON file that can be committed to the repo,
so the daily GitHub Actions run only pays for NEW/changed conference calls —
unchanged ones are cache hits at $0 (spec §9, §22).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ... import config
from ..llm.base import LLMResult
from ...services.textnorm import sha256

_lock = threading.Lock()


class CachedLLMProvider:
    def __init__(self, inner, cache_path: str | Path) -> None:
        self.inner = inner
        self.name = f"cache({inner.name})"
        self.capabilities = inner.capabilities
        self.path = Path(cache_path)
        self._store: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._store = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._store = {}

    def _key(self, tier: str, system: str, user: str) -> str:
        v = config.versions()
        model = config.model_for_tier(tier) or getattr(self.inner, "name", "?")
        return sha256(f"{tier}|{model}|{v['prompt_version']}|{v['ontology_version']}|"
                      f"{system}|{user}")

    def complete(self, tier, system, user, *, schema=None, temperature=None,
                 cache_prefix=False) -> LLMResult:
        key = self._key(tier, system, user)
        hit = self._store.get(key)
        if hit is not None:
            return LLMResult(
                data=hit["data"], model_id=hit.get("model_id", "cache"),
                provider=self.inner.name, input_tokens=0, output_tokens=0,
                estimated_cost=0.0, processing_time=0.0, cache_hit=True, status="ok")

        result = self.inner.complete(tier, system, user, schema=schema,
                                     temperature=temperature, cache_prefix=cache_prefix)
        if result.status == "ok":
            with _lock:
                self._store[key] = {"data": result.data, "model_id": result.model_id}
                self._flush()
        return result

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._store, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
