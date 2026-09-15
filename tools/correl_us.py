#!/usr/bin/env python3
"""미장 티커 상관관계 수집기 → data/correl.json.

흐름:
  1. 유니버스   : 평평 스크리너의 유니버스를 쓰되 **후보 수 상한은 푼다**
                  (app.flat.universe). 저장소가 이미 정의해 둔 "거래할 만한
                  미국 주식" 목록이고,
                  베이스 스크리너와 달리 **이평선 조건이 없어** 상관 분석에 맞다 —
                  베이스 쪽은 정배열(50·200일선 위)만 담아서, 그걸 쓰면 하락 중인
                  종목이 통째로 빠지고 헤지 후보(음의 상관)를 찾을 수 없다.
                  평평 쪽은 후보를 3,000종목으로 솎아내는데, 그러면 기준을 다
                  넘는 종목이 임의로 빠진다(APPS 가 그렇게 없었다). 솎아내기는
                  끄고 유동성 기준만으로 거른다.
                  Finviz 가 403 으로 막히면 지난번 목록(data/correl_universe.json)을
                  재사용한다 — 유니버스는 하루 사이에 크게 바뀌지 않는다.
  2. 가격       : yfinance 로 배치로 받는다. 한 번에 많이 붙이면 레이트 리밋에
                  맞으므로 작게 끊고 쉬어 가며, 실패분은 라운드를 거듭해 다시 받는다.
  3. 유동성 필터 : 가격 $5 이상, 60일 평균 거래대금 하한 이상, 관측일수 하한 이상.
                  안 걸러내면 거래 없는 잡주가 우연히 상위권에 뜬다.
  4. 상관       : 일간 수익률 → 20/50/120일 원시 상관 + 시장(SPY) 잔차 상관.
  5. 이웃 추리기 : 어느 열로 정렬해도 한쪽 기준에 치우치지 않도록, 6개 순위
                  (3기간 × 원시/잔차)의 상위와 원시 하위(헤지 후보)를 합집합으로
                  모은다. 자를 때는 동행 자리와 헤지 자리를 나눠 채운다 — 한 번에
                  잔차 내림차순으로 자르면 헤지 후보가 통째로 사라진다. 동행 자리는
                  세 기간 잔차의 최솟값으로 고른다(한 기간만 보면 우연이 상위권을
                  먹는다). 상관행렬은 3,700종목이면 하나가 110MB 라, 6개를 동시에
                  들지 않고 **한 번에 하나씩** 만들고 버린다(피크 메모리 1개분).
  6. 잡음선     : 시간축을 어긋나게 돌린 무작위 쌍의 상관 분포에서 상위 1/N
                  지점을 창마다 실측해 같이 저장한다 — "유니버스를 다 훑었을 때
                  운만으로 나오는 최고값". 화면에서 그 아래 값은 흐리게 칠한다.

계산 자체는 가볍다(3,700종목 × 250일 상관행렬이 1초 미만). 무거운 건 가격 수신뿐.

  python tools/correl_us.py                       # 전체
  python tools/correl_us.py --limit 300           # 일부만(빠른 점검)
  python tools/correl_us.py --min-dollar-vol 20   # 유동성 기준 올리기(백만달러)

샌드박스에서는 Yahoo 가 막히므로 GitHub Actions 에서 실행한다.
"""

from __future__ import annotations

import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.correl import (  # noqa: E402
    BOTTOM_N, ETF_SLOTS, HEDGE_SLOTS, META_SCHEMA, PAIR_SCHEMA, TOP_N, WINDOWS,
    corr_rows, daily_returns, market_betas, residualize, standardized,
)

OUT = ROOT / "data" / "correl.json"
UNIVERSE_CACHE = ROOT / "data" / "correl_universe.json"   # Finviz 실패 시 폴백
MARKET = "SPY"                     # 잔차를 구할 때 빼는 시장 대용치

PERIOD = "1y"                      # 120일 창 + 여유. 단기 위주라 길게 받을 이유가 없다
MIN_PRICE = 5.0
MIN_DOLLAR_VOL_M = 10.0            # 60일 평균 거래대금(백만 달러)
MIN_OBS = 130                      # 최소 관측 거래일 — 120일 창을 채울 수 있어야
MAX_NEIGHBORS = 60                 # 종목당 저장할 이웃 수(파일 크기와 직결)
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
def _save_universe(rows: list[dict]) -> None:
    UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    UNIVERSE_CACHE.write_text(json.dumps(
        {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "count": len(rows), "rows": rows}, ensure_ascii=False), encoding="utf-8")


def _load_universe() -> list[dict]:
    if not UNIVERSE_CACHE.exists():
        return []
    try:
        return json.loads(UNIVERSE_CACHE.read_text(encoding="utf-8")).get("rows") or []
    except Exception:  # noqa: BLE001
        return []


def unsampled_flat_config(base: dict) -> dict:
    """평평 스크리너 설정에서 후보 수 상한만 푼 사본.

    평평 스크리너는 Finviz 결과를 3,000종목(+ETF 700)으로 잘라 쓴다. 자를 때
    시총 구간이 고르게 남도록 **일정 간격으로 솎아내는데**, 구간 안의 어떤
    종목이 빠질지는 사실상 임의다. 평평 스크리너는 "쓸 만한 표본"만 있으면
    되니 괜찮지만, 상관 분석에서는 치명적이다 — 사용자가 찾는 바로 그 종목이
    조용히 없을 수 있다. 실제로 APPS(디지털터빈, 시총 $1.4B, 거래대금 $29M)가
    기준을 다 넘고도 이렇게 빠졌다.

    여기서는 솎아내지 않는다(0 = 무제한). 걸러내는 일은 유동성 기준
    (가격 $5 · 거래대금 $10M · 관측 130일)에만 맡긴다.
    """
    cfg = copy.deepcopy(base)          # load() 는 공유 캐시를 돌려준다 — 원본을 건드리면 안 된다
    uni = cfg.setdefault("universe", {})
    uni["max_candidates"] = 0
    uni["max_etf_candidates"] = 0
    return cfg


def universe_rows() -> list[dict]:
    """{ticker, name, sector, industry, market_cap, is_etf} 목록.

    평평 스크리너의 유니버스를 쓴다 — 이 저장소가 이미 정의해 둔 "거래할
    만한 미국 주식"이고, 이평선 조건이 없어 상승·하락 종목이 모두 들어온다.
    (베이스 쪽 유니버스는 정배열만 담아서 헤지 후보를 찾을 수 없다.)
    다만 후보 수 상한은 풀고 가져온다 — unsampled_flat_config 참고.

    Finviz 는 403 으로 막힌 이력이 있으므로, 성공하면 목록을 파일로 남기고
    실패하면 그 파일을 재사용한다.
    """
    rows: list[dict] = []
    try:
        from app.flat import config as flat_config
        from app.flat import universe as flat_universe

        for r in flat_universe.get_candidates(unsampled_flat_config(flat_config.load())):
            t = (r.get("ticker") or "").upper().strip()
            if not t:
                continue
            rows.append({
                "ticker": t,
                "name": r.get("company") or "",
                "sector": r.get("sector") or "",
                "industry": r.get("industry") or "",
                "market_cap": r.get("market_cap") or 0,
                "is_etf": bool(r.get("is_etf")),
            })
    except Exception as e:  # noqa: BLE001
        log(f"  Finviz 유니버스 실패: {e}")

    if rows:
        log(f"  평평 스크리너 유니버스 {len(rows)}종목 "
            f"(ETF {sum(1 for r in rows if r['is_etf'])}개 포함)")
        _save_universe(rows)
        return rows

    cached = _load_universe()
    if cached:
        log(f"  Finviz 가 막혀 지난 유니버스를 재사용합니다 ({len(cached)}종목)")
    else:
        log("  유니버스를 얻지 못했고 폴백 파일도 없습니다.")
    return cached


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
def _specs():
    """저장 순서(PAIR_SCHEMA)와 같은 (종류, 창) 목록 — 원시 3개 뒤 잔차 3개."""
    return [("raw", w) for w in WINDOWS] + [("res", w) for w in WINDOWS]


def build_pairs(tickers, R, E, is_etf=None, max_neighbors: int = MAX_NEIGHBORS):
    """종목별 이웃 목록. 반환: [[ [j, raw…, res…], … ], …] (티커 순서와 동일)

    후보를 한 기준으로만 뽑으면 다른 열로 정렬할 때 편향이 생긴다. 그래서 6개
    순위(3기간 × 원시/잔차)의 상위와 원시 하위(헤지 후보)를 합집합으로 모은다.

    자를 때 두 가지를 조심한다.

      헤지 자리를 따로 뺀다 — 잔차 내림차순으로 한 번에 자르면 애써 모은 음의
      상관 후보가 전부 잘린다(첫 스냅샷에서 이웃이 꽉 찬 종목의 68%가 음의 상관
      이웃을 하나도 갖지 못했다). 동행 자리와 헤지 자리를 나눠 각각 채운다.

      ETF 자리도 따로 뺀다 — ETF 는 그 종목을 담고 있어 상관이 높은 게 당연해서
      자리를 안 나누면 정원을 통째로 먹는다. 유니버스 상한을 풀어 ETF 가 105개
      에서 743개로 늘자 MU 의 이웃 60개 중 45개가 ETF 가 됐다(실제 종목 15개).
      ETF_SLOTS 개까지만 받고 나머지는 실제 종목에 준다.

      동행 자리는 **세 기간의 잔차 상관 중 최솟값**으로 자른다. 2,200종목 중
      한 기간만 보고 고르면 상위권이 우연으로 채워진다 — 50일 상관의 표준오차가
      1/√50 ≈ 0.14 라 무관한 종목도 0.45쯤은 우연히 나오고, 실제로 NVDA 의
      50일 잔차 상위가 유조선·석유주로 찼다. 세 기간이 모두 버텨야 남긴다.

    메모리가 관건이다. 상관을 쌍마다 결측을 따져 구하면 중간 행렬이 9개 생겨
    3,000종목에서 660MB 를 쓴다. 대신 창별로 표준화한 Z 를 만들어 두면
    상관은 Z@Z.T 한 번이고(37MB), **후보가 정해진 뒤에는 행렬조차 필요 없다** —
    필요한 쌍만 내적하면 된다. 그래서 1차에서만 행렬을 쓰고 한 번에 하나씩
    버리며, 2차(값 채우기)는 행렬 없이 후보 쌍만 계산한다.
    """
    import gc

    import numpy as np

    n = len(tickers)
    mid_w = 50 if 50 in WINDOWS else WINDOWS[len(WINDOWS) // 2]
    etf_mask = (np.zeros(n, dtype=bool) if is_etf is None
                else np.asarray(is_etf, dtype=bool))

    # 창별 표준화 행렬은 작다(N×window float32) — 전부 들고 있어도 된다.
    Zs = {(kind, w): standardized(R if kind == "raw" else E, window=w)
          for kind, w in _specs()}

    # --- 1차: 후보 모으기 (행렬 하나씩 만들고 버린다) ----------------------
    cand: list[set] = [set() for _ in range(n)]
    for kind, w in _specs():
        Z, ok = Zs[(kind, w)]
        M = Z @ Z.T
        M[~ok] = np.nan
        M[:, ~ok] = np.nan
        np.fill_diagonal(M, np.nan)
        for i in range(n):
            row = M[i]
            # ETF 를 따로 뽑는다. 섞어서 상위를 고르면 ETF 가 후보를 통째로 먹어
            # **진짜 동료가 애초에 후보에도 못 든다** — 그 종목을 담은 ETF 는
            # 상관이 0.9를 넘는 게 당연해서 상위 30개가 전부 ETF 로 찬다.
            # 정원(ETF_SLOTS)은 마지막에 자를 때도 걸지만, 여기서 안 나누면
            # 자를 후보 자체가 ETF 뿐이라 소용이 없다.
            stock_row = np.where(etf_mask, np.nan, row)
            etf_row = np.where(etf_mask, row, np.nan)
            if kind == "res":
                cand[i].update(_top_idx(stock_row, TOP_N))        # 테마 동행 후보
                cand[i].update(_top_idx(etf_row, ETF_SLOTS))
            else:
                cand[i].update(_top_idx(stock_row, TOP_N // 2))   # 같이 움직이는 종목
                cand[i].update(_top_idx(etf_row, ETF_SLOTS // 2))
                cand[i].update(_top_idx(-stock_row, BOTTOM_N))    # 헤지 후보(음의 상관)
                cand[i].update(_top_idx(-etf_row, BOTTOM_N // 2))
        del M
        gc.collect()

    # --- 후보 자르기: 동행 자리와 헤지 자리를 따로 채운다 -------------------
    hedge_slots = min(HEDGE_SLOTS, max_neighbors // 2)
    theme_slots = max_neighbors - hedge_slots
    etf_cap = min(ETF_SLOTS, max_neighbors)
    Zraw, okraw = Zs[("raw", mid_w)]
    keep: list[list[int]] = []
    for i in range(n):
        c = cand[i]
        c.discard(i)
        cols = np.fromiter(c, dtype=np.int64, count=len(c))
        if len(cols) == 0:
            keep.append([])
            continue

        chosen: list[int] = []
        taken: set[int] = set()
        n_etf = 0

        def take(j: int) -> bool:
            """ETF 정원을 지키며 한 자리 채운다. 채웠으면 True."""
            nonlocal n_etf
            if j in taken:
                return False
            if etf_mask[j]:
                if n_etf >= etf_cap:
                    return False
                n_etf += 1
            chosen.append(j)
            taken.add(j)
            return True

        # 동행 점수 = 세 기간 잔차 상관의 최솟값(한 기간이라도 없으면 탈락).
        score = np.full(len(cols), np.inf, dtype=np.float64)
        for w in WINDOWS:
            Zw, okw = Zs[("res", w)]
            score = np.minimum(score, corr_rows(Zw, okw, i, cols).astype(np.float64))
        for k in np.argsort(-np.where(np.isfinite(score), score, -9.0)):
            if len(chosen) >= theme_slots:
                break
            take(int(cols[k]))

        # 헤지는 실제 손익이 상쇄돼야 하므로 원시 상관 오름차순으로 고른다.
        hv = corr_rows(Zraw, okraw, i, cols)
        for k in np.argsort(np.where(np.isfinite(hv), hv, 9.0)):
            if len(chosen) >= max_neighbors:
                break
            take(int(cols[k]))
        keep.append(chosen)
    del cand
    gc.collect()

    # --- 2차: 값 채우기 — 행렬 없이 후보 쌍만 --------------------------------
    out = [[[j] for j in row] for row in keep]
    for kind, w in _specs():
        Z, ok = Zs[(kind, w)]
        for i in range(n):
            cols = keep[i]
            if not cols:
                continue
            v = corr_rows(Z, ok, i, np.asarray(cols, dtype=np.int64))
            for slot, x in enumerate(v):
                out[i][slot].append(_i100(x))
    return out


def noise_line(Z, ok_row, universe=None, samples: int = 300000, seed: int = 0):
    """"이 유니버스를 다 훑었을 때 운만으로 나올 수 있는 최고값".

    무작위 쌍을 그냥 재면 안 된다 — 처음에 그렇게 했다가 50일 선이 +0.58 로
    나왔고, 그러면 JPM 과 BAC(+0.84) 말고는 전부 잡음으로 찍힌다. 무작위로 고른
    두 종목도 같은 섹터면 진짜로 같이 움직이므로, 그 분포의 상위 1%는 "우연"이
    아니라 "실제 상관이 큰 쌍들"이다.

    그래서 **시간축을 어긋나게 돌려서**(원형 시프트) 잰다. 각 종목의 수익률
    분포와 자기상관은 그대로 두고 종목끼리의 시점만 어긋나게 하면, 남는 상관은
    오로지 우연이다. 표준화된 행을 돌려도 평균 0 · 노름 1 이 그대로라 내적이
    곧 상관계수다.

    백분위는 1 − 1/N 을 쓴다. 한 종목을 조회할 때 N개와 비교하는 셈이므로,
    "N번 뽑으면 한 번쯤 나오는 값" = 운만으로 기대되는 1등이다. 이보다 낮은
    숫자는 그 자체로는 우연과 구별되지 않는다.
    """
    import numpy as np

    idx = np.flatnonzero(ok_row)
    n = int(universe or len(idx))
    if len(idx) < 50 or n < 2:
        return None
    T = Z.shape[1]
    rng = np.random.default_rng(seed)

    vals = []
    step = 20000
    for start in range(0, samples, step):
        k = min(step, samples - start)
        a = rng.choice(idx, k)
        b = rng.choice(idx, k)
        # 덩어리마다 다른 시프트를 준다. 0 이나 T 근처면 안 어긋나므로 피한다.
        shift = int(rng.integers(T // 4, T - T // 4)) if T >= 8 else 1
        m = a != b
        if not m.any():
            continue
        vals.append(np.abs(np.einsum("ij,ij->i", Z[a[m]], np.roll(Z[b[m]], shift, axis=1))))
    if not vals:
        return None
    return round(float(np.quantile(np.concatenate(vals), 1.0 - 1.0 / n)), 3)


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

    log("유니버스 구성 중 ...")
    rows = universe_rows()
    if limit:
        rows = rows[:limit]
    if not rows:
        log("유니버스가 비었습니다. 중단.")
        return
    meta_src = {r["ticker"]: r for r in rows}
    syms = sorted(meta_src)
    log(f"유니버스 {len(syms)}종목 (+ 시장 {MARKET})")

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

    # 중간에 빠진 날(거래정지·데이터 누락)은 직전 종가로 메운다 → 그날 수익률 0%.
    # "거래가 없었으니 가격이 안 변했다"는 해석이고, 안 메우면 하루 결측만으로도
    # 그 종목이 창 전체에서 제외돼 이웃이 하나도 안 잡힌다(실측으로 확인).
    # ffill 은 상장 전 구간(앞쪽 NaN)은 그대로 두므로 신규 상장은 영향받지 않는다.
    close = close.ffill()

    prices = close[keep].to_numpy(dtype=np.float64).T          # (N, T)
    mkt_px = close[MARKET].to_numpy(dtype=np.float64)[None, :]
    R = daily_returns(prices)
    mkt = daily_returns(mkt_px)[0]
    mkt = np.where(np.isfinite(mkt), mkt, 0.0)

    log("상관 계산 중 ...")
    beta = market_betas(R, mkt)
    E = residualize(R, mkt, beta)
    etf_flags = [bool(meta_src.get(t, {}).get("is_etf")) for t in keep]
    pairs = build_pairs(keep, R, E, is_etf=etf_flags)

    # 잡음선 — 이 값 아래는 우연으로도 나온다. 화면에서 흐리게 표시한다.
    noise = {}
    for w in WINDOWS:
        Zw, okw = standardized(E, window=w)
        line = noise_line(Zw, okw, universe=len(keep))
        if line is not None:
            noise[str(w)] = line
    if noise:
        log("  잡음선(시간 어긋낸 무작위 쌍의 상위 1/N): " +
            ", ".join(f"{w}일 {v:+.2f}" for w, v in noise.items()))

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
            1 if m.get("is_etf") else 0,
        ])

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": str(close.index[-1].date()),
        "market": MARKET,
        "period": PERIOD,
        "universe_source": "flat-screener",   # 이평선 조건 없는 목록(상관 분석용)
        "noise": noise,                       # 창별 "우연으로도 나오는" 상관 수준
        "etf_included": sum(1 for t in keep if meta_src.get(t, {}).get("is_etf")),
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
