"""Deterministic Mock LLM provider — for offline tests only (spec §8, §23).

This is a *test double*, never a substitute presented to users as real
analysis. It reads the structured INPUT payload embedded in the prompt and
returns schema-valid output, drawing evidence quotes as **exact substrings**
of the input paragraphs so the evidence verifier genuinely validates them.
Every call is recorded with provider="mock" so the UI can flag it.
"""

from __future__ import annotations

import json
import re
import time

from ... import ontology
from .base import Capabilities, LLMResult

_POS = ("strong", "growth", "record", "exceptional", "robust", "accelerat", "beat", "up ",
        "increase", "healthy", "momentum", "demand")
_NEG = ("weak", "declin", "soft", "pressure", "headwind", "slow", "down ", "cautious",
        "deteriorat", "miss", "constraint", "shortfall")

# very small keyword→topic map so the mock can attach a semantic topic id
_KEYWORDS = {
    "data center": "data_center_investment",
    "demand": "demand_growth",
    "supply": "supply_constraint",
    "hbm": "hbm",
    "inventory": "inventory_build",
    "price": "pricing_power",
    "pricing": "pricing_power",
    "capex": "capital_expenditure",
    "capital expenditure": "capital_expenditure",
    "backlog": "backlog",
    "order": "order_growth",
    "credit": "credit_deterioration",
    "delinquenc": "delinquency",
    "consumer": "consumer_weakness",
    "hiring": "hiring",
    "wage": "wage_pressure",
    "ai ": "ai_adoption",
    "cloud": "cloud_optimization",
    "power": "power_demand",
    "tariff": "tariffs",
    "margin": "pricing_vs_cost",
}


def _sentence_with(text: str, needle: str) -> str | None:
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if needle.lower() in sent.lower():
            return sent.strip()
    return None


def _direction(text: str) -> tuple[str, int]:
    t = text.lower()
    pos = sum(t.count(w) for w in _POS)
    neg = sum(t.count(w) for w in _NEG)
    if pos and neg:
        return "mixed", 3
    if pos > neg:
        return "positive", min(5, 2 + pos)
    if neg > pos:
        return "negative", min(5, 2 + neg)
    return "neutral", 1


class MockLLMProvider:
    name = "mock"
    capabilities = Capabilities(
        supports_structured_output=True, supports_tool_schema=True,
        supports_prompt_caching=False, supports_batch=False,
        supports_temperature=True, supports_thinking=False, maximum_context_length=200_000,
    )

    def complete(self, tier, system, user, *, schema=None, temperature=None,
                 cache_prefix=False) -> LLMResult:
        t0 = time.time()
        payload = _extract_input(user)
        title = (schema or {}).get("title", "")
        if title == "ChunkExtraction":
            data = self._chunk(payload)
        elif title == "CallSynthesis":
            data = self._call(payload)
        elif title == "QoQComparison":
            data = self._qoq(payload)
        elif title == "CrossCompanyThemeSet":
            data = self._cross(payload)
        elif title == "InvestmentThemeLLM":
            data = self._invest(payload)
        else:
            data = {}
        toks = max(1, len(user) // 4)
        return LLMResult(
            data=data, model_id=f"mock-{tier}", provider="mock",
            input_tokens=toks, output_tokens=max(1, len(json.dumps(data)) // 4),
            estimated_cost=0.0, processing_time=time.time() - t0, status="ok",
        )

    # ---- stage builders --------------------------------------------------
    def _chunk(self, payload: dict) -> dict:
        mentions = []
        meta = payload.get("meta", {})
        for para in payload.get("paragraphs", []):
            text = para.get("text", "")
            low = text.lower()
            for kw, topic_id in _KEYWORDS.items():
                if kw in low:
                    quote = _sentence_with(text, kw) or text[:180]
                    topic = ontology.get(topic_id) or {
                        "name_en": topic_id, "name_ko": topic_id, "category": "general"}
                    direction, intensity = _direction(quote)
                    role = para.get("speaker_role")
                    section = para.get("section_type", "prepared_remarks")
                    mentions.append({
                        "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
                        "fiscal_year": meta.get("fiscal_year", 2026),
                        "fiscal_quarter": meta.get("fiscal_quarter", 1),
                        "call_date": meta.get("call_date"),
                        "section_type": section,
                        "speaker_name": para.get("speaker_name"),
                        "speaker_role": role if role in
                        ("operator", "ceo", "cfo", "other_management", "analyst") else None,
                        "topic_id": topic_id, "topic_name_en": topic["name_en"],
                        "topic_name_ko": topic["name_ko"], "topic_category": topic["category"],
                        "direction": direction, "intensity": intensity,
                        "confidence": 0.7,
                        "management_initiated": role in ("ceo", "cfo", "other_management"),
                        "analyst_initiated": role == "analyst",
                        "forward_looking": "expect" in low or "next" in low or "guidance" in low,
                        "backward_looking": "last" in low or "prior" in low,
                        "numeric_support": bool(re.search(r"\d", quote)),
                        "guidance_related": "guidance" in low or "expect" in low,
                        "demand_related": "demand" in low,
                        "pricing_related": "price" in low or "pricing" in low,
                        "capex_related": "capex" in low or "capital" in low,
                        "inventory_related": "inventory" in low,
                        "employment_related": "hiring" in low or "wage" in low,
                        "risk_related": "risk" in low or "headwind" in low,
                        "summary_ko": f"{topic['name_ko']} 관련 발언",
                        "evidence": [{
                            "paragraph_id": para.get("paragraph_id"),
                            "exact_quote_en": quote,
                            "translation_ko": None,
                            "speaker_role": role if role in
                            ("operator", "ceo", "cfo", "other_management", "analyst") else None,
                            "section_type": section,
                            "evidence_reason": f"mentions {kw}",
                        }],
                        "insufficient_evidence": False,
                    })
                    break  # one topic per paragraph for the mock
        return {"mentions": mentions}

    def _call(self, payload: dict) -> dict:
        mentions = payload.get("mentions", [])
        topics = sorted({m.get("topic_name_en", "") for m in mentions})
        return {
            "executive_summary_ko": f"이번 콜의 주요 주제: {', '.join(topics[:5])} (mock 요약).",
            "key_topics": topics[:8],
            "management_priorities": topics[:3],
            "demand_signals": [m["topic_name_en"] for m in mentions if m.get("demand_related")][:5],
            "pricing_signals": [m["topic_name_en"] for m in mentions if m.get("pricing_related")][:5],
            "capex_signals": [m["topic_name_en"] for m in mentions if m.get("capex_related")][:5],
            "inventory_signals": [m["topic_name_en"] for m in mentions if m.get("inventory_related")][:5],
            "labor_signals": [m["topic_name_en"] for m in mentions if m.get("employment_related")][:5],
            "guidance_signals": [m["topic_name_en"] for m in mentions if m.get("guidance_related")][:5],
            "risks": [m["topic_name_en"] for m in mentions if m.get("risk_related")][:5],
            "analyst_concerns": [m["topic_name_en"] for m in mentions if m.get("analyst_initiated")][:5],
            "evasive_or_weak_answers": [],
            "prepared_vs_qa_gap": "mock: prepared/Q&A 큰 차이 없음",
            "narrative_vs_numbers_gap": "mock: 별도 KPI 확인 필요",
            "key_quotes": [],
        }

    def _qoq(self, payload: dict) -> dict:
        cur = {m.get("topic_id") for m in payload.get("current_mentions", [])}
        prev = {m.get("topic_id") for m in payload.get("previous_mentions", [])}
        return {
            "newly_emerging_topics": sorted(cur - prev),
            "accelerating_topics": sorted(cur & prev),
            "persistent_topics": sorted(cur & prev),
            "weakening_topics": [],
            "disappeared_topics": sorted(prev - cur),
            "tone_changes": "mock: 톤 변화 경미",
            "guidance_changes": None,
            "analyst_question_changes": None,
            "management_emphasis_changes": None,
            "narrative_vs_numbers_gap_changes": None,
            "unresolved_concerns": [],
            "key_kpi_changes": [],
            "evidence": [],
        }

    def _cross(self, payload: dict) -> dict:
        themes = []
        for topic_id, info in payload.get("topic_groups", {}).items():
            topic = ontology.get(topic_id) or {"name_en": topic_id, "name_ko": topic_id}
            themes.append({
                "theme_id": f"theme_{topic_id}",
                "theme_name_en": topic["name_en"],
                "theme_name_ko": topic["name_ko"],
                "theme_description_ko": f"여러 기업에서 관찰된 {topic['name_ko']} 신호 (mock).",
                "value_chain_positions": info.get("value_chain_positions", []),
                "direction": info.get("direction", "neutral"),
                "leading_indicators": [], "lagging_indicators": [],
                "supporting_evidence": [], "contradictory_evidence": [],
            })
        return {"themes": themes}

    def _invest(self, payload: dict) -> dict:
        theme = payload.get("theme", {})
        return {
            "investment_theme": theme.get("theme_name_en", "Theme"),
            "why_it_is_emerging": "복수 기업에서 동일 방향 신호 관찰 (mock).",
            "companies_supporting": theme.get("companies", []),
            "sectors_supporting": theme.get("sectors", []),
            "value_chain_transmission": None,
            "direct_beneficiaries": [], "secondary_beneficiaries": [], "potential_losers": [],
            "management_evidence": [], "numeric_evidence": [], "contradictory_evidence": [],
            "unconfirmed_assumptions": ["KPI 교차검증 필요"],
            "risks": ["표본 기업 수 부족"],
            "indicators_to_monitor": [], "next_quarter_checkpoints": [],
            "suggested_narrative_confirmation_status": "Mixed Signals",
        }


def _extract_input(user: str) -> dict:
    """Pull the ```json INPUT block``` the prompt builder embeds for the mock."""
    m = re.search(r"```json\s*(\{.*\})\s*```", user, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}
