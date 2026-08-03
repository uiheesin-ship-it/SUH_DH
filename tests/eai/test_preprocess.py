"""Offline unit tests for transcript preprocessing (spec §7, §23)."""

from app.eai.services import preprocess
from app.eai.services.textnorm import normalize, paragraph_hash


STRUCTURED = {
    "ticker": "NVDA", "fiscal_year": 2026, "fiscal_quarter": 2, "call_date": "2026-05-28",
    "sections": [
        {"section_type": "prepared_remarks", "turns": [
            {"speaker_name": "Operator", "speaker_role": "operator", "text": "Welcome."},
            {"speaker_name": "Jensen Huang", "speaker_role": "ceo",
             "text": "Data center demand is exceptional. We are supply constrained."},
            {"speaker_name": "Colette Kress", "speaker_role": "cfo",
             "text": "Revenue was $30.0 billion, up 122% year over year."},
        ]},
        {"section_type": "qa", "turns": [
            {"speaker_name": "Analyst A", "speaker_role": "analyst",
             "speaker_company": "Big Bank", "text": "Can you talk about HBM supply?"},
            {"speaker_name": "Colette Kress", "speaker_role": "cfo",
             "text": "HBM supply remains tight but improving into next quarter."},
        ]},
    ],
}


def test_paragraph_id_format_and_sections():
    parsed = preprocess.parse_structured(STRUCTURED)
    pids = [p.paragraph_id for p in parsed.paragraphs]
    # section-sequential numbering across speakers (spec §7: QA_ANALYST_014, QA_CFO_015)
    assert "NVDA_2026Q2_PR_OP_001" in pids
    assert "NVDA_2026Q2_PR_CEO_002" in pids
    assert "NVDA_2026Q2_PR_CFO_003" in pids
    assert "NVDA_2026Q2_QA_ANALYST_001" in pids
    assert "NVDA_2026Q2_QA_CFO_002" in pids
    # sections correctly labeled
    pr = [p for p in parsed.paragraphs if p.section_type == "prepared_remarks"]
    qa = [p for p in parsed.paragraphs if p.section_type == "qa"]
    assert len(pr) == 3 and len(qa) == 2


def test_qa_question_answer_linkage():
    parsed = preprocess.parse_structured(STRUCTURED)
    answer = next(p for p in parsed.paragraphs
                  if p.section_type == "qa" and p.speaker_role == "cfo")
    question = next(p for p in parsed.paragraphs
                    if p.section_type == "qa" and p.speaker_role == "analyst")
    assert answer.answer_to_question_id == question.paragraph_id


def test_hash_and_normalization_stable():
    parsed = preprocess.parse_structured(STRUCTURED)
    p = parsed.paragraphs[1]
    assert p.paragraph_hash == paragraph_hash(normalize(p.exact_text_en))


def test_speakers_deduplicated():
    parsed = preprocess.parse_structured(STRUCTURED)
    roles = {s["role"] for s in parsed.speakers}
    assert {"operator", "ceo", "cfo", "analyst"} <= roles


def test_chunks_group_qa_question_with_answer_and_never_empty():
    parsed = preprocess.parse_structured(STRUCTURED)
    chunks = preprocess.build_chunks(parsed)
    qa_chunk = next(c for c in chunks if c.section_type == "qa")
    # the analyst question chunk should include the following CFO answer
    assert len(qa_chunk.paragraph_ids) == 2
    assert all(c.text.strip() for c in chunks)


def test_plaintext_parser_splits_prepared_and_qa():
    text = (
        "Operator -- Operator\n"
        "Good morning and welcome to the call.\n"
        "Tim Cook -- Chief Executive Officer\n"
        "iPhone demand was strong this quarter.\n"
        "Questions and Answers\n"
        "Analyst -- Morgan Stanley\n"
        "How is Services growth trending?\n"
        "Luca Maestri -- Chief Financial Officer\n"
        "Services grew double digits again.\n"
    )
    parsed = preprocess.parse_plaintext(text, "AAPL", 2026, 3)
    sections = {p.section_type for p in parsed.paragraphs}
    assert sections == {"prepared_remarks", "qa"}
    ceo = next(p for p in parsed.paragraphs if p.speaker_role == "ceo")
    assert "iPhone demand" in ceo.exact_text_en
    # answer linked to the analyst question in Q&A
    ans = next(p for p in parsed.paragraphs if p.section_type == "qa" and p.speaker_role == "cfo")
    assert ans.answer_to_question_id is not None
