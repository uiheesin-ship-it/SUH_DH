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

# 저장 포맷 — **상관이 아니라 수익률 행렬을 싣는다.**
#
# 예전엔 3,000종목 전부의 상관을 미리 구해 종목당 이웃 60개만 저장했다. 그러면
# 파일이 5.0MB 인데 이웃은 60개뿐이고, 정원을 어떻게 나눌지(헤지 몇 자리, ETF
# 몇 자리)를 계속 손보게 된다 — ETF 가 늘자 MU 의 이웃 60개 중 45개가 ETF 로
# 차서 실제 종목이 15개만 남은 적도 있다.
#
# 원본을 그대로 실으면 그 문제가 통째로 사라진다. 120일 창이 최장이라 130일치면
# 충분하고, 수익률을 int16(×10000)로 담으면 3,000종목이 0.8MB 다 — **미리 계산한
# 답(5.0MB)보다 작은데 이웃은 3,026개 전부 나온다.** 티커 하나를 조회할 때 드는
# 계산은 행 하나와 전체 행렬의 내적뿐이라(2.4M flops) 브라우저에서 수 밀리초다.
RETURN_SCALE = 10000        # 수익률 → int16 (1 = 0.01%p)
RETURN_NA = -32768          # 결측 표시(int16 최솟값)
STORE_DAYS = max(WINDOWS) + 10
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

    한 번 만들어 두면 **한 종목과 전체의 상관이 내적 하나**다 — ``Z @ Z[i]``.
    화면이 티커를 바꿀 때마다 이걸 하므로 3,000종목이어도 수 밀리초다.

    창 안에 결측이 하나라도 있는 종목은 그 창에서 값을 주지 않는다("그 기간
    데이터가 온전한 종목만 그 기간 상관을 갖는다"). 유동성 필터를 통과한
    종목은 결측이 거의 없다.

    float32 를 쓴다 — 화면에 소수 2자리로 보여 주므로 충분하고 메모리는 절반이다.
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


def encode_returns(R, scale: int = RETURN_SCALE) -> str:
    """수익률 행렬 → base64(int16). 결측은 RETURN_NA."""
    import base64

    import numpy as np

    X = np.asarray(R, dtype=np.float64) * scale
    lim = 32767
    Q = np.where(np.isfinite(X), np.clip(np.round(X), -lim, lim), RETURN_NA)
    return base64.b64encode(Q.astype("<i2").tobytes()).decode("ascii")


def decode_returns(blob: str, rows: int, cols: int, scale: int = RETURN_SCALE):
    """base64(int16) → 수익률 행렬(결측은 NaN)."""
    import base64

    import numpy as np

    Q = np.frombuffer(base64.b64decode(blob), dtype="<i2")
    if Q.size < rows * cols:
        raise ValueError(f"수익률 행렬이 짧습니다: {Q.size} < {rows * cols}")
    Q = Q[: rows * cols].reshape(rows, cols).astype(np.float64)
    return np.where(Q == RETURN_NA, np.nan, Q / scale)


def _matrices(data: dict):
    """저장된 행렬을 펼쳐 (원시 R, 잔차 E) 를 돌려준다.

    잔차 = 실제 − 베타 × 시장. 베타는 수집 때 1년치로 구해 메타에 실어 두었다 —
    여기서 130일로 다시 구하면 값이 달라지므로 그대로 쓴다.
    """
    import numpy as np

    tickers = data.get("tickers") or []
    days = int(data.get("days") or 0)
    scale = int(data.get("scale") or RETURN_SCALE)
    R = decode_returns(data["returns"], len(tickers), days, scale)
    mkt = decode_returns(data["market_returns"], 1, days, scale)[0]
    mkt = np.where(np.isfinite(mkt), mkt, 0.0)
    meta = data.get("meta") or []
    beta = np.array([(_meta_at(meta, i)[3] or 0) / 100 for i in range(len(tickers))])
    return R, R - beta[:, None] * mkt[None, :]


def expand(data: dict, ticker: str) -> dict | None:
    """한 종목과 **유니버스 전체**의 상관을 구해 행 목록으로 편다.

    미리 계산해 둔 이웃을 찾아보는 게 아니라 지금 계산한다 — 행 하나와 전체
    행렬의 내적이라 3,000종목이어도 수 밀리초다. 그래서 이웃 수 상한이 없다.
    """
    import numpy as np

    tickers = data.get("tickers") or []
    try:
        i = tickers.index(ticker.upper().strip())
    except ValueError:
        return None

    meta = data.get("meta") or []
    windows = list(data.get("windows") or WINDOWS)
    R, E = _matrices(data)

    corr: dict[str, object] = {}
    for kind, M in (("raw", R), ("res", E)):
        for w in windows:
            Z, ok = standardized(M, window=w)
            v = Z @ Z[i] if ok[i] else np.full(len(tickers), np.nan)
            corr[f"{kind}{w}"] = np.where(ok, np.clip(v, -1.0, 1.0), np.nan)

    def row(j):
        name, sector, industry, beta, mcap, dvol, is_etf = _meta_at(meta, j)
        etf = bool(is_etf) or industry == "Exchange Traded Fund"
        r = {"ticker": tickers[j], "name": name,
             "sector": "ETF" if etf else sector, "industry": industry,
             "beta": (beta or 0) / 100, "market_cap": (mcap or 0) * 1e6,
             "dollar_volume": (dvol or 0) * 1e6, "is_etf": etf}
        for key, vals in corr.items():
            x = vals[j]
            r[key] = None if not np.isfinite(x) else round(float(x), 4)
        return r

    out = [row(j) for j in range(len(tickers)) if j != i]
    return {
        "ticker": tickers[i],
        "noise": data.get("noise") or {},
        "self": row(i),
        "windows": windows,
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
