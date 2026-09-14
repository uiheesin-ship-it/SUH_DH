#!/usr/bin/env python3
"""스캐너 유니버스 상한을 풀면 실제로 얼마나 더 걸리는지 재 본다(측정 전용).

아무것도 커밋하지 않고, 스냅샷도 건드리지 않는다. 재는 것은 셋이다.

  1. 스크리너별 후보 수 — 지금(상한 있음) vs 상한을 풀었을 때.
     상한이 실제로 종목을 버리고 있는지, 버린다면 몇 개인지.
  2. 세 유니버스의 합집합. 베이스·평평·턴어라운드는 한 빌드 안에서 같은 캐시로
     일봉을 받으므로, 캐시가 빌드 내내 살아 있으면 실제 수신량은 합이 아니라
     **합집합**이다. 이게 늘어나는 비용의 진짜 분모다.
  3. 종목당 수신 시간 — 표본으로 직접 재서 추정에 쓴다.

  python tools/scan_cost_probe.py            # 표본 60종목으로 수신 시간 측정
  python tools/scan_cost_probe.py --sample 0 # 유니버스 크기만(수신 측정 생략)

샌드박스에서는 Finviz·야후가 막히므로 GitHub Actions 에서 실행한다.
"""

from __future__ import annotations

import copy
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def log(msg: str = "") -> None:
    print(msg, flush=True)


def uncapped(cfg: dict) -> dict:
    """후보 수 상한만 푼 설정 사본(0 = 무제한). load() 는 공유 캐시라 사본을 쓴다."""
    out = copy.deepcopy(cfg)
    uni = out.setdefault("universe", {})
    uni["max_candidates"] = 0
    uni["max_etf_candidates"] = 0
    return out


def sizes(name: str, cfg_mod, uni_mod) -> tuple[set, set]:
    """(지금 상한대로 뽑은 티커, 상한 없이 뽑은 티커)."""
    cfg = cfg_mod.load()
    # 두 번 불러도 Finviz 는 한 번만 탄다 — 원본 행이 캐시되고 상한은 그 뒤에 걸린다.
    now = {r["ticker"] for r in uni_mod.get_candidates(cfg)}
    full = {r["ticker"] for r in uni_mod.get_candidates(uncapped(cfg))}
    log(f"  {name:12} 지금 {len(now):5,}  상한 없음 {len(full):5,}  "
        f"버려지던 종목 {len(full) - len(now):5,}")
    return now, full


def measure_fetch(tickers: list[str], n: int) -> float | None:
    """표본 n개를 실제로 받아 종목당 초를 잰다(스캔과 같은 0.2초 간격 포함)."""
    if n <= 0 or not tickers:
        return None
    from app.base import data as basedata

    pick = random.Random(0).sample(tickers, min(n, len(tickers)))
    t0 = time.time()
    ok = 0
    for t in pick:
        try:
            bars = basedata.fetch_bars(t, use_cache=False)
            ok += bool(bars and bars.get("close"))
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)                     # run_scan 과 같은 간격
    per = (time.time() - t0) / len(pick)
    log(f"  표본 {len(pick)}종목 중 {ok}개 수신 — 종목당 {per:.2f}초")
    return per


def main() -> None:
    argv = sys.argv[1:]
    n_sample = int(argv[argv.index("--sample") + 1]) if "--sample" in argv else 60

    from app.base import config as base_cfg
    from app.base import universe as base_uni
    from app.flat import config as flat_cfg
    from app.flat import universe as flat_uni
    from app.turnaround import config as turn_cfg
    from app.turnaround import universe as turn_uni

    log("유니버스 크기 (지금 vs 상한 없음)")
    now_sets, full_sets = {}, {}
    for name, c, u in (("베이스", base_cfg, base_uni),
                       ("평평", flat_cfg, flat_uni),
                       ("턴어라운드", turn_cfg, turn_uni)):
        try:
            now_sets[name], full_sets[name] = sizes(name, c, u)
        except Exception as e:  # noqa: BLE001
            log(f"  {name:12} 실패: {e}")

    if not full_sets:
        log("유니버스를 하나도 얻지 못했습니다. 중단.")
        return

    union_now = set().union(*now_sets.values())
    union_full = set().union(*full_sets.values())
    log()
    log("한 빌드에서 실제로 받는 종목 수 = 세 유니버스의 합집합")
    log(f"  지금        {len(union_now):6,}   (단순 합 {sum(map(len, now_sets.values())):6,})")
    log(f"  상한 없음   {len(union_full):6,}   (단순 합 {sum(map(len, full_sets.values())):6,})")
    log(f"  늘어나는 수신 {len(union_full) - len(union_now):+6,}")

    log()
    log("종목당 수신 시간 측정")
    per = measure_fetch(sorted(union_full), n_sample)

    if per:
        log()
        log("추정 (수신 시간만. 계산·차트 생성은 별도)")
        for label, n in (("지금(합집합)", len(union_now)),
                         ("상한 없음(합집합)", len(union_full))):
            log(f"  {label:20} {n:6,}종목 × {per:.2f}초 = {n * per / 60:6.0f}분")
        log(f"  차이 {(len(union_full) - len(union_now)) * per / 60:+.0f}분")
        log()
        log("참고: 캐시 TTL 이 30분이던 동안에는 빌드가 30분을 넘기면 세 스크리너가")
        log("      겹치는 종목을 다시 받았다. 단순 합에 가까웠다는 뜻이다.")
        log(f"      단순 합 {sum(map(len, now_sets.values())):,}종목 "
            f"= {sum(map(len, now_sets.values())) * per / 60:.0f}분")


if __name__ == "__main__":
    main()
