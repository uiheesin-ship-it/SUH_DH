"""Sample data used when SUH_DH_DEMO=1.

Lets the dashboard (and tests) run without reaching Yahoo Finance / Finviz,
which is useful for UI development and for sandboxes where those hosts are
blocked by a network egress allowlist. The shape matches what
``screener.fetch_new_highs`` and ``charts`` return from the live sources.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

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


def demo_earnings(ticker: str) -> list[dict]:
    """Sample earnings history (date + EPS consensus vs actual) for offline use.

    Shape matches one entry of ``earnings.get_earnings()["quarters"]``. The MU
    rows echo the attached post-earnings drift example; other tickers get a
    couple of generic quarters so the UI always has something to render.
    """
    from .earnings import _make_row  # local import avoids a cycle at module load

    now = datetime.now(timezone.utc)

    # (days_ago, eps_estimate, reported_eps)  — negative days_ago = upcoming.
    samples = {
        # quarter, estimate, actual — loosely tracking Micron's recent beats.
        "MU": [(-1, 2.83, None), (98, 1.91, 3.05), (189, 1.43, 1.79),
               (280, 1.10, 1.18), (371, 0.95, 1.05), (462, 0.50, 0.62)],
        "NVDA": [(28, 0.85, 0.89), (119, 0.75, 0.78), (210, 0.64, 0.68),
                 (301, 0.59, 0.61)],
    }
    rows_spec = samples.get(
        ticker,
        [(35, 1.20, 1.25), (126, 1.10, 1.10), (217, 1.05, 0.99), (308, 0.95, 1.02)],
    )
    rows = []
    for days_ago, est, rep in rows_spec:
        dt = now - timedelta(days=days_ago)
        rows.append(_make_row(dt, est, rep, now=now))
    rows.sort(key=lambda r: r["datetime"], reverse=True)
    return rows


def demo_guidance(ticker: str) -> list[dict]:
    """Sample next-quarter guidance vs point-in-time consensus annotations.

    Shape matches one entry of ``data/guidance.json``. Dates are computed the
    same way as ``demo_earnings`` so the guidance lands on the matching report
    row. Numbers are illustrative (echoing the attached Micron mock), not real.
    """
    if ticker.upper() != "MU":
        return []
    now = datetime.now(timezone.utc)

    def d(days_ago: int) -> str:
        return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    return [
        {
            "report_date": d(98), "guided_period": "FY26 Q3", "metric": "revenue",
            "unit": "B_USD", "guidance_mid": 33.5, "guidance_low": 32.75,
            "guidance_high": 34.25, "consensus": 22.8,
            "note": "AI HBM 수요로 차분기 가이던스가 컨센서스를 대폭 상회(데모).",
            "sources": ["https://investors.micron.com/ (보도자료)"],
        },
        {
            "report_date": d(189), "guided_period": "FY26 Q2", "metric": "revenue",
            "unit": "B_USD", "guidance_mid": 18.7, "consensus": 13.7,
            "note": "차분기 매출 가이던스 컨센서스 대비 +36%(데모).",
            "sources": ["https://investors.micron.com/ (보도자료)"],
        },
    ]


def demo_forward_consensus(ticker: str) -> dict:
    """Sample next-quarter consensus snapshot (offline stand-in for yfinance)."""
    now = datetime.now(timezone.utc)
    table = {
        "MU": {"revenue_consensus": 22.8, "eps_consensus": 2.83},
        "NVDA": {"revenue_consensus": 57.0, "eps_consensus": 0.89},
    }
    vals = table.get(ticker.upper(), {"revenue_consensus": None, "eps_consensus": None})
    return {"ticker": ticker.upper(), "captured": now.strftime("%Y-%m-%d"), **vals}


def demo_news() -> dict:
    """Sample global-news digest (already in Korean) for offline/sandbox use.

    Shape matches ``news.get_news()`` output so the frontend renders identically.
    """
    now = datetime.utcnow()

    def ts(hours: float) -> float:
        return (now - timedelta(hours=hours)).timestamp()

    raw = [
        # (source, reliability, hours_ago, categories, en_title, ko_title, ko_summary)
        ("Reuters", 5, 1.5, ["반도체", "AI", "수출규제", "미중갈등"],
         "US weighs tighter curbs on AI chip exports to China",
         "미국, 중국向 AI 반도체 수출 규제 추가 강화 검토",
         "미 상무부가 엔비디아 등 첨단 AI 가속기의 대중국 수출을 더 옥죄는 추가 규제를 검토 중인 것으로 알려졌다."),
        ("Nikkei", 4, 3.0, ["반도체", "데이터센터", "AI"],
         "TSMC raises capex as AI data center orders surge",
         "TSMC, AI 데이터센터 수주 급증에 설비투자 상향",
         "세계 최대 파운드리 TSMC가 AI 서버용 첨단 패키징 수요 폭증에 연간 설비투자 전망을 상향했다."),
        ("Reuters", 5, 5.0, ["데이터센터투자", "AI", "데이터센터"],
         "OpenAI, Oracle expand Stargate data center buildout to new sites",
         "오픈AI·오라클, '스타게이트' 데이터센터 증설 부지 확대",
         "오픈AI와 오라클이 대규모 AI 학습 단지 '스타게이트' 구축을 추가 부지로 확장한다고 밝혔다."),
        ("CNBC", 4, 6.0, ["데이터센터투자", "AI"],
         "AI funding frenzy: startup raises $5bn to build compute clusters",
         "AI 자금조달 열기…한 스타트업, 컴퓨트 클러스터 구축에 50억 달러 유치",
         "대형 AI 스타트업이 GPU 클러스터 확보를 위해 50억 달러 규모 투자를 유치하며 자금조달 경쟁이 가열되고 있다."),
        ("Bloomberg", 5, 7.0, ["전력·인프라", "데이터센터", "에너지"],
         "Data center power demand strains US grid, spurs transformer shortage",
         "데이터센터 전력 수요에 미 전력망 부담…변압기 품귀",
         "AI 데이터센터 급증으로 전력 수요가 치솟으며 변압기·배전 설비 공급난과 전력망 투자 확대 논의가 가속화되고 있다."),
        ("DataCenterDynamics", 3, 8.0, ["데이터센터투자", "데이터센터"],
         "Developer pauses $3bn data center as power hookup slips two years",
         "전력 연결 2년 지연에 30억 달러 데이터센터 착공 보류",
         "전력망 접속이 지연되며 일부 대형 데이터센터 프로젝트가 착공을 미루는 등 투자 지연 사례가 나타나고 있다."),
        ("WSJ", 5, 9.0, ["반도체", "AI인프라", "AI"],
         "Broadcom lifts AI revenue forecast on custom accelerators",
         "브로드컴, 맞춤형 AI 가속기 수요에 AI 매출 전망 상향",
         "브로드컴이 맞춤형 AI 칩(ASIC)과 네트워킹 수요를 근거로 연간 AI 매출 가이던스를 상향했다."),
        ("CNBC", 4, 10.0, ["에너지", "데이터센터", "전력·인프라"],
         "Tech giants sign SMR nuclear deals to power AI data centers",
         "빅테크, AI 데이터센터 전력 위해 SMR 원전 계약 잇따라",
         "전력 확보 경쟁이 치열해지며 빅테크들이 소형모듈원전(SMR)·원자력 전력구매계약을 잇달아 체결하고 있다."),
        # --- AI 인프라 공급망 (무료 매체 위주) ---
        ("The Register", 3, 2.5, ["광통신", "AI인프라", "반도체"],
         "Broadcom, Nvidia push co-packaged optics for next-gen AI networking",
         "브로드컴·엔비디아, 차세대 AI 네트워킹용 CPO(공동패키지 광학) 도입 가속",
         "전력·지연을 줄이려는 CPO 채택이 빨라지며 실리콘 포토닉스·광 트랜시버 공급망이 수혜를 볼 전망이다."),
        ("Yahoo Finance", 3, 4.5, ["AI인프라", "반도체"],
         "SK Hynix, Samsung race to ramp HBM4 for AI accelerators",
         "SK하이닉스·삼성, AI 가속기용 HBM4 양산 경쟁",
         "차세대 GPU에 탑재될 HBM4 양산 시점을 놓고 메모리 3사가 경쟁하며 DRAM 업황 회복을 견인하고 있다."),
        ("DataCenterDynamics", 3, 6.5, ["에너지", "전력·인프라", "데이터센터"],
         "Bloom Energy to supply solid oxide fuel cells for AI data center power",
         "블룸에너지, AI 데이터센터에 SOFC 연료전지 전력 공급",
         "전력망 접속 지연을 피하려는 데이터센터들이 SOFC 연료전지 등 온사이트 발전으로 눈을 돌리고 있다."),
        ("CNBC", 4, 9.5, ["에너지", "전력·인프라", "데이터센터"],
         "GE Vernova orders jump as data centers scramble for gas turbines",
         "GE버노바, 데이터센터 가스터빈 수요 급증에 수주 확대",
         "AI 전력 수요 폭증으로 발전엔진·가스터빈 공급이 빠듯해지며 관련 설비 업체 주문이 크게 늘었다."),
        ("Reuters", 5, 11.0, ["전력·인프라", "데이터센터", "AI인프라"],
         "Nvidia pushes 800VDC power architecture for gigawatt AI data centers",
         "엔비디아, 기가와트급 AI 데이터센터용 800VDC 전력 아키텍처 추진",
         "랙당 전력이 급증하며 엔비디아가 효율을 높인 800VDC 직류 급전 아키텍처를 데이터센터 표준으로 밀고 있다."),
        ("Yahoo Finance", 3, 12.5, ["소버린AI", "데이터센터투자", "AI"],
         "Gulf state unveils sovereign AI plan with national data center fund",
         "걸프 국가, 국가 데이터센터 펀드 앞세운 소버린 AI 계획 발표",
         "각국 정부가 자국 데이터·모델 주권을 위해 소버린 AI 인프라 투자에 나서며 데이터센터 수요를 키우고 있다."),
        ("CNBC", 4, 14.0, ["피지컬AI", "AI", "반도체"],
         "Nvidia, partners bet on humanoid robotics as 'physical AI' wave builds",
         "엔비디아·파트너들, '피지컬 AI' 부상에 휴머노이드 로보틱스 베팅",
         "AI가 로보틱스·자동화로 확장되는 '피지컬 AI' 흐름에 맞춰 칩·플랫폼 업체들이 휴머노이드 시장에 진입하고 있다."),
        ("The Register", 3, 16.0, ["엣지AI", "반도체", "AI"],
         "Qualcomm, chipmakers ramp edge AI silicon for on-device inference",
         "퀄컴 등 칩 업체, 온디바이스 추론용 엣지 AI 반도체 확대",
         "AI PC·스마트폰 등 온디바이스 추론 수요가 커지며 엣지 AI용 저전력 반도체 경쟁이 본격화되고 있다."),
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
