"""Export a static snapshot of the analysis for GitHub Pages (spec §21, §22).

Runs the pipeline against an (ephemeral) DB and writes plain JSON that the
vanilla static page app/static/eai/ reads — exactly the repo's existing model
(GitHub Actions builds JSON, Pages serves it). With the LLM cache committed,
the daily run only pays for new/changed calls.

    python -m app.eai.export                      # → data/eai/*.json
    python -m app.eai.export --out site/data/eai  # → into a built site

Providers come from env/eai_config.yaml (mock by default; set
EAI_LLM_PROVIDER=anthropic + EAI_*_MODEL + EAI_ANTHROPIC_API_KEY for real runs,
and EAI_TRANSCRIPT_PROVIDER=directory to analyze committed transcripts).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .db import create_all, dispose, sessionmaker
from .services import jobs, queries


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


async def export_snapshot(out_dir: Path, run: bool = True) -> dict:
    await create_all()
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = None
    async with sessionmaker()() as s:
        if run:
            job = await jobs.create_job(s, "batch", {"source": "export"})
            result = await jobs.run_batch(s, job=job)

    async with sessionmaker()() as s:
        companies = await queries.list_companies(s)
        themes = await queries.list_themes(s)
        board = await queries.investment_board(s)
        coverage = await queries.coverage_dashboard(s)
        usage = await queries.usage_summary(s)

        meta = {
            "built": built,
            "maturity": config.maturity()["mvp_label"],
            "llm_provider": config.provider_name("llm"),
            "transcript_provider": config.provider_name("transcript"),
            "versions": config.versions(),
            "counts": {"companies": len(companies), "themes": len(themes),
                       "investment_themes": len(board)},
            "batch_status": (result or {}).get("status"),
        }
        _write(out_dir / "index.json", meta)
        _write(out_dir / "companies.json", {"built": built, "companies": companies})
        _write(out_dir / "themes.json",
               {"built": built, "maturity": meta["maturity"], "themes": themes})
        _write(out_dir / "investment_themes.json",
               {"built": built, "maturity": meta["maturity"], "investment_themes": board})
        _write(out_dir / "coverage.json", {"built": built, **coverage})
        _write(out_dir / "usage.json", {"built": built, **usage})

        for c in companies:
            detail = await queries.company_detail(s, c["ticker"])
            _write(out_dir / "company" / f"{c['ticker']}.json", detail)

    await dispose()
    return {"built": built, **meta}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(config.ROOT / "data" / "eai"))
    ap.add_argument("--no-run", action="store_true",
                    help="export current DB without re-running analysis")
    args = ap.parse_args()
    meta = asyncio.run(export_snapshot(Path(args.out), run=not args.no_run))
    print(f"eai snapshot written to {args.out}: {meta['counts']} "
          f"(llm={meta['llm_provider']}, status={meta['batch_status']})")


if __name__ == "__main__":
    main()
