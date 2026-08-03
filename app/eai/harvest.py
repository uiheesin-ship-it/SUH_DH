"""Incremental, resumable, budget-limited transcript harvester (spec §22).

Separates *collection* from *analysis*. Each run fetches at most
``harvest_daily_budget`` API requests (≈20-23, to stay under Alpha Vantage's
free 25/day), writes each transcript to ``data/eai/transcripts/`` as a canonical
JSON file, and records progress in ``data/eai/harvest_state.json``. Because both
the files and the ledger are committed by the workflow:

  * already-collected ticker/quarters are skipped (no repeat API call),
  * a run interrupted mid-way resumes from the ledger next time,
  * the daily free-tier limit is never exceeded.

The analysis step then reads the collected files via the ``directory`` provider.
This module does no LLM work and needs no database — just the transcript
provider + the filesystem — so it is fully unit-testable offline.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .providers.transcript import get_transcript_provider
from .providers.transcript.base import RawTranscript, TranscriptRef


@dataclass
class HarvestResult:
    requests_used: int = 0
    collected: list[str] = field(default_factory=list)   # "TICKER_YYYYQn"
    empty: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0
    budget_exhausted: bool = False
    worklist_done: bool = False

    def as_dict(self) -> dict:
        return {"requests_used": self.requests_used, "collected": self.collected,
                "empty": self.empty, "errors": self.errors, "skipped": self.skipped,
                "budget_exhausted": self.budget_exhausted,
                "worklist_done": self.worklist_done}


def _load_ledger(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tickers": {}, "history": []}


def _save_ledger(path: Path, ledger: dict, now: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if now:
        ledger["updated"] = now
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _serialize(raw: RawTranscript, out_dir: Path, ticker: str, year: int, quarter: int) -> Path:
    """Write a fetched transcript as a directory-provider-readable file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if raw.structured:
        path = out_dir / f"{ticker}_{year}Q{quarter}.json"
        payload = {
            "ticker": ticker, "company": raw.company, "fiscal_year": year,
            "fiscal_quarter": quarter, "call_date": raw.call_date,
            "published_at": raw.published_at, "source": raw.source,
            "license_note": raw.license_note, "sections": raw.structured["sections"],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path
    # plain-text sources (e.g. FMP) → .txt for the directory provider
    path = out_dir / f"{ticker}_{year}Q{quarter}.txt"
    path.write_text(raw.raw_text or "", encoding="utf-8")
    return path


def run_harvest(provider, tickers: list[str], *, out_dir: Path, ledger_path: Path,
                daily_budget: int, quarters_per_ticker: int, now: str | None = None) -> HarvestResult:
    """One budgeted harvest pass. Returns what happened; persists the ledger."""
    ledger = _load_ledger(ledger_path)
    tinfo_all = ledger.setdefault("tickers", {})
    res = HarvestResult()

    def budget_left() -> bool:
        if res.requests_used >= daily_budget:
            res.budget_exhausted = True
            return False
        return True

    for ticker in tickers:
        if not budget_left():
            break
        tinfo = tinfo_all.setdefault(ticker, {})
        collected = tinfo.setdefault("collected", {})

        # 1) ensure we know this ticker's available quarters (costs 1 request once)
        if "quarters" not in tinfo:
            if not budget_left():
                break
            refs = provider.list_available(ticker)
            res.requests_used += 1
            tinfo["quarters"] = [[r.fiscal_year, r.fiscal_quarter] for r in refs]

        # 2) fetch the target recent quarters not yet collected/known-empty
        for year, quarter in tinfo["quarters"][:quarters_per_ticker]:
            key = f"{year}Q{quarter}"
            tag = f"{ticker}_{key}"
            status = collected.get(key)
            file_exists = ((out_dir / f"{ticker}_{key}.json").exists()
                           or (out_dir / f"{ticker}_{key}.txt").exists())
            if status == "empty":
                res.skipped += 1            # known-empty: never re-request
                continue
            if file_exists:
                if status != "collected":
                    collected[key] = "collected"
                res.skipped += 1            # already have the file → skip
                continue
            # status == "collected" but the file is gone (e.g. CI cache evicted):
            # re-fetch to self-heal rather than silently lose the transcript.
            if not budget_left():
                break
            ref = TranscriptRef(ticker=ticker, fiscal_year=year, fiscal_quarter=quarter,
                                source=getattr(provider, "name", "api"),
                                source_identifier=key)
            try:
                raw = provider.fetch(ref)
                res.requests_used += 1
                _serialize(raw, out_dir, ticker, year, quarter)
                collected[key] = "collected"
                res.collected.append(tag)
            except ValueError:  # provider signals genuinely empty/missing quarter
                res.requests_used += 1
                collected[key] = "empty"
                res.empty.append(tag)
            except Exception as e:  # transient (network/rate) — leave pending, retry next run
                res.requests_used += 1
                collected[key] = "error"
                res.errors.append(f"{tag}: {e}")

    res.worklist_done = not res.budget_exhausted
    ledger.setdefault("history", []).append(
        {"run": now, **res.as_dict()})
    _save_ledger(ledger_path, ledger, now)
    return res


def _default_tickers() -> list[str]:
    override = config.settings().harvest_tickers
    if override:
        return [t.strip().upper() for t in override.split(",") if t.strip()]
    return [c["ticker"].upper() for c in config.universe()]


def main() -> None:
    s = config.settings()
    ap = argparse.ArgumentParser(description="Incremental transcript harvester")
    ap.add_argument("--out", default=str(config.ROOT / "data" / "eai" / "transcripts"))
    ap.add_argument("--ledger", default=str(config.ROOT / "data" / "eai" / "harvest_state.json"))
    ap.add_argument("--budget", type=int, default=s.harvest_daily_budget)
    ap.add_argument("--quarters", type=int, default=s.harvest_quarters_per_ticker)
    ap.add_argument("--tickers", default=None, help="CSV subset (overrides universe)")
    ap.add_argument("--now", default=None, help="timestamp to stamp the ledger with")
    args = ap.parse_args()

    provider = get_transcript_provider(s.harvest_provider)
    tickers = ([t.strip().upper() for t in args.tickers.split(",") if t.strip()]
               if args.tickers else _default_tickers())
    res = run_harvest(provider, tickers, out_dir=Path(args.out), ledger_path=Path(args.ledger),
                      daily_budget=args.budget, quarters_per_ticker=args.quarters, now=args.now)
    print(f"harvest: requests={res.requests_used}/{args.budget} "
          f"collected={len(res.collected)} empty={len(res.empty)} "
          f"errors={len(res.errors)} skipped={res.skipped} "
          f"budget_exhausted={res.budget_exhausted}")
    if res.collected:
        print("  new:", ", ".join(res.collected))


if __name__ == "__main__":
    main()
