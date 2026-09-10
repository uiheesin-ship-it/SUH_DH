"""Korean 52-week-high screener (KOSPI + KOSDAQ) — the 국장 twin of app/screener.py.

Universe/metadata come from FinanceDataReader (KRX listings: name, market,
market-cap, sector). The 52-week-high test uses per-ticker OHLCV from Yahoo
(.KS/.KQ) — the one Korean source already proven to work from the GitHub Actions
build server (see app/kr.py). Excludes ETF/ETN, SPACs (스팩) and preferred
shares (…우/우B), and anything under a market-cap floor (default 1,500억원).

Everything is defensive: Korean sources can be slow/blocked from a US IP, so any
failure degrades to fewer names (or demo data) rather than aborting the build.
Output matches app/screener.get_dashboard() so the frontend/grouping is shared.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import time
from datetime import date, timedelta
from pathlib import Path

from . import cache
from .screener import group_by_sector  # reuse the US-highs sector→industry grouping

KRHIGHS_TTL = float(os.environ.get("SUH_DH_KRHIGHS_TTL", "600"))

# Persisted universe snapshot. The KOSPI/KOSDAQ listing comes from KRX
# (data.krx.co.kr) via FinanceDataReader, which KRX periodically blocks from
# datacenter (GitHub Actions) IPs — when that happens the live fetch returns an
# empty universe and every KR scan (52w/60d highs + KR base) yields 0, freezing
# the committed data for days. So we keep a last-good universe on disk and fall
# back to it. The list of tickers barely changes day to day, and the actual
# new-high test uses fresh per-ticker bars (Naver/Yahoo), so a slightly stale
# universe still produces correct, fresh results.
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_UNIVERSE_SNAPSHOT = _DATA_DIR / "kr_universe.json"
# FinanceData's community mirror of the daily KRX listing, served from GitHub —
# reachable from the build server even when data.krx.co.kr blocks it. Used as a
# KRX-independent secondary source so freshness recovers on its own.
_GH_LISTING_CACHE = (
    "https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/"
    "refs/heads/master/data/listing/krx/{date}.csv"
)
# Market-cap floor in KRW. 1,500억원 = 150,000,000,000.
MIN_MARCAP_KRW = float(os.environ.get("SUH_DH_KR_MIN_MARCAP", str(150_000_000_000)))
# Cap how many names we pull OHLCV for, to bound runtime on the scheduled build.
SCAN_LIMIT = int(os.environ.get("SUH_DH_KRHIGHS_LIMIT", "1200"))
# 52w window (trading days) and how strict "new high" is (1.0 = must equal high).
WEEK52 = 252
NEAR_RATIO = float(os.environ.get("SUH_DH_KR_NEAR_HIGH", "1.0"))


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _is_excluded(name: str | None) -> bool:
    """Drop SPACs and preferred shares by name (ETFs aren't in the stock listings)."""
    n = (name or "").strip()
    if not n:
        return True
    if "스팩" in n:
        return True
    # Preferred shares: '삼성전자우', '현대차2우B', 'LG우' … end with 우 / 우[A-C].
    if n.endswith("우") or (len(n) >= 2 and n[-1] in "ABC" and n[-2] == "우"):
        return True
    return False


def _yahoo_symbol(code: str, market: str) -> str:
    return f"{code}.{'KQ' if market == 'KOSDAQ' else 'KS'}"


def _col(df, *names):
    for n in names:
        if n in getattr(df, "columns", []):
            return n
    return None


def _fetch_listing() -> list[dict]:
    """KRX listing rows: {code, name, market, sector, industry, market_cap, price}."""
    import FinanceDataReader as fdr

    rows: list[dict] = []
    # Descriptive listing (has Sector/Industry) → map by code; optional.
    sector_map: dict[str, tuple] = {}
    try:
        krx = fdr.StockListing("KRX")
        c_code = _col(krx, "Code", "Symbol")
        c_sec = _col(krx, "Sector")
        c_ind = _col(krx, "Industry")
        if c_code:
            for _, r in krx.iterrows():
                sector_map[str(r[c_code]).zfill(6)] = (
                    (r[c_sec] if c_sec else None), (r[c_ind] if c_ind else None))
    except Exception:
        sector_map = {}

    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(market)
        except Exception:
            continue
        c_code = _col(df, "Code", "Symbol")
        c_name = _col(df, "Name")
        c_cap = _col(df, "Marcap", "MarketCap", "Market Cap")
        c_close = _col(df, "Close")
        c_chg = _col(df, "ChagesRatio", "ChangesRatio", "ChangeRatio", "Chg")
        if not c_code or not c_name:
            continue
        for _, r in df.iterrows():
            code = str(r[c_code]).zfill(6)
            name = r[c_name]
            sec, ind = sector_map.get(code, (None, None))
            rows.append({
                "code": code,
                "name": name,
                "market": market,
                "sector": (sec or market),
                "industry": ind,
                "market_cap": _num(r[c_cap]) if c_cap else None,
                "price": _num(r[c_close]) if c_close else None,
                "change_pct": _num(r[c_chg]) if c_chg else None,
            })
    return rows


def _made_new_high(bars: dict) -> bool:
    """True if today's high is the highest of the last ~52 weeks."""
    high = bars.get("high") or []
    if len(high) < 60:               # need enough history to be meaningful
        return False
    window = high[-WEEK52:]
    prior = window[:-1] or window
    today = high[-1]
    peak_prior = max(p for p in prior if p is not None) if any(p is not None for p in prior) else None
    if today is None or peak_prior is None:
        return False
    return today >= peak_prior * NEAR_RATIO


def _demo_universe() -> list[dict]:
    return [{"code": c, "name": n, "market": m, "sector": s, "industry": None,
             "market_cap": cap, "price": px}
            for c, n, m, s, cap, px, _ in _demo_base()]


def _demo_base():
    return [
        ("005930", "삼성전자", "KOSPI", "전기전자", 4.5e14, 78000, 1.9),
        ("000660", "SK하이닉스", "KOSPI", "전기전자", 1.6e14, 220000, 3.2),
        ("373220", "LG에너지솔루션", "KOSPI", "전기전자", 9.0e13, 385000, 2.1),
        ("247540", "에코프로비엠", "KOSDAQ", "화학", 1.8e13, 185000, 4.5),
        ("196170", "알테오젠", "KOSDAQ", "제약", 1.5e13, 290000, 5.1),
        ("012450", "한화에어로스페이스", "KOSPI", "기계", 3.2e13, 640000, 2.8),
    ]


def _fetch_listing_gh_cache() -> list[dict]:
    """KRX listing from FinanceData's GitHub CSV mirror (KRX-independent).

    Probes the most recent available date (the mirror lags a little behind the
    live KRX close). Returns the same row schema as _fetch_listing(). Never
    raises — an empty list means the mirror was unreachable/behind.
    """
    import urllib.request

    mkt_map = {"STK": "KOSPI", "KSQ": "KOSDAQ"}  # skip KNX (KONEX)
    today = date.today()
    for i in range(0, 10):  # look back up to ~1.5 weeks for the latest snapshot
        day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            with urllib.request.urlopen(
                _GH_LISTING_CACHE.format(date=day), timeout=20
            ) as resp:
                text = resp.read().decode("utf-8-sig", "replace")
        except Exception:
            continue
        rows: list[dict] = []
        for r in csv.DictReader(io.StringIO(text)):
            mid = r.get("MarketId")
            if mid not in mkt_map:
                continue
            rows.append({
                "code": str(r.get("Code", "")).zfill(6),
                "name": r.get("Name"),
                "market": mkt_map[mid],
                "sector": mkt_map[mid],
                "industry": None,
                "market_cap": _num(r.get("Marcap")),
                "price": _num(r.get("Close")),
                "change_pct": _num(r.get("ChagesRatio")),
            })
        if rows:
            return rows
    return []


def _save_universe_snapshot(rows: list[dict]) -> None:
    """Persist a last-good universe (best-effort; a read-only FS is fine)."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"asof": date.today().isoformat(), "count": len(rows), "rows": rows}
        _UNIVERSE_SNAPSHOT.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_universe_snapshot() -> list[dict]:
    try:
        payload = json.loads(_UNIVERSE_SNAPSHOT.read_text(encoding="utf-8"))
        return payload.get("rows") or []
    except Exception:
        return []


def _resolve_listing() -> list[dict]:
    """Best-available KRX listing: live KRX → GitHub mirror → committed snapshot.

    Refreshes the on-disk snapshot whenever a live source succeeds, so the
    scans self-heal to fresh data the moment KRX is reachable again.
    """
    listing = _fetch_listing()
    if not listing:
        listing = _fetch_listing_gh_cache()
    if listing:
        _save_universe_snapshot(listing)
        return listing
    # Both live sources are blocked/behind — reuse the last good universe so the
    # scans still run (off fresh per-ticker bars) instead of freezing at 0.
    snap = _load_universe_snapshot()
    if snap:
        print(f"  KR universe: live listing unavailable — reusing snapshot "
              f"({len(snap)} names)")
    return snap


def kr_universe(limit: int | None = None) -> list[dict]:
    """Filtered KOSPI+KOSDAQ candidate list (excl. SPAC/ETF/preferred, cap floor).

    Shared by the highs screen and the KR base screener. Each row:
    {code, name, market, sector, industry, market_cap, price}.
    """
    listing = _demo_universe() if _demo() else _resolve_listing()
    universe = [
        r for r in listing
        if not _is_excluded(r.get("name"))
        and (r.get("market_cap") is None or r["market_cap"] >= MIN_MARCAP_KRW)
    ]
    universe.sort(key=lambda r: r.get("market_cap") or 0, reverse=True)
    return universe[: (limit or SCAN_LIMIT)]


def _fetch_live() -> list[dict]:
    from . import krdata  # same-day FDR bars (Yahoo fallback), consistent with the chart

    universe = kr_universe()
    out: list[dict] = []
    for r in universe:
        sym = _yahoo_symbol(r["code"], r["market"])
        try:
            bars = krdata.fetch_kr_bars(r["code"], r["market"])
        except Exception:
            continue
        if not bars or not bars.get("high"):
            continue
        if not _made_new_high(bars):
            continue
        close = bars.get("close") or []
        price = close[-1] if close else r.get("price")
        # Prefer the change computed from the fresh bars: the listing's
        # change_pct can be stale when the universe came from a snapshot.
        change = None
        if len(close) >= 2 and close[-2]:
            change = round((close[-1] / close[-2] - 1) * 100, 2)
        if change is None:
            change = r.get("change_pct")
        out.append({
            "ticker": r["code"],
            "company": r["name"],
            "sector": r.get("sector") or r["market"],
            "industry": r.get("industry"),
            "market": r["market"],
            "yahoo": sym,
            "market_cap": r.get("market_cap"),
            "price": round(price, 2) if price is not None else None,
            "change_pct": change,
        })
        time.sleep(0.15)  # be gentle with Yahoo
    return out


def _demo_rows() -> list[dict]:
    return [{
        "ticker": c, "company": n, "sector": s, "industry": None, "market": m,
        "yahoo": _yahoo_symbol(c, m), "market_cap": cap, "price": px, "change_pct": chg,
    } for c, n, m, s, cap, px, chg in _demo_base()]


def fetch_new_highs() -> list[dict]:
    def producer():
        return _demo_rows() if _demo() else _fetch_live()

    return cache.get_or_set("kr_new_highs", KRHIGHS_TTL, producer,
                            cache_when=lambda r: bool(r) or _demo())


def get_dashboard() -> dict:
    rows = fetch_new_highs()
    return {
        "count": len(rows),
        "sectors": group_by_sector(rows),
        "demo": _demo(),
        "market_cap_currency": "KRW",
    }
