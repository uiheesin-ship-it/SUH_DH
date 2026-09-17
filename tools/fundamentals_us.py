#!/usr/bin/env python3
"""한 종목의 분기 실적 + 12M forward PER 을 뽑아 본다.

  python tools/fundamentals_us.py AAPL MU JPM
  python tools/fundamentals_us.py AAPL --json out.json

미리 전 종목을 모으지 않는다 — 요청한 티커만 받는다. 수집·조립은 전부
``app/`` 안에 있고(secdata·consensus·quarterly) 여기는 그걸 불러 보여 주는
얇은 껍데기다. API 가 쓰는 코드와 **같은 코드**여야 CLI 로 본 게 화면에
나오는 것과 같다.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import quarterly, secdata  # noqa: E402


def log(m=""):
    print(m, flush=True)


def fmt(v):
    if v is None:
        return "—"
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def show(r: dict) -> None:
    log(f"\n■ {r['ticker']} — {r.get('name')} ({r.get('sic')}) "
        f"결산 {r.get('fiscal_year_end')}")
    for label, m in r["metrics"].items():
        qs = m["quarters"]
        if not qs:
            log(f"   {label:12} —  ({m['source']})")
            continue
        last = qs[-1]
        yoy = f"{last['yoy']:+.1f}%" if last.get("yoy") is not None else "—"
        qoq = f"{last['qoq']:+.1f}%" if last.get("qoq") is not None else "—"
        log(f"   {label:12} {m['count']:2}분기 · 최근 {last['end']} "
            f"{fmt(last['val'])}  YoY {yoy}  QoQ {qoq}   ({m['source']})")
        if m.get("warning"):
            log(f"   {'':12} ⚠ {m['warning']}")

    per = r.get("per")
    if not per:
        for n in r.get("notes") or []:
            log(f"   ⚠ {n}")
        return
    vals = [(d, v, True) for d, v in zip(per["dates"], per["per_confirmed"]) if v]
    est = [(d, v, False) for d, v in zip(per["dates"], per["per_estimated"]) if v]
    log(f"   {'forward PER':12} {len(vals)}일 확정 + {len(est)}일 추정 "
        f"· 컨센 출처 {', '.join(per['consensus_sources']) or '없음'}")
    for d, v, ok in ([vals[0]] if vals else []) + ([vals[-1]] if vals else []) + \
            ([est[-1]] if est else []):
        log(f"   {'':12} {d}  PER {v:,.1f}  ({'확정' if ok else '추정'})")
    for m in per["marks"][-3:]:
        log(f"   {'':12} 발표 {m['announced']} · 기준 {m['basis_end']} · "
            f"향후4분기 EPS {fmt(m['eps'])} · 추정 {m['estimated']}분기 "
            f"({m['source']})")
    for n in r.get("notes") or []:
        log(f"   ⚠ {n}")


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_path = Path(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else None
    tickers = argv or ["AAPL"]

    log(f"CIK 씨앗 {len(secdata.cik_map()):,}개")
    results = []
    for t in tickers:
        try:
            r = quarterly.build(t)
        except Exception as e:  # noqa: BLE001
            r = {"ticker": t.upper(), "error": f"{type(e).__name__}: {e}"}
            log(f"\n■ {t} — ❌ {r['error']}")
        else:
            show(r)
        results.append(r)
        time.sleep(secdata.PAUSE)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
        log(f"\nWrote {out_path} ({out_path.stat().st_size / 1e3:.0f}KB)")


if __name__ == "__main__":
    main()
