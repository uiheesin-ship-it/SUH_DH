"""티커 상관관계 — "이 종목이 움직일 때 같이 가는 종목" 찾기.

두 가지 용도가 한 표에 들어간다.

  테마 동행 : 동행 점수(세 기간 잔차 상관의 최솟값) 내림차순. 시장 움직임을
              걷어낸 뒤에도, 세 기간 모두에서 같이 가는 종목이 진짜 테마 동료다.
  헤지      : 원시 상관 오름차순. 헤지는 실제 손익이 상쇄돼야 하므로 시장
              움직임까지 포함한 원시 상관으로 봐야 한다.

왜 잔차를 쓰나 — 모든 주식의 수익률에는 시장 전체의 움직임이 섞여 있어서, 서로
아무 관계 없는 두 종목도 "둘 다 시장을 따라간다"는 이유만으로 상관이 붙는다.
시장이 변동성의 절반을 설명하는 고베타 종목 둘은 고유 움직임이 완전히 독립이어도
상관이 0.5를 넘는다. 그대로 정렬하면 상위권이 테마와 무관한 고베타 대형주로
채워지므로, 시장 성분을 회귀로 뺀 잔차끼리 다시 상관을 구한다.

섹터는 빼지 않는다. 테마가 섹터와 겹치는 경우(AI 전력 ↔ 유틸리티)가 많아 섹터를
회귀로 지우면 찾으려던 신호까지 같이 지워지고, 섹터 라벨 자체가 부정확한 종목
(변압기 회사가 Industrials, 데이터센터 REIT 이 Real Estate)에는 엉뚱한 지수를
빼서 노이즈를 넣게 된다. 대신 섹터를 열로 보여주고 화면에서 필터하게 한다.

기간 하나만 보고 줄을 세우지 않는다. 50일 상관의 표준오차가 1/√50 ≈ 0.14 라
2,200종목을 훑으면 아무 관계 없는 종목도 +0.45쯤을 흔히 찍는다 — 첫 스냅샷에서
NVDA 의 50일 잔차 상위가 유조선·석유주로 찬 것이 그 탓이다. 세 기간이 모두 버틴
값(동행 점수)으로 자르고, 무작위 쌍에서 실측한 "잡음선"을 화면에 같이 띄운다.

ETF 는 기본으로 숨긴다. 성장주 ETF 는 그 종목 자체를 담고 있어 상관이 높은 게
당연하다 — 테마 동료가 아니라 자기 자신이다.

가격이 아니라 수익률로 상관을 구한다. 가격 수준끼리 상관시키면 둘 다 우상향이라
무관한 종목도 0.95가 나온다.

수집은 ``tools/correl_us.py`` 가 하고 결과를 ``data/correl.json`` 에 쓴다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = os.environ.get("SUH_DH_CORREL_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "correl.json"
)

# 상관을 재는 기간(거래일). 단기 위주로 본다 — 같은 두 종목도 20일과 120일의
# 답이 다르고, 그 차이 자체가 신호라서 세 기간을 모두 열로 싣는다.
WINDOWS = (20, 50, 120)

# 종목당 보관할 이웃 수. 후보는 여러 기준의 상위/하위를 합집합으로 모으므로
# (어느 열로 정렬해도 한쪽 기준에 치우치지 않게) 실제 개수는 이보다 적을 수 있다.
TOP_N = 30          # 테마 동행 후보 (잔차 상관 상위)
BOTTOM_N = 15       # 헤지 후보 (원시 상관 하위)

# 이웃 정원을 두 용도로 쪼개 둔다. 안 쪼개면 마지막에 잔차 내림차순으로 한 번
# 자를 때 헤지 후보(음의 상관)가 전부 잘려 나간다 — 실제로 첫 스냅샷에서
# 이웃이 꽉 찬 종목의 68%가 음의 상관 이웃을 하나도 갖지 못했다.
HEDGE_SLOTS = 15    # 원시 상관 오름차순으로 따로 확보하는 자리

# ETF 가 차지할 수 있는 자리의 상한. ETF 는 그 종목을 담고 있어 상관이 높은 게
# 당연해서, 자리를 안 나누면 정원을 통째로 먹는다 — 유니버스 상한을 풀어 ETF 가
# 105개에서 743개로 늘자 MU 의 이웃 60개 중 45개가 ETF 가 됐다(실제 종목 15개).
# 몇 개는 남겨 둔다: SMH·SOXX 가 같이 뜨면 "섹터 전체가 움직였다"는 정보다.
ETF_SLOTS = 10

# 저장 포맷 — 파일이 커지지 않게 상관계수는 ×100 정수로, 티커는 인덱스로 쓴다.
PAIR_SCHEMA = ["j"] + [f"raw{w}" for w in WINDOWS] + [f"res{w}" for w in WINDOWS]
META_SCHEMA = ["name", "sector", "industry", "beta_x100", "mcap_musd", "dvol_musd",
               "is_etf"]


# ------------------------------------------------------------------ 계산
# 아래 네 함수는 numpy 배열만 주고받는다 — 네트워크 없이 합성 데이터로 검증할 수
# 있게 하려는 것(실제 시세는 샌드박스에서 못 받는다).
def daily_returns(close):
    """종가 행렬(N종목 × T일) → 일간 수익률(N × T-1).

    가격이 아니라 수익률로 상관을 봐야 한다. 결측(상장 전/거래정지)은 NaN 으로
    남겨 두고 상관 계산에서 걸러낸다.
    """
    import numpy as np

    c = np.asarray(close, dtype=np.float64)
    prev = c[:, :-1]
    out = np.divide(c[:, 1:] - prev, prev, out=np.full_like(prev, np.nan),
                    where=np.isfinite(prev) & (prev > 0))
    return out


def market_betas(R, mkt):
    """각 종목의 시장 베타 = cov(종목, 시장) / var(시장).

    결측이 있는 종목은 그 종목이 값을 가진 날만 써서 구한다.
    """
    import numpy as np

    R = np.asarray(R, dtype=np.float64)
    m = np.asarray(mkt, dtype=np.float64)
    ok = np.isfinite(R) & np.isfinite(m)[None, :]
    n = ok.sum(axis=1)

    Rz = np.where(ok, R, 0.0)
    Mz = np.where(ok, m[None, :], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        rbar = Rz.sum(axis=1) / n
        mbar = Mz.sum(axis=1) / n
        cov = (Rz * Mz).sum(axis=1) / n - rbar * mbar
        var = (Mz * Mz).sum(axis=1) / n - mbar * mbar
        beta = np.where(var > 0, cov / var, 0.0)
    return np.where(n >= 2, beta, 0.0)


def residualize(R, mkt, beta=None):
    """시장 성분을 뺀 잔차 수익률. 잔차 = 실제 − 베타 × 시장."""
    import numpy as np

    R = np.asarray(R, dtype=np.float64)
    m = np.asarray(mkt, dtype=np.float64)
    b = market_betas(R, m) if beta is None else np.asarray(beta, dtype=np.float64)
    return R - b[:, None] * m[None, :]


def standardized(R, window=None, min_obs=None):
    """창 구간을 표준화한 행렬 Z 와, 그 창에서 값이 온전한 종목 마스크.

    Z 를 만들어 두면 상관은 ``Z @ Z.T`` 한 번으로 끝난다 — 결측을 쌍마다 따지는
    corr_matrix 는 중간 행렬을 9개 만들어 결과의 9배를 쓴다(3,000종목에서 660MB).
    유동성 필터를 통과한 종목은 창 안에 결측이 거의 없으므로, 온전한 종목만
    골라 이 빠른 길로 보내고 나머지는 그 창에서 값을 주지 않는다("그 기간
    데이터가 온전한 종목만 그 기간 상관을 갖는다").

    float32 를 쓴다 — 저장할 때 ×100 정수로 반올림하므로 소수 2자리면 충분하고,
    메모리는 절반이다.
    """
    import numpy as np

    X = np.asarray(R, dtype=np.float64)
    if window:
        X = X[:, -window:]
    T = X.shape[1]
    need = min_obs if min_obs is not None else max(10, int(T * 0.8))

    ok_row = np.isfinite(X).all(axis=1) & (T >= need)
    Z = np.zeros((X.shape[0], T), dtype=np.float32)
    if ok_row.any():
        W = X[ok_row]
        W = W - W.mean(axis=1, keepdims=True)
        sd = W.std(axis=1, keepdims=True)
        sd[sd == 0] = 1.0
        Z[ok_row] = (W / sd / np.sqrt(T)).astype(np.float32)
    return Z, ok_row


def corr_rows(Z, ok_row, i, cols):
    """종목 i 와 cols 들의 상관계수만. 행렬 전체를 만들지 않는다."""
    import numpy as np

    if not ok_row[i] or len(cols) == 0:
        return np.full(len(cols), np.nan, dtype=np.float32)
    v = Z[cols] @ Z[i]
    return np.where(ok_row[cols], np.clip(v, -1.0, 1.0), np.nan)


def corr_matrix(R, window=None, min_obs=None):
    """행끼리의 상관계수 행렬. window 를 주면 마지막 window 일만 쓴다.

    관측이 모자란 쌍(상장한 지 얼마 안 된 종목 등)은 NaN 으로 둔다 — 며칠치로
    구한 0.98 은 의미가 없다.
    """
    import numpy as np

    X = np.asarray(R, dtype=np.float64)
    if window:
        X = X[:, -window:]
    T = X.shape[1]
    need = min_obs if min_obs is not None else max(10, int(T * 0.8))

    ok = np.isfinite(X)
    Xz = np.where(ok, X, 0.0)
    cnt = ok.astype(np.float64) @ ok.astype(np.float64).T      # 쌍별 공통 관측일수
    with np.errstate(invalid="ignore", divide="ignore"):
        s = Xz @ ok.T.astype(np.float64)                       # Σx over 공통일
        ss = (Xz * Xz) @ ok.T.astype(np.float64)               # Σx² over 공통일
        sxy = Xz @ Xz.T
        cov = sxy / cnt - (s / cnt) * (s.T / cnt)
        va = ss / cnt - (s / cnt) ** 2
        den = np.sqrt(np.clip(va, 0, None) * np.clip(va.T, 0, None))
        C = np.where(den > 0, cov / den, np.nan)
    C[cnt < need] = np.nan
    return np.clip(C, -1.0, 1.0)


# ------------------------------------------------------------------ 뷰
def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "").strip() in ("1", "true", "yes")


def _load() -> dict | None:
    path = Path(DATA_FILE)
    if not path.exists():
        # SUH_DH_DEMO=1 이면 합성 시장으로 화면을 확인할 수 있게 한다.
        if _demo():
            from .demo_data import demo_correl

            return demo_correl()
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("tickers") else None


def _meta_at(meta: list, j: int) -> list:
    """메타 한 줄을 스키마 길이에 맞춰 꺼낸다(옛 스냅샷은 is_etf 가 없다)."""
    m = list(meta[j]) if j < len(meta) else []
    blank = ["", "", "", 0, 0, 0, 0]
    return [m[k] if k < len(m) else blank[k] for k in range(len(META_SCHEMA))]


def expand(data: dict, ticker: str) -> dict | None:
    """저장된 압축 포맷을 화면/ API 가 쓰는 행 목록으로 편다."""
    tickers = data.get("tickers") or []
    try:
        i = tickers.index(ticker.upper().strip())
    except ValueError:
        return None

    meta = data.get("meta") or []
    nb = (data.get("neighbors") or [])[i] if i < len(data.get("neighbors") or []) else []

    def row(j, name, sector, industry, beta, mcap, dvol, is_etf=0):
        # is_etf 를 싣기 전 스냅샷도 산업명으로 알아본다. ETF 는 섹터가 전부
        # Financial 로 붙어 나오므로 섹터 자리에는 "ETF" 를 쓴다.
        etf = bool(is_etf) or industry == "Exchange Traded Fund"
        return {"ticker": tickers[j], "name": name,
                "sector": "ETF" if etf else sector,
                "industry": industry, "beta": (beta or 0) / 100,
                "market_cap": (mcap or 0) * 1e6, "dollar_volume": (dvol or 0) * 1e6,
                "is_etf": etf}

    out = []
    for pair in nb:
        j = pair[0]
        if j >= len(tickers):
            continue
        m = _meta_at(meta, j)
        r = row(j, *m)
        n = len(WINDOWS)
        for k, w in enumerate(WINDOWS):
            r[f"raw{w}"] = None if pair[1 + k] is None else pair[1 + k] / 100
            r[f"res{w}"] = None if pair[1 + n + k] is None else pair[1 + n + k] / 100
        out.append(r)

    self_meta = _meta_at(meta, i)
    return {
        "ticker": tickers[i],
        "noise": data.get("noise") or {},
        "self": row(i, *self_meta),
        "windows": list(WINDOWS),
        "count": len(out),
        "rows": out,
    }


def get_correl(ticker: str) -> dict:
    """한 티커의 상관 이웃 목록. 스냅샷이 없거나 유니버스 밖이면 빈 결과."""
    data = _load()
    if data is None:
        return {"error": "아직 수집된 상관 데이터가 없습니다. correl 워크플로를 실행하세요.",
                "ticker": (ticker or "").upper(), "rows": [], "count": 0,
                "windows": list(WINDOWS)}
    view = expand(data, ticker)
    if view is None:
        return {"error": f"{(ticker or '').upper()} 는 유니버스에 없습니다.",
                "ticker": (ticker or "").upper(), "rows": [], "count": 0,
                "windows": list(WINDOWS), "universe": len(data.get("tickers") or [])}
    view["updated"] = data.get("updated")
    view["asof"] = data.get("asof")
    view["universe"] = len(data.get("tickers") or [])
    view["demo"] = bool(data.get("demo")) or _demo()
    return view


def get_universe() -> dict:
    """티커 자동완성을 위한 목록(티커 + 회사명)."""
    data = _load()
    if data is None:
        return {"count": 0, "tickers": [], "names": []}
    meta = data.get("meta") or []
    return {
        "count": len(data["tickers"]),
        "asof": data.get("asof"),
        "tickers": data["tickers"],
        "names": [(m[0] if m else "") for m in meta],
    }


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
