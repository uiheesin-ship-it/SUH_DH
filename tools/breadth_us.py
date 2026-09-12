#!/usr/bin/env python3
"""미장 마켓 브레스 수집기 → data/breadth_us.json.

값을 직접 계산하는 대신 시장이 이미 계산해 둔 지표를 받아온다. 원천은 3개이고
각각 대체 경로를 둔다 — 무료 소스는 언제든 막히므로 하나가 죽어도 나머지 칸이
채워지게 하는 게 이 파일의 설계 목표다.

  1. TradingView 스캐너  : INDEX:S5FI 같은 브레스 지수(화면의 위젯과 같은 값).
                           당일 값만 주므로 하루 한 줄씩 쌓인다.
  2. Yahoo(yfinance)     : RSP/SPY · VIX 기간구조 · HYG/LQD · XLP/SPY · 200일선
                           이격. 가격에서 파생되므로 과거치를 한 번에 채운다.
  3. FRED                : 하이일드 스프레드(BAMLH0A0HYM2). 키 불필요.
  4. 폴백 직접 계산       : 1번이 막히면 S&P 500 구성종목 종가로 %>20/50/200일선
                           을 직접 구한다. 느리지만 과거치까지 한 번에 복구된다.

결과는 날짜별 시계열(series)에 병합되므로 여러 번 실행해도 안전하고, 소스가
바뀌어도 이미 쌓인 과거 값은 보존된다.

  python tools/breadth_us.py              # 평소 수집(TradingView + Yahoo + FRED)
  python tools/breadth_us.py --compute    # 구성종목 직접 계산까지 강제
  python tools/breadth_us.py --no-tv      # TradingView 건너뛰고 폴백만

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

from app.breadth import MAX_HISTORY_DAYS, METRICS  # noqa: E402

OUT = ROOT / "data" / "breadth_us.json"     # 원본 시계열(누적)
VIEW = ROOT / "data" / "breadth.json"       # 화면이 그대로 그리는 파생 뷰
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# TradingView 에서 그대로 받아오는 심볼(레지스트리의 tradingview 지표) + 파생을
# 만들기 위해 필요한 원재료 심볼.
TV_RAW = {
    "MAHN": "INDEX:MAHN",   # NYSE 52주 신고가 종목수
    "MALN": "INDEX:MALN",   # NYSE 52주 신저가 종목수
    "UVOL": "INDEX:UVOL",   # NYSE 상승 종목 거래량
    "DVOL": "INDEX:DVOL",   # NYSE 하락 종목 거래량
}

# Yahoo 가격에서 파생하는 지표: (티커들, 계산 방식)
# ^VIX3M 은 첫 실전 실행에서 내려오지 않았다(Yahoo 가 심볼별로 들쭉날쭉하다).
# ^VXV 는 같은 3개월 VIX 의 옛 심볼이라 둘 다 받아 먼저 잡히는 쪽을 쓴다.
YF_TICKERS = ["SPY", "QQQ", "RSP", "^VIX", "^VIX3M", "^VXV", "HYG", "LQD", "XLP"]
VIX3M_CANDIDATES = ("^VIX3M", "^VXV")

FRED_SERIES = {"HY_OAS": "BAMLH0A0HYM2"}

# 폴백 직접 계산용 S&P 500 구성종목(공개 데이터셋 저장소의 CSV).
SPX_CONSTITUENTS_CSV = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)


# ------------------------------------------------------------------ http
def _get(url: str, timeout: int = 30, retries: int = 3,
         data: bytes | None = None, headers: dict | None = None) -> str:
    """재시도가 의미 있는 실패만 재시도한다.

    404/400 처럼 "이 주소가 틀렸다"는 응답은 몇 번을 더 보내도 같으므로 즉시
    포기한다 — 첫 실행에서 TradingView 심볼 14개가 각각 3번씩 404 를 맞으며
    백오프 sleep 으로 2분을 버린 적이 있다. 429(과요청)와 5xx, 타임아웃 같은
    일시적 실패만 백오프하며 다시 시도한다.
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


# ----------------------------------------------------- 1. TradingView
# 스캐너 엔드포인트 후보. 첫 실전 실행에서 /index/scan 이 전 심볼 404 를 돌려줬다
# — 경로가 틀린 것이지 심볼이 없는 게 아니다. 어느 형태가 살아 있는지 여기서
# 확정할 방법이 없으므로(샌드박스가 tradingview 를 차단) 후보를 순서대로 시도하고
# 성공한 변형을 로그에 남긴다. 다음 실행의 로그가 곧 답이 된다.
TV_BATCH_URLS = (
    "https://scanner.tradingview.com/america/scan",
    "https://scanner.tradingview.com/global/scan?label-product=markets-screener",
    "https://scanner.tradingview.com/index/scan",
)
# 단건 조회는 no_404=true 가 없으면 필드 하나만 없어도 404 를 돌려준다.
TV_SYMBOL_URL = ("https://scanner.tradingview.com/symbol"
                 "?symbol={sym}&fields=close&no_404=true")

TV_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Accept": "application/json",
}


def _tv_batch(url: str, tickers: list[str]) -> dict[str, float]:
    body = json.dumps({
        "symbols": {"tickers": tickers, "query": {"types": []}},
        "columns": ["close"],
    }).encode()
    txt = _get(url, data=body, retries=2, headers=TV_HEADERS)
    rows = (json.loads(txt) or {}).get("data") or []
    out = {}
    for r in rows:
        v = (r.get("d") or [None])[0]
        if isinstance(v, (int, float)):
            out[r.get("s")] = float(v)
    return out


def fetch_tradingview(symbols: dict[str, str]) -> dict[str, float]:
    """{키: 심볼} → {키: 최신 종가}. 받지 못한 심볼은 그냥 빠진다.

    배치 엔드포인트 후보를 차례로 시도해 하나라도 값을 주면 채택하고, 그래도
    빈 심볼은 단건 조회로 한 번 더 훑는다. 어느 경로도 안 되면 빈 dict 를
    돌려주고 호출부가 직접 계산 폴백으로 넘어간다.
    """
    out: dict[str, float] = {}
    tickers = list(symbols.values())

    for url in TV_BATCH_URLS:
        try:
            got = _tv_batch(url, tickers)
        except Exception as e:  # noqa: BLE001
            print(f"  tradingview batch {url.split('/')[3]} failed: {e}")
            continue
        if got:
            print(f"  tradingview batch OK via {url} ({len(got)} symbols)")
            for key, sym in symbols.items():
                if sym in got:
                    out[key] = got[sym]
            break
        print(f"  tradingview batch {url.split('/')[3]} returned no rows")

    missing = {k: s for k, s in symbols.items() if k not in out}
    for key, sym in missing.items():
        try:
            txt = _get(TV_SYMBOL_URL.format(sym=urllib.parse.quote(sym)),
                       retries=1, headers={"Referer": "https://www.tradingview.com/"})
            v = (json.loads(txt) or {}).get("close")
            if isinstance(v, (int, float)):
                out[key] = float(v)
        except Exception as e:  # noqa: BLE001
            print(f"  tradingview {sym} failed: {e}")
        time.sleep(0.2)
    return out


# ------------------------------------------------------------ 2. Yahoo
def _pct_change(series, back: int) -> float | None:
    """back 거래일 전 대비 변화율(%)."""
    vals = [v for v in series if v is not None]
    if len(vals) <= back:
        return None
    prev = vals[-1 - back]
    if not prev:
        return None
    return round((vals[-1] / prev - 1) * 100, 4)


def fetch_yahoo(period: str = "2y") -> dict[str, dict[str, float]]:
    """날짜 → {지표: 값}. 가격 파생이라 과거치가 한 번에 채워진다."""
    import pandas as pd  # noqa: F401 - yfinance 가 끌고 오는 의존성
    import yfinance as yf

    df = yf.download(YF_TICKERS, period=period, interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    close = df["Close"] if "Close" in df else df
    close = close.dropna(how="all")

    def col(t):
        return close[t] if t in close else None

    spy, qqq, rsp = col("SPY"), col("QQQ"), col("RSP")
    vix = col("^VIX")
    vix3m = next((c for c in map(col, VIX3M_CANDIDATES)
                  if c is not None and c.notna().any()), None)
    hyg, lqd, xlp = col("HYG"), col("LQD"), col("XLP")

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
                put(str(r.index[i].date()), key,
                    (r.iloc[i] / prev - 1) * 100)

    missing = [t for t in YF_TICKERS if t not in close or not close[t].notna().any()]
    if missing:
        print(f"  yahoo: no data for {', '.join(missing)}")

    ratio_20d(rsp, spy, "RSP_SPY_20D")
    ratio_20d(hyg, lqd, "HYG_LQD_20D")
    ratio_20d(xlp, spy, "XLP_SPY_20D")

    if vix is not None and vix3m is not None:
        term = (vix3m / vix).dropna()
        for d, v in term.items():
            put(str(d.date()), "VIX_TERM", v)
    if vix is not None:
        for d, v in vix.dropna().items():
            put(str(d.date()), "VIX", v)

    # 200일선 이격률.
    for s, key in ((spy, "SPY_VS_200"), (qqq, "QQQ_VS_200")):
        if s is None:
            continue
        s = s.dropna()
        ma = s.rolling(200).mean()
        gap = (s / ma - 1) * 100
        for d, v in gap.dropna().items():
            put(str(d.date()), key, v)

    return out


def yahoo_last_session(rows: dict[str, dict]) -> str | None:
    """Yahoo 시계열의 마지막 날짜 = 미국 장 기준 최신 거래일."""
    return max(rows) if rows else None


# ------------------------------------------------------------- 3. FRED
def fetch_fred(series: dict[str, str], cosd: str = "2023-01-01") -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key, sid in series.items():
        try:
            # 첫 실전 실행이 read timeout 으로 떨어졌다. FRED 는 CSV 를 즉석에서
            # 만들어 주느라 가끔 느리므로 기본값(30s/3회)보다 넉넉히 준다.
            txt = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv"
                       f"?id={sid}&cosd={cosd}", timeout=90, retries=4)
        except Exception as e:  # noqa: BLE001
            print(f"  fred {sid} failed: {e}")
            continue
        for line in txt.splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 2:
                continue
            d, v = parts[0].strip(), parts[1].strip()
            if v in (".", ""):
                continue
            try:
                out.setdefault(d, {})[key] = float(v)
            except ValueError:
                continue
    return out


# --------------------------------------------- 4. 폴백: 구성종목 직접 계산
def spx_constituents() -> list[str]:
    try:
        txt = _get(SPX_CONSTITUENTS_CSV)
    except Exception as e:  # noqa: BLE001
        print(f"  constituent list failed: {e}")
        return []
    syms = []
    for row in csv.DictReader(io.StringIO(txt)):
        s = (row.get("Symbol") or "").strip()
        if s:
            syms.append(s.replace(".", "-"))  # BRK.B -> BRK-B (Yahoo 표기)
    return syms


def compute_pct_above_ma(tickers: list[str], period: str = "2y") -> dict[str, dict[str, float]]:
    """구성종목 종가로 20/50/200일선 위 비율을 직접 계산한다.

    TradingView 가 막혔을 때의 폴백이자, 처음 구축할 때 과거 시계열을 한 번에
    채워 넣는 수단. 500 종목을 한 번에 받으므로 수 분 걸린다.
    """
    if not tickers:
        return {}
    import yfinance as yf

    df = yf.download(tickers, period=period, interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    close = df["Close"] if "Close" in df else df
    close = close.dropna(how="all")
    if close.empty:
        return {}

    out: dict[str, dict[str, float]] = {}
    for window, key in ((20, "S5TW"), (50, "S5FI"), (200, "S5TH")):
        ma = close.rolling(window).mean()
        above = (close > ma)
        # 그날 값이 있는 종목만 분모에 넣는다(상장 전/거래정지 종목 제외).
        valid = close.notna() & ma.notna()
        pct = (above & valid).sum(axis=1) / valid.sum(axis=1).replace(0, float("nan")) * 100
        for d, v in pct.dropna().items():
            out.setdefault(str(d.date()), {})[key] = round(float(v), 2)
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


def main() -> None:
    args = set(sys.argv[1:])
    force_compute = "--compute" in args
    use_tv = "--no-tv" not in args

    data = load_existing()
    series = data["series"]
    sources: dict[str, str] = data.get("sources") or {}
    notes: list[str] = []

    # --- Yahoo 먼저. 거래일 기준(anchor)을 여기서 얻는다. ------------------
    print("Fetching Yahoo-derived ratios ...")
    yrows: dict[str, dict[str, float]] = {}
    try:
        yrows = fetch_yahoo()
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

    # --- FRED -------------------------------------------------------------
    print("Fetching FRED credit spread ...")
    frows = fetch_fred(FRED_SERIES)
    if frows:
        merge(series, frows)
        sources["HY_OAS"] = "fred"
        print(f"  {len(frows)} dates from FRED.")
    else:
        notes.append("FRED 하이일드 스프레드 수집 실패")

    # --- TradingView ------------------------------------------------------
    tv_direct = {m.key: m.symbol for m in METRICS if m.source == "tradingview"}
    tv_vals: dict[str, float] = {}
    if use_tv:
        print(f"Fetching TradingView breadth ({len(tv_direct) + len(TV_RAW)} symbols) ...")
        tv_vals = fetch_tradingview({**tv_direct, **TV_RAW})
        print(f"  {len(tv_vals)} values.")
    else:
        print("Skipping TradingView (--no-tv).")

    today_vals = {k: v for k, v in tv_vals.items() if k in tv_direct}
    for k in today_vals:
        sources[k] = "tradingview"

    # 파생: 신고가−신저가, 상승/하락 거래량 비율.
    if "MAHN" in tv_vals and "MALN" in tv_vals:
        today_vals["NHNL"] = round(tv_vals["MAHN"] - tv_vals["MALN"], 2)
        sources["NHNL"] = "tradingview"
    if tv_vals.get("DVOL"):
        today_vals["UD_VOL"] = round(tv_vals["UVOL"] / tv_vals["DVOL"], 4)
        sources["UD_VOL"] = "tradingview"

    if today_vals:
        merge(series, {session: today_vals})

    # --- 폴백: %>이평선을 못 받았으면(또는 --compute) 직접 계산 -------------
    need_pct = not all(k in today_vals for k in ("S5TW", "S5FI", "S5TH"))
    if force_compute or need_pct:
        why = "강제(--compute)" if force_compute else "TradingView 미수신"
        print(f"Computing %>MA from S&P 500 constituents ({why}) ...")
        try:
            syms = spx_constituents()
            print(f"  {len(syms)} constituents.")
            crows = compute_pct_above_ma(syms)
            if crows:
                # TradingView 값이 이미 있는 날짜/지표는 건드리지 않는다.
                fresh = {d: {k: v for k, v in vals.items()
                             if sources.get(k) != "tradingview" or k not in (series.get(d) or {})}
                         for d, vals in crows.items()}
                merge(series, fresh)
                for k in ("S5TW", "S5FI", "S5TH"):
                    sources.setdefault(k, "computed")
                print(f"  {len(crows)} dates computed.")
            else:
                notes.append("구성종목 직접 계산 실패(가격 수신 없음)")
        except Exception as e:  # noqa: BLE001
            print(f"  compute failed: {e}")
            notes.append(f"구성종목 직접 계산 실패: {e}")

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
    print(f"Wrote {VIEW} — 종합 {comp.get('score')} ({comp.get('regime')}), "
          f"경고 {len(view.get('alerts') or [])}건.")


if __name__ == "__main__":
    main()
