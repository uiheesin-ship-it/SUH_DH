#!/usr/bin/env python3
"""EV/EBITDA 파이프라인 실측 — 샌드박스에서는 SEC 가 막혀 있어 여기서 잰다.

단위 테스트(tests/test_evebitda.py)는 이중계상·as-of 같은 **규칙**을 못 박지만,
실제 회사의 태그 조합까지는 못 본다. 그래서 진짜 티커로 돌려 보고 세 가지를
확인한다.

  1. 선이 그려지나 — 확정(실선) 며칠, 가정(점선) 며칠.
  2. 오늘 EV 가 야후 ``enterpriseValue`` 와 얼마나 벌어지나. **일치가 목표가
     아니다** — 리스부채를 넣는 만큼 우리 쪽이 커야 맞다. 방향과 크기가
     설명되는지를 본다.
  3. 없는 버킷이 무엇인지. 조용한 0 이 제일 나쁘다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def log(m=""):
    print(m, flush=True)


def money(v):
    if v is None:
        return "—"
    a = abs(v)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if a >= div:
            return f"{v / div:,.2f}{unit}"
    return f"{v:,.2f}"


def main():
    from app import quarterly

    tickers = [a for a in sys.argv[1:] if not a.startswith("-")] or \
              ["AAPL", "NVDA", "PLD", "CEG", "SMCI", "WMT", "JPM"]
    summary = []
    for t in tickers:
        log(f"\n■ {t}")
        try:
            d = quarterly.build(t)
        except Exception as e:  # noqa: BLE001
            log(f"   ✕ {type(e).__name__}: {e}")
            continue
        ev = d.get("ev") or {}
        if ev.get("error"):
            log(f"   EV/EBITDA 없음 — {ev['error']}")
            summary.append((t, None, None, ev["error"][:40]))
            continue

        solid = [v for v in ev["per_confirmed"] if v is not None]
        dashed = [v for v in ev["per_estimated"] if v is not None]
        log(f"   실선 {len(solid)}일 (최저 {min(solid, default=0):.1f} ~ "
            f"최고 {max(solid, default=0):.1f}) · 점선 {len(dashed)}일")
        log(f"   기간 {ev['dates'][0]} ~ {ev['dates'][-1]} · 계단 {len(ev['marks'])}개")
        log(f"   EBITDA 출처: {ev['ebitda_source']}")
        m, why = ev.get("margin"), ev.get("margin_why") or {}
        log(f"   EBITDA 마진(중앙값) {'' if m is None else f'{m * 100:.1f}%'} "
            f"· 최근 {why.get('quarters')}분기 "
            f"{why.get('low')}~{why.get('high')}")
        log(f"   추정: {ev.get('estimate_note')}")

        L = ev.get("latest") or {}
        log(f"   최근 재무상태표 {L.get('end')} (발표 {L.get('announced')})")
        log(f"     발행주식수 {money(L.get('shares'))} · 차입금 {money(L.get('debt'))} "
            f"· 현금성 {money(L.get('cash'))} · 기타 {money(L.get('other'))} "
            f"→ 순부채 {money(L.get('net_debt'))}")
        for k, v in sorted((L.get("parts") or {}).items()):
            log(f"       {k:22} {money(v)}")
        log(f"     태그: {ev.get('tags')}")
        if ev.get("missing"):
            log(f"     전 기간 없는 버킷: {', '.join(ev['missing'])}")
        if L.get("absent"):
            log(f"     이 분기만 없는 버킷: {', '.join(L['absent'])}")

        # 오늘 EV 대조
        close = ev["close"][-1]
        mk = ev["marks"][-1] if ev["marks"] else None
        mine = close * mk["shares"] + mk["adj"] if mk else None
        y_ev = None
        try:
            import yfinance as yf
            info = yf.Ticker(t).info or {}
            y_ev = info.get("enterpriseValue")
            y_debt, y_cash = info.get("totalDebt"), info.get("totalCash")
            gap = (mine / y_ev - 1) * 100 if (mine and y_ev) else None
            log(f"   오늘 EV  내 값 {money(mine)}  야후 {money(y_ev)}"
                + (f"  차이 {gap:+.1f}%" if gap is not None else ""))
            log(f"     야후 차입금 {money(y_debt)} · 현금 {money(y_cash)}"
                f"  (리스부채를 넣는 만큼 내 차입금이 커야 맞다)")
        except Exception as e:  # noqa: BLE001
            log(f"   야후 대조 ✕ {type(e).__name__}")

        last = ev["per_confirmed"][-1] or ev["per_estimated"][-1]
        log(f"   → 최근 12M forward EV/EBITDA ≈ {last}")
        summary.append((t, mine, y_ev, last))

    # 한눈에 보는 요약 — 로그가 길어져 종목별 줄이 화면 밖으로 밀리기 때문이다.
    log("\n── 요약 ─────────────────────────────────────")
    log(f"   {'티커':6} {'내 EV':>14} {'야후 EV':>14} {'차이':>8}  최근 배수")
    for t, mine, y_ev, last in summary:
        if mine is None:
            log(f"   {t:6} {'—':>14} {'—':>14} {'—':>8}  {last}")
            continue
        gap = f"{(mine / y_ev - 1) * 100:+.1f}%" if (mine and y_ev) else "—"
        log(f"   {t:6} {money(mine):>14} {money(y_ev):>14} {gap:>8}  {last}")


if __name__ == "__main__":
    main()
