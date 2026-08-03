"""Versioned prompts (spec §9, §11).

Each stage builds a fixed system prefix (instructions, ontology, evidence
rules — cacheable) and a variable user body carrying the data. The body embeds
a ```json INPUT block``` so the deterministic Mock provider can consume the
exact same prompt a real provider gets. Prompt text is tagged with a version
so analyses reproduce.
"""

from __future__ import annotations

import json

from .. import config, ontology

_EVIDENCE_RULES = (
    "EVIDENCE RULES: every claim needs >=1 evidence item. Each evidence must set "
    "paragraph_id to a real paragraph and exact_quote_en to a VERBATIM substring "
    "of that paragraph's English text (no paraphrasing). If you cannot support a "
    "claim with an exact quote, set insufficient_evidence=true and omit the claim."
)


def _ontology_brief() -> str:
    lines = [f"- {t['topic_id']}: {t['name_en']} ({t['category']})"
             for t in ontology.topics().values()]
    return "TOPIC ONTOLOGY (use topic_id from this list; propose new only if none fit):\n" + \
        "\n".join(lines)


def _system(role: str) -> str:
    v = config.versions()
    return (
        f"You are an equity-research analyst assistant. {role}\n"
        f"Analyze the ENGLISH source text; write Korean summaries where asked.\n"
        f"{_ontology_brief()}\n{_EVIDENCE_RULES}\n"
        f"[prompt_version={v['prompt_version']} ontology_version={v['ontology_version']}]"
    )


def _wrap(instruction: str, payload: dict) -> str:
    return f"{instruction}\n\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def chunk_extraction(meta: dict, paragraphs: list[dict]) -> tuple[str, str]:
    system = _system("Extract topic mentions from one transcript chunk.")
    user = _wrap(
        "Extract all topic mentions from these paragraphs. Return ChunkExtraction JSON. "
        "Separate management-initiated vs analyst-initiated; mark section_type correctly; "
        "give direction/intensity/confidence and exact-quote evidence.",
        {"meta": meta, "paragraphs": paragraphs},
    )
    return system, user


def call_synthesis(meta: dict, mentions: list[dict]) -> tuple[str, str]:
    system = _system("Synthesize one earnings call from its topic mentions.")
    user = _wrap(
        "Summarize the call (Korean executive summary) and separate prepared-remarks "
        "emphasis from Q&A, and narrative tone from the numbers. Return CallSynthesis JSON.",
        {"meta": meta, "mentions": mentions},
    )
    return system, user


def qoq_comparison(meta: dict, current: list[dict], previous: list[dict]) -> tuple[str, str]:
    system = _system("Compare two consecutive quarters for one company.")
    user = _wrap(
        "Identify newly-emerging / accelerating / persistent / weakening / disappeared topics "
        "and tone & guidance changes. Do NOT judge by raw mention count alone. Return "
        "QoQComparison JSON.",
        {"meta": meta, "current_mentions": current, "previous_mentions": previous},
    )
    return system, user


def cross_company(topic_groups: dict) -> tuple[str, str]:
    system = _system("Synthesize cross-company themes from many companies' mentions.")
    user = _wrap(
        "Group the signals into cross-company themes. Weight independent confirmation by "
        "DIFFERENT companies over repeated mentions by one. Return CrossCompanyThemeSet JSON.",
        {"topic_groups": topic_groups},
    )
    return system, user


def investment_theme(theme: dict) -> tuple[str, str]:
    system = _system("Draft an investment theme with beneficiaries and counter-evidence.")
    user = _wrap(
        "Write the investment theme: why emerging, beneficiaries, value-chain transmission, "
        "numeric vs narrative-only points, contradictory evidence, unconfirmed assumptions, "
        "risks, checkpoints. Return InvestmentThemeLLM JSON. Conviction is decided in code.",
        {"theme": theme},
    )
    return system, user
