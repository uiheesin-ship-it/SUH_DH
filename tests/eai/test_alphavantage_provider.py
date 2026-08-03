"""Alpha Vantage transcript provider, verified with a mocked HTTP layer.

Confirms EARNINGS-based listing, rate-limit handling, and that the structured
transcript maps into Prepared/Q&A sections with question↔answer linkage — all
offline (spec §6.1, §23).
"""

from __future__ import annotations

from app.eai.providers.transcript.alphavantage import AlphaVantageTranscriptProvider
from app.eai.services import preprocess

EARNINGS = {"symbol": "NVDA", "quarterlyEarnings": [
    {"fiscalDateEnding": "2026-06-30"}, {"fiscalDateEnding": "2026-03-31"},
    {"fiscalDateEnding": "2025-12-31"}, {"fiscalDateEnding": "2025-09-30"},
    {"fiscalDateEnding": "2025-06-30"}]}

TRANSCRIPT = {"symbol": "NVDA", "quarter": "2026Q2", "transcript": [
    {"speaker": "Operator", "title": "", "content": "Welcome to the NVIDIA call."},
    {"speaker": "Jensen Huang", "title": "President and CEO",
     "content": "Data center demand was exceptional and we remain supply constrained."},
    {"speaker": "Colette Kress", "title": "EVP and CFO",
     "content": "Revenue was $30.0 billion, up 122% year over year."},
    {"speaker": "Operator", "title": "",
     "content": "We will now begin the question-and-answer session."},
    {"speaker": "Vivek Arya", "title": "Bank of America - Analyst",
     "content": "How is HBM supply trending?"},
    {"speaker": "Colette Kress", "title": "EVP and CFO",
     "content": "HBM supply is improving into next quarter."}]}


def _provider(earnings=EARNINGS, transcript=TRANSCRIPT):
    p = AlphaVantageTranscriptProvider(api_key="k", base="https://av.test")
    def fake_get(params):
        if params["function"] == "EARNINGS":
            return earnings
        return transcript
    p._get = fake_get  # type: ignore[assignment]
    return p


def test_list_available_from_earnings_capped_and_sorted():
    refs = _provider().list_available("NVDA")
    assert len(refs) == 4                                   # capped to max_quarters
    assert (refs[0].fiscal_year, refs[0].fiscal_quarter) == (2026, 2)  # newest first
    assert (refs[1].fiscal_year, refs[1].fiscal_quarter) == (2026, 1)


def test_rate_limit_message_yields_empty_list():
    p = _provider(earnings={"Information": "rate limit reached"})
    assert p.list_available("NVDA") == []


def test_no_key_returns_empty():
    assert AlphaVantageTranscriptProvider(api_key=None).list_available("NVDA") == []


def test_fetch_maps_structured_sections_and_roles():
    p = _provider()
    ref = p.list_available("NVDA")[0]
    raw = p.fetch(ref)
    assert raw.structured and raw.source == "alphavantage"

    parsed = preprocess.parse_structured({
        "ticker": "NVDA", "fiscal_year": 2026, "fiscal_quarter": 2,
        "sections": raw.structured["sections"]})
    sections = {para.section_type for para in parsed.paragraphs}
    assert sections == {"prepared_remarks", "qa"}

    ceo = next(p for p in parsed.paragraphs if p.speaker_role == "ceo")
    assert "Data center demand" in ceo.exact_text_en and ceo.section_type == "prepared_remarks"

    # Q&A answer (CFO) links back to the analyst question
    answer = next(p for p in parsed.paragraphs
                  if p.section_type == "qa" and p.speaker_role == "cfo")
    question = next(p for p in parsed.paragraphs
                    if p.section_type == "qa" and p.speaker_role == "analyst")
    assert answer.answer_to_question_id == question.paragraph_id


def test_empty_transcript_raises():
    import pytest
    p = _provider(transcript={"symbol": "NVDA", "quarter": "2026Q2", "transcript": []})
    with pytest.raises(ValueError):
        p.fetch(p.list_available("NVDA")[0])
