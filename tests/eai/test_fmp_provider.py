"""FMP-style transcript API provider, verified with a mocked HTTP layer.

No network: we monkeypatch the provider's _get so the parsing/mapping and the
downstream plaintext parsing are checked deterministically (spec §6.1, §23).
"""

from __future__ import annotations

from app.eai.providers.transcript.fmp import FMPTranscriptProvider
from app.eai.services import preprocess

LIST = [[3, 2026, "2026-08-27 17:00:00"], [2, 2026, "2026-05-28 17:00:00"],
        [1, 2026, "2026-02-26 17:00:00"], [4, 2025, "2025-11-20 17:00:00"],
        [3, 2025, "2025-08-27 17:00:00"]]

CONTENT = (
    "Operator: Good morning and welcome to the NVIDIA earnings call.\n"
    "Jensen Huang: Data center demand was exceptional and we remain supply constrained.\n"
    "Colette Kress: Revenue was $30.0 billion, up 122% year over year.\n"
    "Question-and-Answer Session\n"
    "Vivek Arya: Can you talk about HBM supply?\n"
    "Colette Kress: HBM supply is improving into next quarter.\n"
)


def _provider():
    p = FMPTranscriptProvider(api_key="test-key", base="https://example.test")
    def fake_get(url, params):
        if "/api/v4/earning_call_transcript" in url:
            return LIST
        return [{"symbol": "NVDA", "quarter": params["quarter"], "year": params["year"],
                 "date": "2026-08-27 17:00:00", "content": CONTENT}]
    p._get = fake_get  # type: ignore[assignment]
    return p


def test_list_available_sorted_and_capped():
    p = _provider()
    refs = p.list_available("NVDA")
    assert len(refs) == 4                       # capped to transcript_max_quarters
    assert (refs[0].fiscal_year, refs[0].fiscal_quarter) == (2026, 3)  # newest first
    assert all(r.source == "fmp" for r in refs)


def test_list_available_empty_without_key():
    p = FMPTranscriptProvider(api_key=None)
    assert p.list_available("NVDA") == []


def test_fetch_maps_to_raw_transcript():
    p = _provider()
    ref = p.list_available("NVDA")[0]
    raw = p.fetch(ref)
    assert raw.raw_text and "Data center demand" in raw.raw_text
    assert raw.call_date == "2026-08-27"
    assert raw.source == "fmp"
    assert raw.checksum()                       # dedup key


def test_api_content_parses_into_sections_and_speakers():
    p = _provider()
    raw = p.fetch(p.list_available("NVDA")[0])
    parsed = preprocess.parse_plaintext(raw.raw_text, "NVDA", 2026, 3)
    sections = {para.section_type for para in parsed.paragraphs}
    assert sections == {"prepared_remarks", "qa"}
    # inline "Name: body" text is kept as the paragraph body (not dropped)
    jensen = next(p for p in parsed.paragraphs if "Data center demand" in p.exact_text_en)
    assert jensen.section_type == "prepared_remarks"
    operator = next(p for p in parsed.paragraphs if p.speaker_role == "operator")
    assert "welcome" in operator.exact_text_en.lower()
    # Q&A answer links back to the analyst question
    ans = [p for p in parsed.paragraphs if p.section_type == "qa"
           and "HBM supply is improving" in p.exact_text_en][0]
    assert ans.answer_to_question_id is not None
