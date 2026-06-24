#!/usr/bin/env python3
"""Maintain the curated guidance-vs-consensus annotations in data/guidance.json.

The free price/earnings sources do not carry two numbers the post-earnings drift
table needs in its right-hand column:

  * the company's **next-quarter guidance** (only in the earnings release/call), and
  * the **point-in-time consensus** for that quarter as of the report date.

This tool runs where the network is open (your PC or the GitHub Actions build —
the web sandbox blocks the data sites) and helps fill both:

  add        Record a verified guidance entry (guidance + consensus + source).
             No network; this is the authoritative path — paste the numbers
             from the press release / earnings-day coverage and it computes the
             상회/하회 grade and writes data/guidance.json.

  consensus  Snapshot the current next-quarter consensus (revenue + EPS) via
             yfinance. Run it shortly *before* an earnings date to capture the
             pre-guidance consensus automatically; optionally write it onto an
             existing entry's `consensus` field with --apply.

Examples
--------
  # Authoritative: fill one quarter from the press release + earnings coverage
  python3 tools/guidance.py add MU \\
      --report-date 2025-12-17 --period "FY26 Q2" --metric revenue \\
      --guidance 8.8 --low 8.6 --high 9.0 --consensus 8.5 \\
      --source https://investors.micron.com/... --note "AI 메모리 수요"

  # Automatable half: snapshot next-quarter consensus before earnings
  python3 tools/guidance.py consensus MU
  python3 tools/guidance.py consensus MU --apply 2025-12-17 --metric revenue

Offline preview (no network): prefix with SUH_DH_DEMO=1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import earnings  # noqa: E402

GUIDANCE_FILE = Path(earnings.GUIDANCE_FILE)


def _load() -> dict:
    if GUIDANCE_FILE.exists():
        try:
            data = json.loads(GUIDANCE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"warning: could not parse {GUIDANCE_FILE}: {e}", file=sys.stderr)
    return {}


def _save(data: dict) -> None:
    GUIDANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GUIDANCE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _entry_key(e: dict) -> tuple:
    return (e.get("report_date"), e.get("metric"))


def cmd_add(args) -> int:
    entry = {
        "report_date": args.report_date,
        "guided_period": args.period,
        "metric": args.metric,
        "unit": args.unit,
        "guidance_mid": args.guidance,
        "consensus": args.consensus,
    }
    if args.low is not None:
        entry["guidance_low"] = args.low
    if args.high is not None:
        entry["guidance_high"] = args.high
    if args.note:
        entry["note"] = args.note
    if args.source:
        entry["sources"] = list(args.source)

    pct, label = earnings.classify_guidance(args.guidance, args.consensus)
    data = _load()
    bucket = data.setdefault(args.ticker.upper(), [])
    # Replace an existing entry for the same (report_date, metric), else append.
    bucket[:] = [e for e in bucket if _entry_key(e) != _entry_key(entry)]
    bucket.append(entry)
    bucket.sort(key=lambda e: (e.get("report_date") or "", e.get("metric") or ""), reverse=True)
    _save(data)
    grade = f"{label} ({pct:+}%)" if label else "등급 계산 불가(숫자 누락)"
    print(f"saved {args.ticker.upper()} {args.report_date} {args.metric}: "
          f"가이던스 {args.guidance} vs 컨센 {args.consensus} -> {grade}")
    print(f"-> {GUIDANCE_FILE}")
    return 0


def cmd_consensus(args) -> int:
    snap = earnings.forward_consensus(args.ticker)
    print(json.dumps(snap, ensure_ascii=False, indent=2))

    if not args.apply:
        return 0

    field = "revenue_consensus" if args.metric == "revenue" else "eps_consensus"
    value = snap.get(field)
    if value is None:
        print(f"no {args.metric} consensus available to apply.", file=sys.stderr)
        return 1
    data = _load()
    bucket = data.get(args.ticker.upper(), [])
    target = next(
        (e for e in bucket if e.get("report_date") == args.apply and e.get("metric") == args.metric),
        None,
    )
    if target is None:
        print(f"no guidance entry for {args.ticker.upper()} {args.apply} {args.metric}; "
              f"create it first with `add`.", file=sys.stderr)
        return 1
    target["consensus"] = value
    target.setdefault("sources", []).append(f"yfinance forward consensus snapshot {snap.get('captured')}")
    _save(data)
    print(f"applied {args.metric} consensus {value} to {args.ticker.upper()} {args.apply}.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="record a verified guidance entry")
    a.add_argument("ticker")
    a.add_argument("--report-date", required=True, help="earnings date the guidance was given (YYYY-MM-DD)")
    a.add_argument("--period", required=True, help="guided quarter label, e.g. 'FY26 Q3'")
    a.add_argument("--metric", default="revenue", choices=["revenue", "eps", "gross_margin"])
    a.add_argument("--unit", default="B_USD", help="display unit (B_USD, USD, pct)")
    a.add_argument("--guidance", type=float, required=True, help="company guidance midpoint")
    a.add_argument("--low", type=float, default=None)
    a.add_argument("--high", type=float, default=None)
    a.add_argument("--consensus", type=float, required=True, help="consensus at report time")
    a.add_argument("--note", default=None)
    a.add_argument("--source", action="append", help="source URL (repeatable)")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("consensus", help="snapshot next-quarter consensus via yfinance")
    c.add_argument("ticker")
    c.add_argument("--apply", metavar="REPORT_DATE", default=None,
                   help="write the snapshot onto an existing entry's consensus field")
    c.add_argument("--metric", default="revenue", choices=["revenue", "eps"])
    c.set_defaults(func=cmd_consensus)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
