#!/usr/bin/env python3
"""분기 실적표 만들기/채우기 — 티커 하나로 10개 분기 표를 뽑는다.

표는 **최근 발표 분기**를 기준으로 이전 6개 분기 + 향후 4개 분기(총 10열)이고,
행은 과거 가이던스 / 컨센서스 / 실적 / 향후 가이던스(연간) / 향후 가이던스(QoQ),
각각 매출·영업이익·EBITDA·EPS 입니다(app/qtable.py 참고).

실적과 EPS 컨센서스는 야후(yfinance)에서 자동으로 채워지고, 회사 가이던스처럼
무료 API에 없는 값은 ``data/guidance_table.json`` 큐레이션에서 옵니다. ``add`` 로
그 큐레이션을 명령 한 줄로 채울 수 있습니다.

사용 예
-------
  # 표 보기(터미널)
  python3 tools/qtable.py APPS

  # 엑셀에 그대로 붙여넣기 (탭 구분) / 파일로 저장
  python3 tools/qtable.py APPS --tsv
  python3 tools/qtable.py APPS --csv apps.csv
  python3 tools/qtable.py APPS --json apps.json

  # 가이던스 입력: FY26 3Q 발표 때 제시한 4분기 매출 가이던스 130.3~135.3
  python3 tools/qtable.py add APPS --kind quarter_guidance --metric revenue \
      --for FY2026Q4 --given-at FY2026Q3 --low 130.3 --high 135.3 \
      --source https://ir.digitalturbine.com/... --note "3Q 발표 자료"

  # 연간 가이던스 / 문구만 넣기
  python3 tools/qtable.py add APPS --kind annual_guidance --metric ebitda \
      --for FY2027 --given-at FY2026Q4 --low 135 --high 145
  python3 tools/qtable.py add APPS --kind quarter_guidance --metric eps \
      --given-at FY2027Q1 --text 미제공 --sections fwd_qoq

  # 큐레이션이 입력된 종목 목록
  python3 tools/qtable.py list

네트워크가 막힌 환경에서는 ``SUH_DH_DEMO=1`` 을 앞에 붙이면 야후 호출 없이
큐레이션 값만으로 표를 그립니다.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import qtable  # noqa: E402

SUBCOMMANDS = ("show", "add", "list")


# --------------------------------------------------------------------------- #
# 터미널 출력(한글 폭 보정)
# --------------------------------------------------------------------------- #
def _w(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s: str, width: int, right: bool = False) -> str:
    space = " " * max(0, width - _w(s))
    return (space + s) if right else (s + space)


def render_text(table: dict) -> str:
    grid = qtable.to_grid(table)
    widths = [max(_w(row[i]) if i < len(row) else 0 for row in grid)
              for i in range(len(grid[0]))]
    lines = []
    for r, row in enumerate(grid):
        cells = [_pad(row[0], widths[0])]
        cells += [_pad(c, widths[i + 1], right=True) for i, c in enumerate(row[1:])]
        lines.append("  ".join(cells).rstrip())
        if r == 1:  # 헤더(연도/분기) 아래 구분선
            lines.append("-" * min(_w(lines[-1]), 160))
    return "\n".join(lines)


def header_text(table: dict) -> str:
    name = f" {table['name']}" if table.get("name") else ""
    anchor = table["anchor"]
    report = f", 발표 {anchor['report_date']}" if anchor.get("report_date") else ""
    basis = f"\n기준: {table['basis']}" if table.get("basis") else ""
    warn = f"\n⚠ 야후 수집 실패({table['fetch_error']}) — 큐레이션 값만 표시" \
        if table.get("fetch_error") else ""
    return (f"[{table['ticker']}]{name} · 기준 분기 {anchor['label']}{report}"
            f" · {table['fy_end_month']}월 결산 · 단위 {table['unit_label']}{basis}{warn}")


# --------------------------------------------------------------------------- #
# show
# --------------------------------------------------------------------------- #
def cmd_show(args) -> int:
    table = qtable.build_table(args.ticker, past=args.past, ahead=args.ahead)

    if args.json is not None:
        text = json.dumps(table, ensure_ascii=False, indent=2)
        _emit(text, args.json)
    elif args.csv is not None:
        _emit(qtable.to_delimited(table, ","), args.csv)
    elif args.tsv is not None:
        _emit(qtable.to_delimited(table, "\t"), args.tsv)
    else:
        print(header_text(table))
        print(render_text(table))
        for note in table.get("notes") or []:
            print(f"  · {note}")
        if not table.get("curated"):
            print(f"\n큐레이션 없음 — 가이던스 행은 비어 있습니다. "
                  f"'python3 tools/qtable.py add {table['ticker']} ...' 로 채우세요.")
    return 0


def _emit(text: str, path: str) -> None:
    """``path`` 가 빈 문자열(플래그만 준 경우)이면 표준출력."""
    if path:
        Path(path).write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    else:
        sys.stdout.write(text)


# --------------------------------------------------------------------------- #
# add
# --------------------------------------------------------------------------- #
def cmd_add(args) -> int:
    path = Path(qtable.QTABLE_FILE)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    ticker = args.ticker.upper()

    block = data.get(ticker)
    if isinstance(block, list):        # 옛 형식(엔트리 배열)은 감싸서 승격
        block = {"meta": {}, "entries": block}
    if not isinstance(block, dict):
        block = {"meta": {}, "entries": []}
    block.setdefault("meta", {})
    block.setdefault("entries", [])

    if args.fy_end_month:
        block["meta"]["fy_end_month"] = args.fy_end_month
    if args.name:
        block["meta"]["name"] = args.name

    if args.low is None and args.high is None and args.value is None and not args.text:
        print("값이 없습니다 — --low/--high, --value, --text 중 하나는 필요합니다.",
              file=sys.stderr)
        return 2
    if not args.for_period and not args.given_at:
        print("--for 또는 --given-at 중 하나는 필요합니다.", file=sys.stderr)
        return 2

    entry: dict = {"kind": args.kind, "metric": args.metric}
    if args.for_period:
        entry["for"] = args.for_period
    if args.given_at:
        entry["given_at"] = args.given_at
    for key, val in (("low", args.low), ("high", args.high), ("value", args.value)):
        if val is not None:
            entry[key] = val
    if args.text:
        entry["text"] = args.text
    if args.unit:
        entry["unit"] = args.unit
    if args.sections:
        entry["sections"] = args.sections
    if args.note:
        entry["note"] = args.note
    if args.source:
        entry["sources"] = list(args.source)

    # 같은 (kind, metric, for, given_at) 은 갱신으로 본다 — 재입력이 흔하므로.
    key_of = lambda e: (e.get("kind"), e.get("metric"), e.get("for"),
                        e.get("given_at"), tuple(e.get("sections") or ()))
    entries = [e for e in block["entries"] if key_of(e) != key_of(entry)]
    replaced = len(entries) != len(block["entries"])
    entries.append(entry)
    block["entries"] = entries
    data[ticker] = block

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(("갱신" if replaced else "추가") + f": {ticker} {args.kind} {args.metric} "
          f"for={args.for_period or '-'} given_at={args.given_at or '-'}")
    print(f"→ {path}")
    return 0


def cmd_list(_args) -> int:
    tickers = qtable.curated_tickers()
    if not tickers:
        print("큐레이션된 종목이 없습니다.")
        return 0
    for t in tickers:
        meta, entries = qtable._ticker_block(t)
        name = f" ({meta['name']})" if meta.get("name") else ""
        print(f"{t}{name} — {len(entries)}건")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="분기 실적표(과거 가이던스/컨센서스/실적/향후 가이던스)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="티커의 분기 실적표 출력(기본 명령)")
    s.add_argument("ticker")
    s.add_argument("--past", type=int, default=qtable.PAST_QUARTERS,
                   help=f"과거 분기 수(기본 {qtable.PAST_QUARTERS}, 최근 발표 분기 포함)")
    s.add_argument("--ahead", type=int, default=qtable.AHEAD_QUARTERS,
                   help=f"향후 분기 수(기본 {qtable.AHEAD_QUARTERS})")
    s.add_argument("--tsv", nargs="?", const="", metavar="PATH",
                   help="탭 구분(엑셀 붙여넣기용). 경로를 주면 파일로 저장")
    s.add_argument("--csv", nargs="?", const="", metavar="PATH", help="CSV 출력/저장")
    s.add_argument("--json", nargs="?", const="", metavar="PATH", help="JSON 출력/저장")
    s.set_defaults(func=cmd_show)

    a = sub.add_parser("add", help="가이던스·컨센서스·실적 큐레이션 한 줄 입력")
    a.add_argument("ticker")
    a.add_argument("--kind", required=True,
                   choices=["quarter_guidance", "annual_guidance", "consensus", "actual"])
    a.add_argument("--metric", required=True,
                   choices=["revenue", "operating_income", "ebitda", "eps"])
    a.add_argument("--for", dest="for_period", metavar="FY2026Q4|FY2027",
                   help="대상 기간(분기 가이던스/컨센서스/실적) 또는 연간 가이던스의 회계연도")
    a.add_argument("--given-at", metavar="FY2026Q3", help="그 수치를 제시한 분기")
    a.add_argument("--low", type=float, help="가이던스 밴드 하단")
    a.add_argument("--high", type=float, help="가이던스 밴드 상단")
    a.add_argument("--value", type=float, help="단일 수치")
    a.add_argument("--text", help="숫자 대신 넣을 문구(예: 미제공, 연간 제공)")
    a.add_argument("--unit", default=None, help="M_USD(기본) | B_USD | USD(EPS)")
    a.add_argument("--sections", nargs="+", choices=qtable.SECTION_KEYS,
                   help="배치할 행 블록 제한(기본: kind 에 따라 자동)")
    a.add_argument("--note", help="메모(툴팁)")
    a.add_argument("--source", action="append", help="출처 URL(여러 번 사용 가능)")
    a.add_argument("--fy-end-month", type=int, help="결산월을 meta 에 함께 기록(1~12)")
    a.add_argument("--name", help="회사명을 meta 에 함께 기록")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="큐레이션이 입력된 종목 목록")
    l.set_defaults(func=cmd_list)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 첫 인자가 서브커맨드가 아니면 티커로 보고 show 로 넘긴다.
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "show")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
