"""Transcript preprocessing: paragraphs, sections, speakers, Q&A links, chunks.

Pure functions (no DB, no network) so they are fully unit-testable offline
(spec §7, §23). Two entry points produce the same ``ParsedTranscript``:

  * ``parse_structured`` — for providers that already deliver speaker turns
    (mock provider, .json upload).
  * ``parse_plaintext``  — heuristic parser for raw .txt transcripts.

Then ``build_chunks`` groups paragraphs into speaker/semantic units without
ever splitting mid-sentence, keeping each chunk's paragraph_ids and speaker
info (spec §7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import textnorm

# ------------------------------- data types --------------------------------


@dataclass
class ParsedParagraph:
    paragraph_id: str
    section_type: str            # prepared_remarks | qa
    speaker_name: str | None
    speaker_role: str | None     # operator|ceo|cfo|other_management|analyst
    speaker_company: str | None
    sequence_number: int
    exact_text_en: str
    normalized_text_en: str
    preceding_question_id: str | None = None
    answer_to_question_id: str | None = None
    paragraph_hash: str = ""


@dataclass
class ParsedTranscript:
    ticker: str
    fiscal_year: int
    fiscal_quarter: int
    call_date: str | None
    paragraphs: list[ParsedParagraph] = field(default_factory=list)

    @property
    def speakers(self) -> list[dict]:
        seen: dict[tuple, dict] = {}
        for p in self.paragraphs:
            key = (p.speaker_name, p.speaker_role, p.speaker_company)
            if p.speaker_name and key not in seen:
                seen[key] = {
                    "name": p.speaker_name,
                    "role": p.speaker_role or "other_management",
                    "company": p.speaker_company,
                }
        return list(seen.values())


@dataclass
class Chunk:
    chunk_ref: str
    section_type: str
    paragraph_ids: list[str]
    text: str
    speakers: list[str]


# ------------------------------- role mapping ------------------------------

_ROLE_CODE = {
    "operator": "OP",
    "ceo": "CEO",
    "cfo": "CFO",
    "other_management": "MGMT",
    "analyst": "ANALYST",
}

_SECTION_CODE = {"prepared_remarks": "PR", "qa": "QA"}


def role_from_title(title: str | None, section: str | None = None) -> str:
    """Best-effort speaker-role classification from a title/label string.

    Exec/operator keywords win. For anything else, the section is the t[i]e-breaker:
    an unknown speaker in Q&A is almost always an analyst (execs there carry
    titles), whereas in Prepared Remarks it defaults to other_management.
    """
    if not title:
        return "analyst" if section == "qa" else "other_management"
    t = title.lower()
    if "operator" in t:
        return "operator"
    if "chief executive" in t or re.search(r"\bceo\b", t):
        return "ceo"
    if "chief financial" in t or re.search(r"\bcfo\b", t):
        return "cfo"
    if any(k in t for k in ("analyst", "research", "securities", "capital", "& co",
                            "bank", "partners", "markets")):
        return "analyst"
    return "analyst" if section == "qa" else "other_management"


def _make_pid(ticker: str, fy: int, fq: int, section: str, role: str, seq: int) -> str:
    return f"{ticker}_{fy}Q{fq}_{_SECTION_CODE[section]}_{_ROLE_CODE.get(role, 'MGMT')}_{seq:03d}"


# ------------------------------- structured --------------------------------


def parse_structured(raw: dict) -> ParsedTranscript:
    """Parse a provider's structured transcript dict into paragraphs.

    Expected shape::

        {
          "ticker": "NVDA", "fiscal_year": 2026, "fiscal_quarter": 2,
          "call_date": "2026-05-28",
          "sections": [
            {"section_type": "prepared_remarks",
             "turns": [{"speaker_name": "...", "speaker_role": "ceo",
                        "speaker_company": null, "text": "..."}, ...]},
            {"section_type": "qa", "turns": [...]}
          ]
        }
    """
    ticker = raw["ticker"]
    fy = int(raw["fiscal_year"])
    fq = int(raw["fiscal_quarter"])
    out = ParsedTranscript(ticker, fy, fq, raw.get("call_date"))

    last_question_id: str | None = None

    for section in raw.get("sections", []):
        section_type = section["section_type"]
        seq = 0  # paragraph number runs sequentially within the section (spec §7)
        for turn in section.get("turns", []):
            role = turn.get("speaker_role") or role_from_title(
                turn.get("speaker_title"), section_type)
            seq += 1
            pid = _make_pid(ticker, fy, fq, section_type, role, seq)
            exact = turn["text"]
            norm = textnorm.normalize(exact)
            para = ParsedParagraph(
                paragraph_id=pid,
                section_type=section_type,
                speaker_name=turn.get("speaker_name"),
                speaker_role=role,
                speaker_company=turn.get("speaker_company"),
                sequence_number=len(out.paragraphs) + 1,
                exact_text_en=exact,
                normalized_text_en=norm,
                paragraph_hash=textnorm.paragraph_hash(norm),
            )
            # Q&A relationship (spec §7): analyst turn = question; management
            # answers link back to the most recent question.
            if section_type == "qa":
                if role == "analyst":
                    last_question_id = pid
                elif role in ("ceo", "cfo", "other_management") and last_question_id:
                    para.answer_to_question_id = last_question_id
                    para.preceding_question_id = last_question_id
            out.paragraphs.append(para)
    return out


# ------------------------------- plaintext ---------------------------------

_QA_MARKERS = re.compile(
    r"(question[\s-]and[\s-]answer|q\s*&\s*a|questions?\s+and\s+answers?)", re.I
)
# "Colette Kress -- Chief Financial Officer" / "Operator"
_SPEAKER_LINE = re.compile(r"^\s*([A-Z][\w.\-'’ ]{1,60}?)\s*(?:--|—|–|:)\s*(.*)$")


def parse_plaintext(text: str, ticker: str, fiscal_year: int, fiscal_quarter: int,
                    call_date: str | None = None) -> ParsedTranscript:
    """Heuristically parse a raw text transcript.

    Splits Prepared Remarks vs Q&A on a Q&A marker line, detects speaker turns
    by a ``Name -- Title`` (or ``Name:``) pattern, and accumulates each
    speaker's text until the next speaker line. Conservative by design — the
    resulting paragraphs still carry the exact original text.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    section_type = "prepared_remarks"
    out = ParsedTranscript(ticker, int(fiscal_year), int(fiscal_quarter), call_date)

    cur_name: str | None = None
    cur_role: str | None = None
    cur_buf: list[str] = []
    seq_in_section = {"prepared_remarks": 0, "qa": 0}
    last_question_id: str | None = None

    def flush():
        nonlocal cur_buf, last_question_id
        if cur_name is None or not "".join(cur_buf).strip():
            cur_buf = []
            return
        role = cur_role or "other_management"
        seq_in_section[section_type] += 1
        pid = _make_pid(ticker, int(fiscal_year), int(fiscal_quarter), section_type, role,
                        seq_in_section[section_type])
        exact = "\n".join(cur_buf).strip()
        norm = textnorm.normalize(exact)
        para = ParsedParagraph(
            paragraph_id=pid, section_type=section_type, speaker_name=cur_name,
            speaker_role=role, speaker_company=None, sequence_number=len(out.paragraphs) + 1,
            exact_text_en=exact, normalized_text_en=norm,
            paragraph_hash=textnorm.paragraph_hash(norm),
        )
        if section_type == "qa":
            if role == "analyst":
                last_question_id = pid
            elif last_question_id:
                para.answer_to_question_id = last_question_id
                para.preceding_question_id = last_question_id
        out.paragraphs.append(para)
        cur_buf = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if section_type == "prepared_remarks" and _QA_MARKERS.search(line) and len(line) < 80:
            flush()
            section_type = "qa"
            cur_name, cur_role = None, None
            continue
        m = _SPEAKER_LINE.match(line)
        if m and len(m.group(1).split()) <= 6:
            flush()
            name = m.group(1).strip()
            title = m.group(2).strip()
            cur_name = name
            if name.lower() == "operator":
                cur_role = "operator"
            else:
                cur_role = role_from_title(title, section_type)
            cur_buf = []  # title is speaker metadata, not paragraph body
            continue
        cur_buf.append(line)
    flush()
    return out


# ------------------------------- chunking ----------------------------------


def build_chunks(parsed: ParsedTranscript) -> list[Chunk]:
    """Group paragraphs into chunks by speaker/semantic unit (spec §7).

    Prepared Remarks: one chunk per speaker turn. Q&A: group each analyst
    question with the management answers that follow it, so the chunk carries
    the full question→answer context. Never splits a paragraph.
    """
    chunks: list[Chunk] = []
    i = 0
    paras = parsed.paragraphs
    n = len(paras)
    while i < n:
        p = paras[i]
        if p.section_type == "prepared_remarks":
            chunks.append(Chunk(
                chunk_ref=p.paragraph_id, section_type="prepared_remarks",
                paragraph_ids=[p.paragraph_id], text=p.exact_text_en,
                speakers=[p.speaker_name or ""],
            ))
            i += 1
        else:  # qa: gather question + following answers until next question/operator
            group = [p]
            j = i + 1
            if p.speaker_role == "analyst":
                while j < n and paras[j].section_type == "qa" and paras[j].speaker_role in (
                    "ceo", "cfo", "other_management",
                ):
                    group.append(paras[j])
                    j += 1
            chunks.append(Chunk(
                chunk_ref=group[0].paragraph_id, section_type="qa",
                paragraph_ids=[g.paragraph_id for g in group],
                text="\n\n".join(g.exact_text_en for g in group),
                speakers=[g.speaker_name or "" for g in group],
            ))
            i = j if j > i else i + 1
    return chunks
