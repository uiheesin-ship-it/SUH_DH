#!/usr/bin/env python3
"""미장 마켓 브레스 수집기 → data/breadth_us.json(시계열) + data/breadth.json(뷰).

처음에는 "이미 계산된 지표를 받아오자"는 방침이었다. TradingView 의 INDEX:S5FI
계열이 딱 그것이라 거기부터 시도했는데, 실전 2회 실행에서 막혔다 — 스캐너의
america/global 엔드포인트는 응답은 하면서 INDEX 심볼에 대해 0행을 주고,
단건 조회도 close 를 돌려주지 않는다. 웹 화면 전용 데이터로 보인다. FRED 의
하이일드 스프레드도 러너에서 계속 read timeout 이었다(이 저장소의 기존
fred-rates 워크플로 역시 결과물을 한 번도 남기지 못했다).

그래서 지금 구조는 이렇다.

  1. Yahoo(yfinance) 가격 파생 : RSP/SPY · VIX 기간구조 · HYG/LQD · XLP/SPY ·
     200일선 이격. 가격에서 나오므로 과거치가 한 번에 채워진다.
  2. 구성종목 직접 계산        : S&P 500 · Nasdaq 100 종가로 %>20/50/200일선,
     그리고 S&P 500 안의 신고가−신저가 · 상승−하락 종목수.

TradingView 는 숫자 수집에서는 빠지고 화면 하단 위젯 차트로만 남는다 —
NYSE 전체(약 3,000 종목) 기준 A/D·맥클렐란은 거기서 눈으로 본다.

결과는 날짜별 시계열(series)에 병합되므로 여러 번 실행해도 안전하고, 소스가
바뀌어도 이미 쌓인 과거 값은 보존된다.

  python tools/breadth_us.py                # 전체 수집(Yahoo + 구성종목 계산)
  python tools/breadth_us.py --no-compute   # Yahoo 만(빠른 점검용)
  python tools/breadth_us.py --period 5y    # 더 긴 과거치로 백필

샌드박스에서는 외부 호스트가 막혀 있으므로 GitHub Actions 에서 실행한다.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.breadth import MAX_HISTORY_DAYS  # noqa: E402

OUT = ROOT / "data" / "breadth_us.json"     # 원본 시계열(누적)
VIEW = ROOT / "data" / "breadth.json"       # 화면이 그대로 그리는 파생 뷰
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# Yahoo 에서 받는 ETF/지수. ^VXV(구 3개월 VIX)는 상장폐지되어 뺐다 — ^VIX3M 만 산다.
YF_TICKERS = ["SPY", "QQQ", "RSP", "^VIX", "^VIX3M", "HYG", "LQD", "XLP"]

# S&P 500 구성종목: 공개 데이터셋 저장소의 CSV(매일 갱신되는 커뮤니티 유지 목록).
SPX_CONSTITUENTS_CSV = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)

# Nasdaq 100: 위와 달리 믿을 만한 공개 CSV 를 찾지 못해 목록을 직접 들고 있다.
# 구성 변경은 보통 연 1회(12월 정기변경)뿐이고, 빠진/사라진 티커는 가격이 안
# 내려오면 분모에서 자동으로 제외되므로 조금 낡아도 값이 크게 틀어지지 않는다.
# 정기변경 뒤에는 한 번 손봐 주는 게 좋다. (기준: 2025년 12월 정기변경)
NDX_100 = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN",
    "AMZN", "ANSS", "APP", "ARM", "ASML", "AVGO", "AXON", "AZN", "BIIB", "BKNG",
    "BKR", "CCEP", "CDNS", "CDW", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD",
    "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC",
    "FANG", "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON", "IDXX",
    "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LIN", "LRCX", "LULU", "MAR",
    "MCHP", "MDB", "MDLZ", "MELI", "META", "MNST", "MRVL", "MSFT", "MU", "NFLX",
    "NVDA", "NXPI", "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP",
    "PLTR", "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SNPS", "TEAM", "TMUS",
    "TSLA", "TTD", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDAY", "XEL", "ZS",
]

# 52주 신고가/신저가 판정 창(거래일). 52주 ≈ 252거래일.
HIGH_LOW_WINDOW = 252


# ------------------------------------------------------------------ http
def _get(url: str, timeout: int = 30, retries: int = 3,
         data: bytes | None = None, headers: dict | None = None) -> str:
    """재시도가 의미 있는 실패만 재시도한다.

    404/400 처럼 "이 주소가 틀렸다"는 응답은 몇 번을 더 보내도 같으므로 즉시
    포기한다. 429(과요청)와 5xx, 타임아웃 같은 일시적 실패만 백오프하며
    다시 시도한다.
    """
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:
                raise                      # 주소/요청이 틀린 것 — 재시도 무의미
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa: BLE001 - 네트워크/타임아웃은 재시도
            last = e
            time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


# --------------------------------------------------------- 가격 다운로드
def download_closes(tickers: list[str], period: str = "2y"):
    """티커 목록의 일별 종가 표(행=날짜, 열=티커). 실패한 티커는 열이 비어 있다."""
    import yfinance as yf

    df = yf.download(tickers, period=period, interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    close = df["Close"] if "Close" in df else df
    return close.dropna(how="all")


# ------------------------------------------------------------- 1. Yahoo
def fetch_yahoo(period: str = "2y") -> dict[str, dict[str, float]]:
    """날짜 → {지표: 값}. 가격 파생이라 과거치가 한 번에 채워진다."""
    close = download_closes(YF_TICKERS, period)

    def col(t):
        return close[t] if t in close else None

    spy, qqq, rsp = col("SPY"), col("QQQ"), col("RSP")
    vix, vix3m = col("^VIX"), col("^VIX3M")
    hyg, lqd, xlp = col("HYG"), col("LQD"), col("XLP")

    missing = [t for t in YF_TICKERS if t not in close or not close[t].notna().any()]
    if missing:
        print(f"  yahoo: no data for {', '.join(missing)}")

    out: dict[str, dict[str, float]] = {}

    def put(d, key, val):
        if val is None:
            return
        try:
            f = float(val)
        except (TypeError, ValueError):
            return
        if f != f:  # NaN
            return
        out.setdefault(d, {})[key] = round(f, 4)

    # 비율 시계열은 20거래일 변화율로 환산해야 의미가 생긴다(수준은 무의미).
    def ratio_20d(a, b, key):
        if a is None or b is None:
            return
        r = (a / b).dropna()
        for i in range(20, len(r)):
            prev = r.iloc[i - 20]
            if prev:
                put(str(r.index[i].date()), key, (r.iloc[i] / prev - 1) * 100)

    ratio_20d(rsp, spy, "RSP_SPY_20D")
    ratio_20d(hyg, lqd, "HYG_LQD_20D")
    ratio_20d(xlp, spy, "XLP_SPY_20D")

    if vix is not None and vix3m is not None:
        for d, v in (vix3m / vix).dropna().items():
            put(str(d.date()), "VIX_TERM", v)
    if vix is not None:
        for d, v in vix.dropna().items():
            put(str(d.date()), "VIX", v)

    for s, key in ((spy, "SPY_VS_200"), (qqq, "QQQ_VS_200")):
        if s is None:
            continue
        s = s.dropna()
        gap = (s / s.rolling(200).mean() - 1) * 100
        for d, v in gap.dropna().items():
            put(str(d.date()), key, v)

    return out


def yahoo_last_session(rows: dict[str, dict]) -> str | None:
    """Yahoo 시계열의 마지막 날짜 = 미국 장 기준 최신 거래일."""
    return max(rows) if rows else None


# ------------------------------------------------- 2. 구성종목 직접 계산
def spx_constituents() -> list[str]:
    try:
        txt = _get(SPX_CONSTITUENTS_CSV)
    except Exception as e:  # noqa: BLE001
        print(f"  S&P 500 constituent list failed: {e}")
        return []
    syms = []
    for row in csv.DictReader(io.StringIO(txt)):
        s = (row.get("Symbol") or "").strip()
        if s:
            syms.append(s.replace(".", "-"))  # BRK.B -> BRK-B (Yahoo 표기)
    return syms


def pct_above_ma(close, windows: dict[int, str]) -> dict[str, dict[str, float]]:
    """구성종목 종가로 "N일선 위 종목 비율"을 구한다.

    분모는 그날 값이 있고 이동평균도 계산되는 종목만 센다 — 상장 전이거나
    거래가 없는 종목이 비율을 흐리지 않게.
    """
    out: dict[str, dict[str, float]] = {}
    if close is None or close.empty:
        return out
    for window, key in windows.items():
        ma = close.rolling(window).mean()
        valid = close.notna() & ma.notna()
        pct = ((close > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, float("nan")) * 100
        for d, v in pct.dropna().items():
            out.setdefault(str(d.date()), {})[key] = round(float(v), 2)
    return out


def advance_decline(close, key: str = "SPX_AD") -> dict[str, dict[str, float]]:
    """전일 대비 오른 종목수 − 내린 종목수.

    NaN(그날 거래 없음)은 diff 도 NaN 이라 양쪽 어디에도 안 들어간다.
    """
    out: dict[str, dict[str, float]] = {}
    if close is None or close.empty:
        return out
    diff = close.diff()
    net = (diff > 0).sum(axis=1) - (diff < 0).sum(axis=1)
    for d, v in net.items():
        out.setdefault(str(d.date()), {})[key] = int(v)
    return out


def new_high_low(close, key: str = "SPX_NHNL",
                 window: int = HIGH_LOW_WINDOW) -> dict[str, dict[str, float]]:
    """52주 신고가 종목수 − 신저가 종목수.

    오늘 종가가 지난 252거래일(오늘 포함) 최고가와 같으면 신고가로 센다.
    """
    out: dict[str, dict[str, float]] = {}
    if close is None or close.empty:
        return out
    roll_max = close.rolling(window).max()
    roll_min = close.rolling(window).min()
    valid = close.notna() & roll_max.notna()
    highs = ((close >= roll_max) & valid).sum(axis=1)
    lows = ((close <= roll_min) & valid).sum(axis=1)
    net = highs - lows
    # 창이 다 차기 전 구간은 값이 없다(전부 NaN 인 날은 건너뛴다).
    for d in close.index[valid.any(axis=1)]:
        out.setdefault(str(d.date()), {})[key] = int(net.loc[d])
    return out


# ------------------------------------------------------------------ merge
def load_existing() -> dict:
    if not OUT.exists():
        return {"series": {}, "sources": {}, "notes": []}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"series": {}, "sources": {}, "notes": []}
    if not isinstance(data, dict):
        return {"series": {}, "sources": {}, "notes": []}
    data.setdefault("series", {})
    data.setdefault("sources", {})
    return data


def merge(series: dict, rows: dict[str, dict[str, float]]) -> int:
    """날짜별 값을 병합. 새로 들어온 값이 기존 값을 덮는다."""
    n = 0
    for d, vals in rows.items():
        bucket = series.setdefault(d, {})
        for k, v in vals.items():
            if v is None:
                continue
            bucket[k] = v
            n += 1
    return n


def trim(series: dict, keep: int = MAX_HISTORY_DAYS) -> dict:
    dates = sorted(series)
    if len(dates) <= keep:
        return series
    return {d: series[d] for d in dates[-keep:]}


def drop_retired(series: dict, live_keys: set[str]) -> int:
    """레지스트리에서 사라진 지표의 과거 값을 시계열에서 치운다.

    TradingView 경로를 접으면서 NHNL·ADDN 같은 키가 레지스트리에서 빠졌다.
    남겨 두면 아무도 안 읽는 데이터가 파일만 키우므로 같이 정리한다.
    """
    n = 0
    for vals in series.values():
        for k in [k for k in vals if k not in live_keys]:
            del vals[k]
            n += 1
    return n


def main() -> None:
    argv = sys.argv[1:]
    do_compute = "--no-compute" not in argv
    period = "2y"
    if "--period" in argv:
        period = argv[argv.index("--period") + 1]

    from app.breadth import BY_KEY

    data = load_existing()
    series = data["series"]
    sources: dict[str, str] = data.get("sources") or {}
    notes: list[str] = []

    # --- Yahoo 파생비율. 거래일 기준(anchor)도 여기서 얻는다. --------------
    print(f"Fetching Yahoo-derived ratios (period={period}) ...")
    yrows: dict[str, dict[str, float]] = {}
    try:
        yrows = fetch_yahoo(period)
        merge(series, yrows)
        for k in ("RSP_SPY_20D", "HYG_LQD_20D", "XLP_SPY_20D", "VIX_TERM",
                  "VIX", "SPY_VS_200", "QQQ_VS_200"):
            sources[k] = "yahoo"
        print(f"  {len(yrows)} dates from Yahoo.")
    except Exception as e:  # noqa: BLE001
        print(f"  yahoo failed: {e}")
        notes.append(f"Yahoo 파생지표 수집 실패: {e}")

    session = yahoo_last_session(yrows) or str(date.today())
    print(f"  anchor session = {session}")

    # --- S&P 500: %>이평선 + 상승/하락 + 신고가/신저가 ---------------------
    if do_compute:
        print(f"Computing S&P 500 breadth (period={period}) ...")
        try:
            syms = spx_constituents()
            print(f"  {len(syms)} constituents.")
            close = download_closes(syms, period) if syms else None
            if close is not None and not close.empty:
                rows = pct_above_ma(close, {20: "S5TW", 50: "S5FI", 200: "S5TH"})
                merge(series, rows)
                merge(series, advance_decline(close))
                merge(series, new_high_low(close))
                for k in ("S5TW", "S5FI", "S5TH", "SPX_AD", "SPX_NHNL"):
                    sources[k] = "computed"
                print(f"  {len(rows)} dates computed (%>MA, A/D, 신고가−신저가).")
            else:
                notes.append("S&P 500 구성종목 가격 수신 실패")
        except Exception as e:  # noqa: BLE001
            print(f"  S&P 500 compute failed: {e}")
            notes.append(f"S&P 500 직접 계산 실패: {e}")

        # --- Nasdaq 100: %>이평선 ----------------------------------------
        print(f"Computing Nasdaq 100 breadth ({len(NDX_100)} names) ...")
        try:
            close = download_closes(NDX_100, period)
            if close is not None and not close.empty:
                rows = pct_above_ma(close, {50: "NDFI", 200: "NDTH"})
                merge(series, rows)
                for k in ("NDFI", "NDTH"):
                    sources[k] = "computed"
                print(f"  {len(rows)} dates computed.")
            else:
                notes.append("Nasdaq 100 구성종목 가격 수신 실패")
        except Exception as e:  # noqa: BLE001
            print(f"  Nasdaq 100 compute failed: {e}")
            notes.append(f"Nasdaq 100 직접 계산 실패: {e}")
    else:
        print("Skipping constituent computation (--no-compute).")

    live = set(BY_KEY)
    removed = drop_retired(series, live)
    if removed:
        print(f"  dropped {removed} values of retired metrics.")
    sources = {k: v for k, v in sources.items() if k in live}

    data["series"] = trim(series)
    data["sources"] = sources
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["asof"] = max(data["series"]) if data["series"] else None
    data["notes"] = notes

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")
    latest = data["series"].get(data["asof"] or "", {})
    print(f"Wrote {OUT} — {len(data['series'])} dates, "
          f"{len(latest)} metrics on {data['asof']}.")

    # 구간 판정 · 종합점수 · 다이버전스 경고까지 붙인 뷰를 같이 커밋한다.
    # 정적 페이지(GitHub Pages)는 이 파일만 읽으면 되므로 채점 로직이 파이썬
    # 한 곳에만 있게 된다 — JS 에 같은 임계값을 복제하지 않으려는 것.
    from app.breadth import get_breadth

    view = get_breadth()
    VIEW.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
    comp = view.get("composite") or {}
    print(f"Wrote {VIEW} — 수집 {view.get('count')}/{view.get('total')}, "
          f"종합 {comp.get('score')} ({comp.get('regime')}), "
          f"커버리지 {comp.get('coverage')}%, 경고 {len(view.get('alerts') or [])}건.")


if __name__ == "__main__":
    main()
