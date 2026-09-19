#!/usr/bin/env python3
"""국장 파이프라인 실측 — 샌드박스에서 DART·네이버가 막혀 있어 여기서 잰다.

단위 테스트(tests/test_krfundamentals.py, tests/test_krquarterly.py)는 누적 차분·
Q4 역산·세 단계 채움 같은 **규칙**을 못 박지만, 진짜 회사의 계정 이름과 보고서
구성까지는 못 본다. 확인할 것은 넷이다.

  1. 5년 분기가 다 잡히나 — 항목마다 몇 분기인가.
  2. 실적발표일이 붙나 — 잠정실적으로 몇 분기, 정기보고서로 몇 분기.
  3. 선이 그려지나 — 확정(실선) 며칠, 추정(점선) 며칠.
  4. 추정 분기를 **무엇으로** 채웠나 — ①분기 컨센 ②연간 배분 ③성장률 가정.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ["005930", "000660", "035420", "105560", "247540"]


def log(m=""):
    print(m, flush=True)


def won(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:,.2f}조"
    if a >= 1e8:
        return f"{v / 1e8:,.0f}억"
    return f"{v:,.0f}"


def main():
    from app import krquarterly

    codes = [a for a in sys.argv[1:] if not a.startswith("-")] or SAMPLES
    for code in codes:
        log(f"\n■ {code}")
        try:
            d = krquarterly.build(code)
        except Exception as e:  # noqa: BLE001
            log(f"   ✕ {type(e).__name__}: {e}")
            continue
        log(f"   {d.get('name') or '?'} · DART {d.get('corp_code')}")
        for label, m in (d.get("metrics") or {}).items():
            qs = m.get("quarters") or []
            last = qs[-1] if qs else None
            est = m.get("estimates") or {}
            ne = len(est.get("quarters") or []) + \
                sum(1 for y in (est.get("years") or []) if y.get("val") is not None)
            log(f"   {label:10} {len(qs):2}분기 · 최근 {last['end'] if last else '—'} "
                f"{won(last['val']) if last else '':>12} · 컨센 칸 {ne}"
                + (f"  ⚠ {m['warning']}" if m.get("warning") else ""))
        for n in d.get("notes") or []:
            log(f"   ⚠ {n}")

        per = d.get("per")
        if not per:
            log("   forward PER 없음")
            continue
        solid = [v for v in per["per_confirmed"] if v is not None]
        dashed = [v for v in per["per_estimated"] if v is not None]
        log(f"   실선 {len(solid)}일 (최저 {min(solid, default=0):.1f} ~ "
            f"최고 {max(solid, default=0):.1f}) · 점선 {len(dashed)}일")
        log(f"   기간 {per['dates'][0]} ~ {per['dates'][-1]} · 계단 {len(per['marks'])}개")
        src = {}
        for q in per["quarters"]:
            src[q.get("source") or "없음"] = src.get(q.get("source") or "없음", 0) + 1
        log(f"   발표일 출처: {src}")
        log(f"   추정 채움: {per.get('kr_fill')} · 성장률 {per.get('kr_growth')}")
        log(f"   계절성: {per['season']['mode']} {per['season']['weights']}")
        for e in per.get("estimates") or []:
            log(f"     {e['end']}  EPS {e['eps']}  ({e['source']})"
                + (f"  ⚠ {e['note']}" if e.get("note") else ""))
        log(f"   컨센 출처: {per.get('consensus_sources')}")


if __name__ == "__main__":
    main()
