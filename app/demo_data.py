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


def demo_news() -> dict:
    """Sample global-news digest (already in Korean) for offline/sandbox use.

    Shape matches ``news.get_news()`` output so the frontend renders identically.
    """
    now = datetime.utcnow()

    def ts(hours: float) -> float:
        return (now - timedelta(hours=hours)).timestamp()

    raw = [
        # (source, reliability, hours_ago, categories, en_title, ko_title, ko_summary)
        ("Reuters", 5, 1.5, ["반도체", "AI", "수출규제"],
         "US weighs tighter curbs on AI chip exports to China",
         "미국, 중국向 AI 반도체 수출 규제 추가 강화 검토",
         "미 상무부가 엔비디아 등 첨단 AI 가속기의 대중국 수출을 더 옥죄는 추가 규제를 검토 중인 것으로 알려졌다."),
        ("Bloomberg", 5, 2.0, ["미국금리"],
         "Fed holds rates, signals one cut later this year",
         "연준, 금리 동결…올해 한 차례 인하 시사",
         "FOMC가 기준금리를 동결하고 연내 1회 인하 가능성을 점도표로 시사하며 시장의 기대를 일부 되돌렸다."),
        ("Nikkei", 4, 3.0, ["반도체", "데이터센터"],
         "TSMC raises capex as AI data-center orders surge",
         "TSMC, AI 데이터센터 수주 급증에 설비투자 상향",
         "세계 최대 파운드리 TSMC가 AI 서버용 첨단 패키징 수요 폭증에 연간 설비투자 전망을 상향했다."),
        ("FT", 5, 4.0, ["에너지", "원자재"],
         "Oil jumps 3% as Middle East tensions threaten supply",
         "중동 긴장에 공급 우려…유가 3% 급등",
         "중동 지정학적 리스크가 다시 부각되며 브렌트유가 장중 3% 넘게 올라 배럴당 90달러에 근접했다."),
        ("WSJ", 5, 5.0, ["실적·가이던스", "AI", "반도체"],
         "Broadcom lifts AI revenue forecast, shares rally",
         "브로드컴, AI 매출 전망 상향에 주가 급등",
         "브로드컴이 맞춤형 AI 칩 수요를 근거로 연간 AI 매출 가이던스를 올리며 시간외 주가가 크게 뛰었다."),
        ("Reuters", 5, 6.0, ["관세", "미중갈등"],
         "China retaliates with tariffs on US farm goods",
         "중국, 미국산 농산물에 보복 관세",
         "미국의 관세 인상에 맞서 중국이 대두·돼지고기 등 미국산 농산물에 보복 관세를 부과하기로 했다."),
        ("Bloomberg", 5, 7.0, ["전력·인프라", "데이터센터", "에너지"],
         "Power demand from data centers strains US grid",
         "데이터센터 전력 수요에 미 전력망 '비상'",
         "AI 데이터센터 급증으로 미국 전력 수요가 빠르게 늘며 전력 인프라·유틸리티 투자 확대 논의가 가속화되고 있다."),
        ("CNBC", 4, 8.0, ["증시", "미국금리"],
         "S&P 500 hits record as cooling inflation lifts stocks",
         "인플레 둔화에 S&P500 사상 최고치",
         "예상보다 낮은 물가 지표에 금리 인하 기대가 살아나며 S&P500과 나스닥이 사상 최고치로 마감했다."),
        ("FT", 5, 9.0, ["환율"],
         "Yen slides to fresh low, raising intervention risk",
         "엔화 추가 약세…일본 개입 경계감 고조",
         "미일 금리차 확대로 엔화가 다시 연저점을 경신하며 일본 당국의 외환시장 개입 가능성이 거론된다."),
        ("Nikkei", 4, 10.0, ["반도체", "수출규제"],
         "Japan tightens chip-tool export rules to China",
         "일본, 중국向 반도체 장비 수출 규제 강화",
         "일본이 미국과 보조를 맞춰 첨단 반도체 제조장비의 대중국 수출 통제 품목을 추가로 확대했다."),
        ("WSJ", 5, 12.0, ["원자재"],
         "Copper hits record on supply fears and AI demand",
         "구리, 공급 차질·AI 수요에 사상 최고가",
         "주요 광산 차질과 전력·AI 인프라 수요가 맞물리며 구리 선물 가격이 사상 최고 수준으로 올랐다."),
        ("Bloomberg", 5, 14.0, ["실적·가이던스"],
         "Micron beats on memory demand, guides higher",
         "마이크론, 메모리 호황에 실적·가이던스 동반 상회",
         "마이크론이 AI용 고대역폭메모리(HBM) 수요 덕에 분기 실적이 컨센서스를 웃돌고 다음 분기 전망도 상향했다."),
        ("Reuters", 5, 16.0, ["에너지", "원자재"],
         "OPEC+ extends output cuts to support prices",
         "OPEC+, 가격 방어 위해 감산 연장",
         "OPEC+가 유가 하단을 떠받치기 위해 기존 감산 조치를 다음 분기까지 연장하기로 합의했다."),
        ("CNBC", 4, 18.0, ["AI", "데이터센터"],
         "Microsoft, OpenAI plan multibillion-dollar data-center buildout",
         "MS·오픈AI, 수십억 달러 데이터센터 증설 추진",
         "마이크로소프트와 오픈AI가 차세대 AI 모델 학습을 위해 대규모 데이터센터 증설 계획을 추진 중인 것으로 전해졌다."),
        # --- AI 인프라 공급망(무료 매체 위주) ---
        ("The Register", 3, 2.5, ["AI인프라", "반도체", "데이터센터"],
         "Broadcom, Nvidia push co-packaged optics for next-gen AI networking",
         "브로드컴·엔비디아, 차세대 AI 네트워킹용 CPO(공동패키지 광학) 도입 가속",
         "전력·지연을 줄이려는 CPO 채택이 빨라지며 실리콘 포토닉스·광 트랜시버 공급망이 수혜를 볼 전망이다."),
        ("Yahoo Finance", 3, 4.5, ["AI인프라", "반도체"],
         "SK Hynix, Samsung race to ramp HBM4 for AI accelerators",
         "SK하이닉스·삼성, AI 가속기용 HBM4 양산 경쟁",
         "차세대 GPU에 탑재될 HBM4 양산 시점을 놓고 메모리 3사가 경쟁하며 DRAM 업황 회복을 견인하고 있다."),
        ("DataCenterDynamics", 3, 6.5, ["AI인프라", "전력·인프라", "데이터센터"],
         "Bloom Energy to supply solid-oxide fuel cells for AI data center power",
         "블룸에너지, AI 데이터센터에 SOFC 연료전지 전력 공급",
         "전력망 접속 지연을 피하려는 데이터센터들이 SOFC 연료전지 등 온사이트 발전으로 눈을 돌리고 있다."),
        ("CNBC", 4, 9.5, ["AI인프라", "전력·인프라"],
         "GE Vernova orders jump as data centers scramble for gas turbines",
         "GE버노바, 데이터센터 가스터빈 수요 급증에 수주 확대",
         "AI 전력 수요 폭증으로 발전엔진·가스터빈 공급이 빠듯해지며 관련 설비 업체 주문이 크게 늘었다."),
    ]

    paywalled = {"Bloomberg", "FT", "WSJ", "Nikkei"}
    items = []
    for source, rel, hours, cats, en, ko, summary in raw:
        items.append(
            {
                "title": en,
                "title_ko": ko,
                "summary_ko": summary,
                "source": source,
                "reliability": rel,
                "paywall": source in paywalled,
                "categories": cats,
                "link": "https://www.example.com/markets/" + en.lower().replace(" ", "-")[:60],
                "published": (now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M UTC"),
                "published_ts": ts(hours),
            }
        )
    # Newest-first, like the live digest.
    items.sort(key=lambda x: x["published_ts"], reverse=True)
    return {
        "built": now.replace(microsecond=0).isoformat() + "+00:00",
        "count": len(items),
        "items": items,
        "demo": True,
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
