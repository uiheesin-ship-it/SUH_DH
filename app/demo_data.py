"""Sample data used when SUH_DH_DEMO=1.

Lets the dashboard (and tests) run without reaching Yahoo Finance / Finviz,
which is useful for UI development and for sandboxes where those hosts are
blocked by a network egress allowlist. The shape matches what
``screener.fetch_new_highs`` and ``charts`` return from the live sources.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

# Raw rows mimic the normalized output of the Finviz "New High" screener.
DEMO_ROWS = [
    # ticker, company, sector, industry, market_cap, price, change(%)
    ("NVDA", "NVIDIA Corporation", "Technology", "Semiconductors", 3.21e12, 131.26, 3.42),
    ("AVGO", "Broadcom Inc.", "Technology", "Semiconductors", 1.15e12, 245.10, 2.10),
    ("TSM", "Taiwan Semiconductor", "Technology", "Semiconductors", 9.80e11, 188.55, 1.85),
    ("MU", "Micron Technology", "Technology", "Semiconductor Memory", 1.42e11, 128.40, 4.95),
    ("LRCX", "Lam Research", "Technology", "Semiconductor Equipment", 9.60e10, 78.20, 2.30),
    ("AAPL", "Apple Inc.", "Technology", "Consumer Electronics", 3.30e12, 214.29, 1.10),
    ("MSFT", "Microsoft Corporation", "Technology", "Software - Infrastructure", 3.35e12, 449.78, 0.95),
    ("LLY", "Eli Lilly and Company", "Healthcare", "Drug Manufacturers - General", 8.30e11, 915.40, 2.75),
    ("NVO", "Novo Nordisk A/S", "Healthcare", "Drug Manufacturers - General", 5.60e11, 142.30, 1.60),
    ("ISRG", "Intuitive Surgical", "Healthcare", "Medical Instruments", 1.55e11, 432.10, 3.05),
    ("FCX", "Freeport-McMoRan", "Basic Materials", "Copper", 6.80e10, 49.85, 5.20),
    ("NEM", "Newmont Corporation", "Basic Materials", "Gold", 5.10e10, 44.20, 2.90),
    ("XOM", "Exxon Mobil Corporation", "Energy", "Oil & Gas Integrated", 4.60e11, 116.80, 1.40),
    ("JPM", "JPMorgan Chase & Co.", "Financial", "Banks - Diversified", 5.80e11, 202.15, 0.80),
    ("V", "Visa Inc.", "Financial", "Credit Services", 5.40e11, 275.60, 1.25),
    ("WMT", "Walmart Inc.", "Consumer Defensive", None, 5.50e11, 68.40, 1.05),
    ("COST", "Costco Wholesale", "Consumer Defensive", "Discount Stores", 3.60e11, 845.20, 0.70),
]


def demo_new_highs() -> list[dict]:
    rows = []
    for ticker, company, sector, industry, mcap, price, change in DEMO_ROWS:
        rows.append(
            {
                "ticker": ticker,
                "company": company,
                "sector": sector or "Unknown",
                "industry": industry,
                "market_cap": mcap,
                "price": price,
                "change_pct": change,
            }
        )
    return rows


def demo_reason(ticker: str) -> dict:
    # (English title, Korean title, publisher)
    headlines = {
        "NVDA": [("NVIDIA tops earnings estimates as data-center demand surges",
                  "엔비디아, 데이터센터 수요 급증으로 실적 추정치 상회", "Reuters")],
        "MU": [("Micron guides above consensus on AI memory boom",
                "마이크론, AI 메모리 호황에 가이던스 컨센서스 상회", "Bloomberg")],
        "LLY": [("Eli Lilly weight-loss drug shows strong trial data",
                 "일라이릴리 비만 치료제, 임상서 강력한 데이터 확인", "CNBC")],
        "FCX": [("Copper prices hit record as supply tightens",
                 "공급 위축에 구리 가격 사상 최고치", "MarketWatch")],
    }
    items = headlines.get(
        ticker,
        [(f"{ticker} hits fresh 52-week high amid sector strength",
          f"{ticker}, 섹터 강세 속 52주 신고가 경신", "Yahoo Finance")],
    )
    descriptions = {
        "NVDA": "AI·데이터센터용 GPU와 가속 컴퓨팅 플랫폼을 설계하는 반도체 기업.",
        "MU": "D램·낸드 등 메모리 반도체를 생산하는 글로벌 메모리 제조사.",
        "TSM": "세계 최대 반도체 위탁생산(파운드리) 업체.",
        "LLY": "당뇨·비만·항암 등 의약품을 개발·판매하는 글로벌 제약사.",
        "FCX": "구리·금 등을 채굴하는 광산·원자재 기업.",
    }
    now = datetime.utcnow()
    return {
        "ticker": ticker,
        "description": descriptions.get(ticker, f"{ticker}의 사업 개요(데모 데이터)."),
        "earnings_recent": ticker in {"NVDA", "MU"},
        "earnings_date": (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if ticker in {"NVDA", "MU"}
        else None,
        "news": [
            {
                "title": title,
                "title_ko": title_ko,
                "publisher": pub,
                "link": f"https://finance.yahoo.com/quote/{ticker}",
                "published": (now - timedelta(hours=i * 3)).strftime("%Y-%m-%d %H:%M"),
            }
            for i, (title, title_ko, pub) in enumerate(items)
        ],
    }


def demo_chart(ticker: str, rng: str) -> dict:
    """Deterministic synthetic OHLCV so charts render without network."""
    days = 130 if rng == "6mo" else 500
    seed = sum(ord(c) for c in ticker)
    base = 50 + seed % 200
    dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    price = base
    start = datetime.utcnow() - timedelta(days=int(days * 1.45))
    d = start
    for i in range(days):
        # skip weekends to look like trading days
        while d.weekday() >= 5:
            d += timedelta(days=1)
        drift = 0.0006 * (i)  # gentle uptrend so it ends near a high
        wave = math.sin((i + seed) / 18.0) * 0.015
        ret = drift + wave + math.sin(i * 1.7 + seed) * 0.004
        o = price
        c = price * (1 + ret)
        h = max(o, c) * (1 + abs(math.sin(i + seed)) * 0.008)
        low = min(o, c) * (1 - abs(math.cos(i + seed)) * 0.008)
        v = int(1_000_000 + abs(math.sin(i * 0.7 + seed)) * 5_000_000)
        dates.append(d.strftime("%Y-%m-%d"))
        opens.append(round(o, 2))
        highs.append(round(h, 2))
        lows.append(round(low, 2))
        closes.append(round(c, 2))
        volumes.append(v)
        price = c
        d += timedelta(days=1)
    return {
        "ticker": ticker,
        "range": rng,
        "dates": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }
