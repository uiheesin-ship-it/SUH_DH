"""Offline tests for the pure logic (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.indicators import attach_moving_averages, moving_average
from app.screener import _normalize_change, group_by_sector
from app import demo_data, news


def test_moving_average_padding_and_value():
    vals = [1, 2, 3, 4, 5]
    ma3 = moving_average(vals, 3)
    assert ma3[0] is None and ma3[1] is None
    assert ma3[2] == 2.0  # (1+2+3)/3
    assert ma3[4] == 4.0  # (3+4+5)/3


def test_attach_moving_averages_keys():
    chart = {"close": list(range(200))}
    out = attach_moving_averages(chart)
    for w in (5, 20, 50, 120):
        assert f"ma{w}" in out
        assert len(out[f"ma{w}"]) == 200
    assert out["ma120"][118] is None
    assert out["ma120"][119] is not None


def test_normalize_change_fraction_and_percent():
    assert _normalize_change(0.0523) == 5.23   # finviz fraction -> percent
    assert _normalize_change(-0.011) == -1.1
    assert _normalize_change(None) is None


def test_group_by_sector_sorted_by_market_cap():
    rows = demo_data.demo_new_highs()
    sectors = group_by_sector(rows)
    # sectors sorted by total market cap desc
    caps = [s["market_cap"] for s in sectors]
    assert caps == sorted(caps, reverse=True)
    # within an industry, stocks sorted by market cap desc
    tech = next(s for s in sectors if s["sector"] == "Technology")
    semis = next(i for i in tech["industries"] if i["industry"] == "Semiconductors")
    mcaps = [s["market_cap"] for s in semis["stocks"]]
    assert mcaps == sorted(mcaps, reverse=True)
    # counts add up
    assert tech["count"] == sum(i["count"] for i in tech["industries"]) + len(tech["stocks"])


def test_demo_chart_has_consistent_lengths():
    d = demo_data.demo_chart("NVDA", "6mo")
    n = len(d["dates"])
    for k in ("open", "high", "low", "close", "volume"):
        assert len(d[k]) == n
    assert n > 100


# ---------- global news digest ----------
def test_score_item_picks_relevant_categories():
    score, cats = news.score_item(
        {"title": "US weighs tighter export controls on AI chips to China", "summary": ""}
    )
    assert score >= news.MIN_SCORE
    # Hits export-control, AI, semiconductor and China topics.
    assert {"수출규제", "AI", "반도체", "미중갈등"} <= set(cats)


def test_score_item_ignores_generic_non_investment_news():
    score, cats = news.score_item(
        {"title": "Local council debates new park bench design", "summary": "A community meeting."}
    )
    assert score == 0 and cats == []


def test_ai_scope_covers_full_supply_chain_and_themes():
    # Every facet of the AI / data-center ecosystem the feed targets should be
    # recognized as in-scope (AI-relevant) and clear the minimum score.
    for title in [
        "Broadcom ramps co-packaged optics (CPO) for AI networking",
        "SK Hynix accelerates HBM4 and DDR5 DRAM output",
        "Bloom Energy supplies solid oxide fuel cells (SOFC) to data centers",
        "GE Vernova gas turbine orders surge on data center power demand",
        "TSMC expands CoWoS advanced packaging capacity",
        "Nvidia pushes 800VDC power architecture for AI data centers",
        "Solar and SMR deals signed to power hyperscale data centers",
        "Grid transformer shortage threatens data center buildout",
        "Gulf state launches sovereign AI compute program",
        "Qualcomm ramps edge AI chips for on-device inference",
        "Nvidia bets on humanoid robotics and physical AI",
        "AI startup raises billions in funding for compute clusters",
        "Developer pauses data center as power hookup is delayed",
    ]:
        score, cats = news.score_item({"title": title, "summary": ""})
        assert news.is_ai_relevant({"title": title, "summary": ""}), title
        assert score >= news.MIN_SCORE, title


def test_non_ai_macro_news_is_excluded():
    import time

    now = time.time()
    macro = [
        "Fed holds interest rates steady, signals one cut this year",
        "Yen tumbles to a multi-decade low against the dollar",
        "OPEC extends oil output cuts to support crude prices",
        "Gold rallies to an all-time high as investors seek safe havens",
        "Boeing wins major jet order, lifts delivery outlook",
        "US imposes fresh tariffs on imported steel",
    ]
    items = [{"title": t, "summary": "", "source": "Reuters", "reliability": 5,
              "paywall": False, "published_ts": now} for t in macro]
    # None of these touch the AI/data-center ecosystem -> all filtered out.
    assert news.select(items, now_ts=now) == []


def test_dedupe_prefers_free_over_paywalled():
    import time

    now = time.time()
    items = [
        # Same story; paywalled WSJ is more "reliable" but free CNBC should win.
        {"title": "Nvidia unveils new Blackwell AI accelerator for data centers",
         "summary": "", "source": "WSJ", "reliability": 5, "paywall": True,
         "published_ts": now},
        {"title": "Nvidia unveils new Blackwell AI accelerator for data centers",
         "summary": "", "source": "CNBC", "reliability": 4, "paywall": False,
         "published_ts": now},
    ]
    out = news.select(items, max_items=5, now_ts=now)
    assert len(out) == 1
    assert out[0]["source"] == "CNBC" and out[0]["paywall"] is False


def test_select_filters_dedupes_and_caps():
    import time

    now = time.time()
    fresh = now
    items = [
        # Same story from two outlets -> the more reliable (Reuters) should win.
        {"title": "TSMC raises capex on surging AI data center chip demand",
         "summary": "", "source": "Reuters", "reliability": 5, "paywall": False,
         "published_ts": fresh},
        {"title": "TSMC raises capex on surging AI data center chip demand",
         "summary": "", "source": "CNBC", "reliability": 4, "paywall": False,
         "published_ts": fresh},
        # Distinct in-scope story.
        {"title": "Nvidia unveils Blackwell AI accelerator for data centers",
         "summary": "", "source": "Nikkei", "reliability": 4, "paywall": True,
         "published_ts": fresh},
        # In scope but too old -> dropped.
        {"title": "Micron ramps HBM4 memory for AI accelerators",
         "summary": "", "source": "Bloomberg", "reliability": 5, "paywall": True,
         "published_ts": now - (news.MAX_AGE_HOURS + 5) * 3600},
        # Out of scope (macro) -> dropped.
        {"title": "Fed holds interest rates steady this year",
         "summary": "", "source": "CNBC", "reliability": 4, "paywall": False,
         "published_ts": fresh},
    ]
    out = news.select(items, max_items=5, now_ts=now)
    titles = [o["title"] for o in out]
    assert len(out) == 2  # one TSMC (deduped) + Nvidia; old & out-of-scope dropped
    tsmc = next(o for o in out if "TSMC" in o["title"])
    assert tsmc["source"] == "Reuters"  # most reliable free source kept on dedupe
    assert all("Fed" not in t for t in titles)  # macro filtered out
    assert all("_tokens" not in o for o in out)  # internal field cleaned up


def test_select_respects_max_items():
    import time

    now = time.time()
    # Distinct, in-scope AI / data-center stories.
    headlines = [
        "Nvidia unveils next-generation AI accelerator at developer conference",
        "TSMC ramps CoWoS advanced packaging to meet data center demand",
        "Broadcom raises revenue forecast on custom AI silicon",
        "SK Hynix ships HBM4 memory for next-gen AI accelerators",
        "Microsoft commits billions to new data center power deals",
        "ASML lands orders for next-generation EUV lithography machines",
        "Bloom Energy supplies SOFC fuel cells to AI data centers",
        "GE Vernova gas turbine backlog swells on data center demand",
        "OpenAI expands Stargate data center buildout to new sites",
        "Qualcomm ramps edge AI chips for on-device inference",
        "Nvidia bets on humanoid robotics in physical AI push",
        "Sovereign AI fund launches national data center program",
        "Co-packaged optics adoption accelerates for AI networking",
        "Grid transformer shortage threatens data center construction",
        "SMR nuclear deal signed to power hyperscale data centers",
        "AI startup raises $4bn in funding for compute clusters",
        "Marvell guides higher on AI networking silicon demand",
        "Solar and battery storage tapped to power AI data centers",
        "Arm Holdings expands data center CPU roadmap for AI",
        "Amazon plans gigawatt data center campus for AI training",
    ]
    items = [
        {"title": h, "summary": "", "source": "Reuters", "reliability": 5,
         "paywall": False, "published_ts": now - i * 60}
        for i, h in enumerate(headlines)
    ]
    out = news.select(items, max_items=18, now_ts=now)
    assert len(out) == 18


def test_demo_news_shape_and_count():
    d = demo_data.demo_news()
    assert d["demo"] is True
    assert 10 <= d["count"] <= 20
    assert d["count"] == len(d["items"])
    for it in d["items"]:
        assert it["title_ko"] and it["link"] and it["source"]
        assert it["categories"]
        assert isinstance(it["paywall"], bool)
        # Every demo headline is within the AI / data-center scope of the feed.
        assert news.is_ai_relevant({"title": it["title"], "summary": ""}), it["title"]
    # The digest should span the AI ecosystem (supply chain + themes).
    seen = set().union(*(it["categories"] for it in d["items"]))
    assert {"AI인프라", "데이터센터투자", "에너지"} <= seen
