"""Directory transcript provider (spec §6.1) — the auto-update drop folder.

Reads transcripts committed under ``data/eai/transcripts/`` (configurable via
EAI_TRANSCRIPT_DIR). Drop a new ``<TICKER>_<FY>Q<Q>.json`` (canonical
sections→turns shape) or ``.txt`` file into that folder, commit it, and the
daily GitHub Actions run ingests + analyzes it automatically — no paid API
required. A licensed transcript API can be added later as another provider.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ... import config
from .base import RawTranscript, TranscriptRef

_NAME = re.compile(r"^(?P<ticker>[A-Za-z.\-]+)_(?P<fy>\d{4})Q(?P<fq>[1-4])\.(json|txt)$")


class DirectoryTranscriptProvider:
    name = "directory"

    def __init__(self, directory: str | Path | None = None) -> None:
        self.dir = Path(directory or config.settings().transcript_dir)

    def list_available(self, ticker: str, since=None) -> list[TranscriptRef]:
        refs: list[TranscriptRef] = []
        if not self.dir.exists():
            return refs
        for path in sorted(self.dir.glob(f"{ticker.upper()}_*")):
            m = _NAME.match(path.name)
            if not m or m.group("ticker").upper() != ticker.upper():
                continue
            refs.append(TranscriptRef(
                ticker=ticker.upper(), fiscal_year=int(m.group("fy")),
                fiscal_quarter=int(m.group("fq")), source="directory",
                source_identifier=path.name))
        return refs

    def fetch(self, ref: TranscriptRef) -> RawTranscript:
        path = self.dir / (ref.source_identifier or "")
        common = dict(ticker=ref.ticker, fiscal_year=ref.fiscal_year,
                      fiscal_quarter=ref.fiscal_quarter, source="directory",
                      license_note="committed transcript file")
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return RawTranscript(
                call_date=data.get("call_date"), company=data.get("company"),
                published_at=data.get("published_at") or data.get("call_date"),
                structured={"sections": data["sections"]}, **common)
        return RawTranscript(raw_text=path.read_text(encoding="utf-8"), **common)
