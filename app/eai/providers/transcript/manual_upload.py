"""Manual-upload transcript provider (spec §6.1): .txt / .json / .pdf.

Converts an uploaded file into a canonical RawTranscript. JSON is expected in
the structured shape; TXT is kept as raw_text for the heuristic parser; PDF
text is extracted lazily (pypdf) and treated as raw_text.
"""

from __future__ import annotations

import json

from .base import RawTranscript


def from_upload(*, filename: str, content: bytes, ticker: str, fiscal_year: int,
                fiscal_quarter: int, call_date: str | None = None,
                company: str | None = None) -> RawTranscript:
    name = filename.lower()
    common = dict(ticker=ticker, fiscal_year=int(fiscal_year),
                  fiscal_quarter=int(fiscal_quarter), call_date=call_date,
                  company=company, source="manual_upload",
                  license_note="user-provided upload")

    if name.endswith(".json"):
        data = json.loads(content.decode("utf-8"))
        sections = data.get("sections")
        if sections is None:
            raise ValueError("JSON upload must contain a 'sections' list")
        return RawTranscript(structured={"sections": sections}, **common)

    if name.endswith(".pdf"):
        text = _pdf_to_text(content)
        return RawTranscript(raw_text=text, **common)

    # default: plain text
    return RawTranscript(raw_text=content.decode("utf-8", errors="replace"), **common)


def _pdf_to_text(content: bytes) -> str:
    try:
        from io import BytesIO

        from pypdf import PdfReader  # lazy/optional
    except Exception as e:  # pragma: no cover - optional dep
        raise RuntimeError("PDF support requires the 'pypdf' package") from e
    reader = PdfReader(BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)
