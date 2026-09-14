#!/usr/bin/env python3
"""미장 티커 상관관계 수집기 → data/correl.json.

흐름:
  1. 유니버스   : data/us_exchanges.json 의 미국 상장 심볼(약 7천개)에서 출발한다.
                  Finviz 가 열리면 회사명·섹터·산업·시총을 덧붙이고, 막히면
                  커밋된 스크리너 스냅샷(flat/base/turnaround/highs)에서 긁는다.
  2. 가격       : yfinance 로 한 번에 받아(배치) 종가 행렬을 만든다. 종목별로
                  한 번씩 부르는 기존 스크리너 방식보다 훨씬 빠르다.
  3. 유동성 필터 : 가격 $5 이상, 60일 평균 거래대금 하한 이상, 관측일수 하한 이상.
                  안 걸러내면 거래 없는 잡주가 우연히 상위권에 뜬다.
  4. 상관       : 일간 수익률 → 20/50/120일 원시 상관 + 시장(SPY) 잔차 상관.
  5. 이웃 추리기 : 어느 열로 정렬해도 한쪽 기준에 치우치지 않도록, 6개 순위
                  (3기간 × 원시/잔차)의 상위와 원시 하위(헤지 후보)를 합집합으로
                  모은 뒤 잔차 50일 기준으로 잘라 저장한다.

계산 자체는 가볍다(3,700종목 × 250일 상관행렬이 1초 미만). 무거운 건 가격 수신뿐.

  python tools/correl_us.py                    # 전체
  python tools/correl_us.py --limit 300        # 일부만(빠른 점검)
  python tools/correl_us.py --min-dollar-vol 20   # 유동성 기준 올리기(백만달러)

샌드박스에서는 Yahoo 가 막히므로 GitHub Actions 에서 실행한다.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.correl import (  # noqa: E402
    BOTTOM_N, META_SCHEMA, PAIR_SCHEMA, TOP_N, WINDOWS,
    corr_matrix, daily_returns, market_betas, residualize,
)

OUT = ROOT / "data" / "correl.json"
EXCHANGES = ROOT / "data" / "us_exchanges.json"
MARKET = "SPY"                     # 잔차를 구할 때 빼는 시장 대용치

PERIOD = "1y"                      # 120일 창 + 여유. 단기 위주라 길게 받을 이유가 없다
MIN_PRICE = 5.0
MIN_DOLLAR_VOL_M = 10.0            # 60일 평균 거래대금(백만 달러)
MIN_OBS = 130                      # 최소 관측 거래일 — 120일 창을 채울 수 있어야
# Yahoo 는 한 번에 많이 요청하면 YFRateLimitError 를 돌려준다. 첫 실전 실행에서
# 400개씩 쉬지 않고 붙였다가 NVDA·MSFT·TSLA 를 포함해 수천 종목이 레이트 리밋으로
# 빠졌다(6,553 중 유동성 통과 1,441). 배치를 줄이고 사이사이 쉬면서, 실패한 종목만
# 모아 라운드를 거듭해 다시 받는다.
BATCH = 150                        # yfinance 한 번에 받을 티커 수
BATCH_SLEEP = 2.0                  # 배치 사이 대기(초)
RETRY_ROUNDS = 3                   # 실패분 재시도 라운드 수(라운드마다 더 오래 쉰다)

# 이만큼은 반드시 들어와야 "제대로 받았다"고 볼 수 있는 대형주. 이 중 상당수가
# 빠졌다면 레이트 리밋에 맞은 것이므로 결과를 커밋하지 않는다 — 반쪽 스냅샷이
# 조용히 올라가면 사용자는 "NVDA 가 왜 없지?"만 보게 된다.
ANCHORS = ["SPY", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
           "JPM", "XOM", "LLY", "V", "WMT", "AVGO", "UNH", "MA", "HD", "PG",
           "COST", "JNJ"]
MAX_MISSING_ANCHORS = 4            # 이보다 많이 빠지면 수신 실패로 본다


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------ 1. 유니버스
def base_symbols() -> list[str]:
    if not EXCHANGES.exists():
        log(f"  {EXCHANGES} 가 없습니다 — 빌드가 먼저 만들어야 합니다.")
        return []
    data = json.loads(EXCHANGES.read_text(encoding="utf-8"))
    # '.' 이 든 심볼(우선주·워런트 등)과 5자 이상 티커는 대체로 보통주가 아니다.
    return sorted(t for t in data if t.isalpha() and len(t) <= 5)


def metadata() -> dict[str, dict]:
    """{티커: {name, sector, industry, market_cap}} — Finviz 우선, 스냅샷 보조."""
    meta: dict[str, dict] = {}

    def put(t, name=None, sector=None, industry=None, mcap=None):
        cur = meta.setdefault(t, {})
        for k, v in (("name", name), ("sector", sector),
                     ("industry", industry), ("market_cap", mcap)):
            if v and not cur.get(k):
                cur[k] = v

    # 커밋된 스크리너 스냅샷 — 네트워크 없이 읽히고, Finviz 가 막혀도 남는다.
    for fname in ("flat.json", "base.json", "turnaround.json", "highs.json"):
        path = ROOT / "data" / fname
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = d.get("stocks") or d.get("setups") or []
        if not rows and "sectors" in d:
            rows = [s for sec in d["sectors"] for ind in sec.get("industries", [])
                    for s in ind.get("stocks", [])] + \
                   [s for sec in d["sectors"] for s in sec.get("stocks", [])]
        for r in rows:
            t = (r.get("ticker") or "").upper()
            if t:
                put(t, r.get("company_name") or r.get("company"), r.get("sector"),
                    r.get("industry"), r.get("market_cap"))
    log(f"  스냅샷에서 메타 {len(meta)}종목")

    # Finviz 로 유니버스 전체를 덧칠(열리면).
    try:
        from app.flat import config as flat_config
        from app.flat import universe as flat_universe

        rows = flat_universe.get_candidates(flat_config.load())
        for r in rows:
            t = (r.get("ticker") or "").upper()
            if t:
                put(t, r.get("company"), r.get("sector"), r.get("industry"),
                    r.get("market_cap"))
        log(f"  Finviz 로 보강 → 총 {len(meta)}종목")
    except Exception as e:  # noqa: BLE001 - 없으면 스냅샷만으로 간다
        log(f"  Finviz 메타 보강 실패(스냅샷만 사용): {e}")
    return meta


# ------------------------------------------------------------ 2. 가격 수신
def _download_once(chunk: list[str], period: str):
    """한 배치. (close_df, volume_df) 또는 실패 시 (None, None)."""
    import pandas as pd
    import yfinance as yf

    try:
        df = yf.download(chunk, period=period, interval="1d",
                         auto_adjust=True, progress=False, threads=True)
    except Exception as e:  # noqa: BLE001
        log(f"    배치 실패: {e}")
        return None, None
    if df is None or df.empty:
        return None, None
    c = df["Close"] if "Close" in df else df
    v = df["Volume"] if "Volume" in df else None
    if isinstance(c, pd.Series):               # 티커 하나면 Series 로 온다
        c = c.to_frame(chunk[0])
    if v is not None and isinstance(v, pd.Series):
        v = v.to_frame(chunk[0])
    return c, v


def download(symbols: list[str], period: str = PERIOD):
    """종가·거래대금 표를 배치로 받아 합친다. (close_df, dollar_vol_df)

    레이트 리밋은 일시적이므로 한 번 실패한 티커를 버리지 않고 라운드를 거듭해
    다시 받는다. yfinance 는 실패해도 예외를 던지지 않고 그 티커의 열을 비워
    돌려주므로, "값이 하나라도 있는 열"만 성공으로 친다.
    """
    import pandas as pd

    closes, dvols = [], []
    got: set[str] = set()
    pending = list(symbols)

    for rnd in range(RETRY_ROUNDS):
        if not pending:
            break
        wait = BATCH_SLEEP * (rnd + 1)          # 라운드마다 더 여유를 둔다
        log(f"  라운드 {rnd + 1}: {len(pending)}종목 (배치 {BATCH}, 대기 {wait:.0f}s)")
        failed: list[str] = []
        for i in range(0, len(pending), BATCH):
            chunk = pending[i:i + BATCH]
            c, v = _download_once(chunk, period)
            if c is None:
                failed += chunk
                time.sleep(wait)
                continue
            ok = [t for t in chunk if t in c.columns and c[t].notna().any()]
            failed += [t for t in chunk if t not in ok]
            if ok:
                closes.append(c[ok])
                if v is not None:
                    vok = [t for t in ok if t in v.columns]
                    if vok:
                        dvols.append(c[vok] * v[vok])
                got |= set(ok)
            if (i // BATCH) % 10 == 9:
                log(f"    … {i + len(chunk)}/{len(pending)} (누적 수신 {len(got)})")
            time.sleep(wait)
        pending = [t for t in failed if t not in got]
        log(f"  라운드 {rnd + 1} 끝 — 누적 수신 {len(got)}, 미수신 {len(pending)}")

    if pending:
        log(f"  끝내 못 받은 종목 {len(pending)}개 "
            f"(예: {', '.join(pending[:8])}{' …' if len(pending) > 8 else ''})")
    if not closes:
        return None, None
    close = pd.concat(closes, axis=1).sort_index()
    dvol = pd.concat(dvols, axis=1).sort_index() if dvols else None
    return close.loc[:, ~close.columns.duplicated()], (
        None if dvol is None else dvol.loc[:, ~dvol.columns.duplicated()])


def missing_anchors(close) -> list[str]:
    """대형주 중 가격을 못 받은 것들 — 수신이 정상이었는지 판단하는 기준."""
    return [t for t in ANCHORS
            if t not in close.columns or not close[t].notna().any()]


# ------------------------------------------------------- 3. 유동성 필터
def liquid_columns(close, dvol, min_dollar_vol_m: float) -> list[str]:
    """가격·거래대금·관측일수 기준을 통과한 티커."""
    import numpy as np

    keep = []
    last = close.ffill().iloc[-1]
    obs = close.notna().sum()
    avg_dv = (dvol.tail(60).mean() if dvol is not None else None)
    for t in close.columns:
        if obs.get(t, 0) < MIN_OBS:
            continue
        px = last.get(t)
        if px is None or not np.isfinite(px) or px < MIN_PRICE:
            continue
        if avg_dv is not None:
            dv = avg_dv.get(t)
            if dv is None or not np.isfinite(dv) or dv < min_dollar_vol_m * 1e6:
                continue
        keep.append(t)
    return keep


# ----------------------------------------------------------- 4~5. 상관
def build_pairs(tickers, R, E):
    """종목별 이웃 목록. 반환: [[ [j, raw…, res…], … ], …] (티커 순서와 동일)

    후보를 한 기준으로만 뽑으면 다른 열로 정렬할 때 편향이 생긴다. 그래서 6개
    순위의 상위와 원시 상관 하위(헤지 후보)를 합집합으로 모은다.
    """
    import numpy as np

    n = len(tickers)
    raws = [corr_matrix(R, window=w) for w in WINDOWS]
    ress = [corr_matrix(E, window=w) for w in WINDOWS]
    for M in raws + ress:
        np.fill_diagonal(M, np.nan)

    mid = WINDOWS.index(50) if 50 in WINDOWS else len(WINDOWS) // 2
    out = []
    for i in range(n):
        cand: set[int] = set()
        for M in ress:                                   # 테마 동행 후보
            cand |= set(_top_idx(M[i], TOP_N))
        for M in raws:                                   # 같이 움직이는 종목
            cand |= set(_top_idx(M[i], TOP_N // 2))
            cand |= set(_top_idx(-M[i], BOTTOM_N))       # 헤지 후보(음의 상관)
        cand.discard(i)
        # 너무 커지지 않게 잔차(중간 기간) 기준으로 자른다.
        order = sorted(cand, key=lambda j: -(ress[mid][i, j] if np.isfinite(ress[mid][i, j]) else -9))
        keep = order[:TOP_N + BOTTOM_N + TOP_N // 2]
        out.append([[int(j)] + [_i100(M[i, j]) for M in raws]
                                + [_i100(M[i, j]) for M in ress] for j in keep])
    return out


def _top_idx(row, k: int) -> list[int]:
    import numpy as np

    v = np.where(np.isfinite(row), row, -np.inf)
    k = min(k, len(v))
    idx = np.argpartition(-v, k - 1)[:k] if k > 0 else []
    return [int(j) for j in idx if np.isfinite(row[j])]


def _i100(x):
    import numpy as np

    return None if x is None or not np.isfinite(x) else int(round(float(x) * 100))


# ------------------------------------------------------------------ main
def main() -> None:
    argv = sys.argv[1:]

    def opt(name, cast, default):
        return cast(argv[argv.index(name) + 1]) if name in argv else default

    limit = opt("--limit", int, 0)
    min_dv = opt("--min-dollar-vol", float, MIN_DOLLAR_VOL_M)

    syms = base_symbols()
    if limit:
        syms = syms[:limit]
    if not syms:
        log("유니버스가 비었습니다. 중단.")
        return
    log(f"유니버스 {len(syms)}종목 (+ 시장 {MARKET})")

    meta_src = metadata()

    log("가격 받는 중 ...")
    close, dvol = download(sorted(set(syms) | {MARKET}))
    if close is None or close.empty:
        log("가격을 하나도 받지 못했습니다. 중단.")
        return
    log(f"  {close.shape[1]}종목 × {close.shape[0]}일 수신")

    if MARKET not in close.columns:
        log(f"{MARKET} 가격을 못 받아 잔차를 구할 수 없습니다. 중단.")
        return

    # 레이트 리밋에 맞은 반쪽 결과를 조용히 덮어쓰지 않는다.
    gone = missing_anchors(close)
    if len(gone) > MAX_MISSING_ANCHORS:
        log(f"대형주 {len(gone)}/{len(ANCHORS)}개를 못 받았습니다({', '.join(gone)}). "
            f"레이트 리밋으로 보이므로 기존 스냅샷을 그대로 둡니다.")
        return
    if gone:
        log(f"  참고: 대형주 {len(gone)}개 미수신({', '.join(gone)}) — 허용 범위 안")

    keep = liquid_columns(close, dvol, min_dv)
    keep = [t for t in keep if t != MARKET]
    log(f"유동성 통과 {len(keep)}종목 "
        f"(가격 ≥ ${MIN_PRICE:.0f}, 거래대금 ≥ ${min_dv:.0f}M, 관측 ≥ {MIN_OBS}일)")
    if len(keep) < 50:
        log("통과 종목이 너무 적습니다. 중단.")
        return

    # 지난번보다 크게 줄었으면 수신이 덜 된 것이다 — 유동성 기준을 사용자가
    # 의도적으로 올린 경우가 아니면 기존 스냅샷을 지키는 쪽이 안전하다.
    prev_n = 0
    if OUT.exists():
        try:
            prev_n = len(json.loads(OUT.read_text(encoding="utf-8")).get("tickers") or [])
        except Exception:  # noqa: BLE001
            prev_n = 0
    if prev_n and len(keep) < prev_n * 0.7 and min_dv <= MIN_DOLLAR_VOL_M:
        log(f"지난 스냅샷({prev_n}종목)보다 30% 넘게 줄었습니다({len(keep)}종목). "
            f"수신 누락으로 보이므로 기존 스냅샷을 그대로 둡니다.")
        return

    import numpy as np

    prices = close[keep].to_numpy(dtype=np.float64).T          # (N, T)
    mkt_px = close[MARKET].to_numpy(dtype=np.float64)[None, :]
    R = daily_returns(prices)
    mkt = daily_returns(mkt_px)[0]
    mkt = np.where(np.isfinite(mkt), mkt, 0.0)

    log("상관 계산 중 ...")
    beta = market_betas(R, mkt)
    E = residualize(R, mkt, beta)
    pairs = build_pairs(keep, R, E)

    avg_dv = (dvol.tail(60).mean() if dvol is not None else None)
    last_px = close.ffill().iloc[-1]
    meta = []
    for i, t in enumerate(keep):
        m = meta_src.get(t, {})
        meta.append([
            m.get("name") or "",
            m.get("sector") or "",
            m.get("industry") or "",
            int(round(float(beta[i]) * 100)),
            int(round((m.get("market_cap") or 0) / 1e6)),
            int(round(float(avg_dv.get(t, 0)) / 1e6)) if avg_dv is not None else 0,
        ])

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": str(close.index[-1].date()),
        "market": MARKET,
        "period": PERIOD,
        "windows": list(WINDOWS),
        "pair_schema": PAIR_SCHEMA,
        "meta_schema": META_SCHEMA,
        "tickers": keep,
        "meta": meta,
        "neighbors": pairs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    avg_n = sum(len(p) for p in pairs) / max(1, len(pairs))
    log(f"Wrote {OUT} — {len(keep)}종목, 평균 이웃 {avg_n:.0f}개, "
        f"{OUT.stat().st_size / 1e6:.1f}MB, 기준일 {payload['asof']}")


if __name__ == "__main__":
    main()
