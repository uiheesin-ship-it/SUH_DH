"""Offline tests for the pure logic (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.indicators import attach_moving_averages, moving_average
from app.screener import _normalize_change, group_by_sector
from app import demo_data, earnings, news, telegram


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


# ---------- earnings: consensus beat/miss ----------
def test_surprise_pct_basic_and_undefined():
    assert earnings.surprise_pct(2.0, 2.2) == 10.0     # 10% beat
    assert earnings.surprise_pct(2.0, 1.8) == -10.0    # 10% miss
    assert earnings.surprise_pct(None, 2.0) is None    # no consensus
    assert earnings.surprise_pct(2.0, None) is None    # not reported
    assert earnings.surprise_pct(0.0, 2.0) is None     # undefined (est == 0)
    assert earnings.surprise_pct(float("nan"), 2.0) is None  # NaN guarded


def test_classify_beat_miss_inline_unknown():
    assert earnings.classify(2.0, 2.5) == "beat"
    assert earnings.classify(2.0, 1.5) == "miss"
    assert earnings.classify(2.0, 2.005) == "inline"   # within the band
    assert earnings.classify(2.0, None) == "unknown"   # not reported yet
    assert earnings.classify(None, 2.0) == "unknown"   # reported, no consensus


def test_demo_earnings_shape_and_tags():
    rows = demo_data.demo_earnings("MU")
    assert rows  # MU has sample quarters
    # Newest first.
    assert [r["datetime"] for r in rows] == sorted(
        (r["datetime"] for r in rows), reverse=True
    )
    for r in rows:
        assert r["result"] in {"beat", "miss", "inline", "unknown"}
        assert r["result_ko"] == earnings.RESULT_LABELS_KO[r["result"]]
        # An upcoming (not-yet-reported) quarter has no actual EPS.
        if r["upcoming"]:
            assert r["reported_eps"] is None and r["result"] == "unknown"
        # A reported beat must actually have reported EPS above estimate.
        if r["reported"] and r["result"] == "beat":
            assert r["reported_eps"] > r["eps_estimate"]


# ---------- earnings: guidance vs consensus ----------
def test_classify_guidance_bands():
    assert earnings.classify_guidance(118, 80)[1] == "대폭상회"   # +47.5%
    assert earnings.classify_guidance(8.8, 8.2)[1] == "상회"       # +7.3%
    assert earnings.classify_guidance(8.8, 8.6)[1] == "소폭상회"   # +2.3%
    assert earnings.classify_guidance(8.5, 8.5)[1] == "부합"        # 0%
    assert earnings.classify_guidance(8.3, 8.5)[1] == "소폭하회"   # -2.4%
    assert earnings.classify_guidance(7.9, 9.0)[1] == "하회"        # -12.2%
    assert earnings.classify_guidance(5.0, 9.0)[1] == "대폭하회"   # -44%
    # Missing / undefined inputs grade to nothing.
    assert earnings.classify_guidance(None, 8.5) == (None, None)
    assert earnings.classify_guidance(8.8, None) == (None, None)
    assert earnings.classify_guidance(8.8, 0) == (None, None)


def test_forward_consensus_demo_shape():
    os.environ["SUH_DH_DEMO"] = "1"
    snap = earnings.forward_consensus("MU")
    assert snap["ticker"] == "MU"
    assert "revenue_consensus" in snap and "eps_consensus" in snap
    assert snap["captured"]


def test_estimate_next_q_reads_plus1q_avg():
    class _Row(dict):
        pass

    class _DF:
        index = ["0q", "+1q", "0y", "+1y"]

        def __init__(self, avg):
            self._avg = avg

        @property
        def loc(self):
            return {"+1q": {"avg": self._avg}}

    assert earnings._estimate_next_q(_DF(8.5)) == 8.5
    assert earnings._estimate_next_q(None) is None


def test_guidance_merges_onto_matching_quarter():
    os.environ["SUH_DH_DEMO"] = "1"
    from app import cache as _cache

    _cache.clear()
    try:
        data = earnings.get_earnings("MU")
    finally:
        _cache.clear()
    assert data["guidance_count"] >= 1
    # The quarter carrying guidance has a graded, sourced annotation.
    guided = [q for q in data["quarters"] if q["guidance"]]
    assert guided
    g = guided[0]["guidance"][0]
    assert g["guidance_result_ko"] in {
        "대폭상회", "상회", "소폭상회", "부합", "소폭하회", "하회", "대폭하회"
    }
    assert g["guidance_surprise_pct"] is not None
    assert g["sources"]


# ---------- earnings: post-earnings price drift ----------
def test_drift_returns_anchors_on_report_day():
    # 10 trading days; report on day 5 (close 110), prior day close 100.
    dates = [f"2025-01-{d:02d}" for d in range(1, 11)]
    closes = [90, 95, 100, 105, 100, 110, 121, 130, 140, 150]
    #          0   1    2    3    4    5    6    7    8    9
    # report_date 2025-01-06 -> idx 5 (close 110), D-1 = 100.
    d = earnings.drift_returns(dates, closes, "2025-01-06", offsets=(1, 3), pre_offsets=(5,))
    assert d["d0_close"] == 110 and d["d_minus1_close"] == 100
    assert d["prev1_pct"] == 10.0          # 100 -> 110
    assert d["returns"]["d1"] == 10.0      # 110 -> 121
    assert d["pre_returns"]["d-5"] == 11.1  # D-5 close[0]=90 -> D-1 close[4]=100 = +11.1%
    assert d["returns"]["d3"] == round((140 - 110) / 110 * 100, 1)  # 110 -> 140
    # Offsets past the end of the series come back as None, not an error.
    assert earnings.drift_returns(dates, closes, "2025-01-10", offsets=(5,))["returns"]["d5"] is None
    # No prior trading day to anchor on -> None.
    assert earnings.drift_returns(dates, closes, "2024-12-01") is None


def test_drift_summary_averages_and_up_count():
    drifts = [
        {"returns": {"d1": 10.0, "d7": -5.0}},
        {"returns": {"d1": -2.0, "d7": None}},
        {"returns": {"d1": 4.0, "d7": 15.0}},
    ]
    s = earnings._drift_summary(drifts, offsets=(1, 7))
    assert s["d1"] == {"avg": 4.0, "up": 2, "n": 3}     # (10-2+4)/3
    assert s["d7"] == {"avg": 5.0, "up": 1, "n": 2}     # (-5+15)/2, None skipped


def test_get_drift_demo_end_to_end():
    os.environ["SUH_DH_DEMO"] = "1"
    from app import cache as _cache

    _cache.clear()
    try:
        d = earnings.get_drift("MU")
    finally:
        _cache.clear()
    assert d["offsets"] == [1, 7, 30, 60]
    reported = [q for q in d["quarters"] if q["reported"]]
    assert reported and any(q["drift"] for q in reported)
    # Upcoming quarter has no drift.
    upcoming = [q for q in d["quarters"] if q["upcoming"]]
    assert upcoming and all(q["drift"] is None for q in upcoming)
    assert set(d["summary"]) == {"d1", "d7", "d30", "d60"}


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


# ---------- telegram delivery ----------
def test_telegram_format_message_has_key_fields_and_escapes():
    item = {
        "title": "Nvidia & AMD <ship> chips",
        "title_ko": "엔비디아 & AMD <신제품> 출시",
        "summary_ko": "AI 가속기 경쟁 심화.",
        "source": "Reuters",
        "paywall": False,
        "categories": ["반도체", "AI"],
        "link": "https://example.com/a?b=1&c=2",
        "published": "2026-06-21 02:00 UTC",
        "published_ts": 1_781_000_000,
    }
    msg = telegram.format_message(item)
    assert "엔비디아 &amp; AMD &lt;신제품&gt; 출시" in msg  # HTML-escaped
    assert "AI 가속기 경쟁 심화." in msg
    assert "Reuters" in msg and "반도체 · AI" in msg
    assert 'href="https://example.com/a?b=1&amp;c=2"' in msg
    assert "KST" in msg  # localized from published_ts


def test_telegram_format_message_marks_paywall():
    item = {"title_ko": "유료 기사", "source": "WSJ", "paywall": True, "link": "https://x.y"}
    assert "🔒유료" in telegram.format_message(item)


def test_telegram_new_items_filters_already_sent():
    items = [
        {"title": "A", "link": "https://x/1"},
        {"title": "B", "link": "https://x/2"},
        {"title": "C", "link": "https://x/3"},
    ]
    sent = {"https://x/2"}
    fresh = telegram.new_items(items, sent)
    assert [telegram.item_id(i) for i in fresh] == ["https://x/1", "https://x/3"]


def test_telegram_state_roundtrip_and_bound(tmp_path):
    path = str(tmp_path / "state" / "sent.json")
    ids = [f"https://x/{i}" for i in range(600)]
    telegram.save_state(path, ids, keep=500)
    state = telegram.load_state(path)
    assert len(state["sent"]) == 500  # bounded
    assert state["sent"][-1] == "https://x/599"  # keeps the most recent
    assert telegram.load_state(str(tmp_path / "missing.json")) == {"sent": [], "updated": None}


def test_telegram_fetch_digest_reads_dashboard_json(tmp_path):
    # Mirror the dashboard by reading its published news.json verbatim.
    path = tmp_path / "news.json"
    path.write_text(
        '{"count": 1, "items": [{"title": "x", "link": "https://x/1"}]}',
        encoding="utf-8",
    )
    digest = telegram.fetch_digest(path.as_uri())
    assert digest["count"] == 1
    assert digest["items"][0]["link"] == "https://x/1"
