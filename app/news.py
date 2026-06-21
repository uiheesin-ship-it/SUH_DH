"""Curated global financial news digest for investors.

Pulls headlines from major outlets' RSS feeds (Reuters, Bloomberg, FT, WSJ,
CNBC, Nikkei), scores each item for investment relevance, drops near-duplicate
stories across outlets (keeping the most reliable source), and returns a short,
Korean-summarized digest.

The goal is *selection + brevity*, not analysis: 10~20 items a day, each with a
one/two-line Korean summary, the source, the report time, and the original link.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from . import cache, demo_data

# News is read like a morning brief; refresh every ~30 min is plenty and keeps
# us well under the outlets' rate limits.
NEWS_TTL = float(os.environ.get("SUH_DH_NEWS_TTL", "1800"))
# Target a daily digest of 10~20 items.
MAX_ITEMS = int(os.environ.get("SUH_DH_NEWS_MAX", "18"))
# Ignore anything older than this so the brief stays "today-ish".
MAX_AGE_HOURS = float(os.environ.get("SUH_DH_NEWS_MAX_AGE", "36"))
# A pure-"stocks rise" headline (weight 1) is too generic; require a real,
# investment-relevant topic to make the cut.
MIN_SCORE = int(os.environ.get("SUH_DH_NEWS_MIN_SCORE", "2"))

_AGENT = "Mozilla/5.0 (compatible; SUH-DH-NewsBot/1.0; +https://github.com/uiheesin-ship-it/SUH_DH)"

# (source, reliability, paywall, feed URL). Reliability breaks ties when the
# same story shows up in several outlets. `paywall` flags outlets whose article
# pages mostly sit behind a subscription — we keep them for coverage but prefer
# free-to-read sources (see select()). Free sources are listed first.
FEEDS: list[tuple[str, int, bool, str]] = [
    # --- free to read ---
    ("Reuters", 5, False, "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
    ("Reuters", 5, False, "https://www.reutersagency.com/feed/?best-topics=tech&post_type=best"),
    ("CNBC", 4, False, "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC", 4, False, "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC", 4, False, "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("Yahoo Finance", 3, False, "https://finance.yahoo.com/news/rssindex"),
    # AI-infrastructure supply-chain specialists (free): data centers, power,
    # cooling, optics, chips — exactly the deep supply chain to track.
    ("DataCenterDynamics", 3, False, "https://www.datacenterdynamics.com/rss/"),
    ("The Register", 3, False, "https://www.theregister.com/data_centre/headlines.atom"),
    # --- paywalled (kept for coverage, de-prioritized vs. free) ---
    ("Nikkei", 4, True, "https://asia.nikkei.com/rss/feed/nar"),
    ("Bloomberg", 5, True, "https://feeds.bloomberg.com/markets/news.rss"),
    ("Bloomberg", 5, True, "https://feeds.bloomberg.com/economics/news.rss"),
    ("Bloomberg", 5, True, "https://feeds.bloomberg.com/technology/news.rss"),
    ("FT", 5, True, "https://www.ft.com/rss/home"),
    ("WSJ", 5, True, "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("WSJ", 5, True, "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    ("WSJ", 5, True, "https://feeds.a.dj.com/rss/RSSWSJD.xml"),
]

# A free article, all else equal, is nudged above an equally-relevant paywalled
# one in the daily cut (and always wins on de-duplication).
FREE_BONUS = int(os.environ.get("SUH_DH_NEWS_FREE_BONUS", "1"))

# Korean category label -> (weight, keyword list). This feed is AI-investment
# focused: it ONLY surfaces news about the AI / data-center ecosystem. Most
# categories below are "AI-qualifying" (listed in AI_QUALIFYING) — an article
# must match at least one of them to be included. A few macro categories at the
# bottom (수출규제·미중갈등·관세) are *context only*: they add a tag/score when an
# AI story also touches them, but never let a non-AI story in on their own.
# Keywords are matched case-insensitively on whole words.
CATEGORIES: dict[str, tuple[int, list[str]]] = {
    "AI": (3, ["artificial intelligence", "ai", "a.i.", "generative ai", "ai model",
               "ai models", "foundation model", "frontier model", "large language model",
               "llm", "openai", "anthropic", "chatgpt", "gemini", "copilot", "ai agent",
               "ai inference", "ai training", "ai cluster", "ai supercomputer", "ai boom",
               "ai race", "ai demand", "ai workload", "ai bubble", "ai spending"]),
    "반도체": (3, ["semiconductor", "semiconductors", "chip", "chips", "chipmaker", "ai chip",
                "gpu", "graphics card", "accelerator", "asic", "tsmc", "nvidia", "amd",
                "broadcom", "arm holdings", "asml", "wafer", "foundry", "micron",
                "sk hynix", "samsung electronics", "applied materials", "marvell"]),
    # AI build-out supply chain: compute, memory, advanced packaging, cooling.
    "AI인프라": (3, ["blackwell", "hopper", "h100", "h200", "b200", "gb200", "gb300",
                  "mi300", "mi350", "instinct", "tpu", "trainium",
                  "dram", "hbm", "hbm3", "hbm4", "ddr5", "nand", "high bandwidth memory",
                  "cowos", "advanced packaging", "interposer", "abf substrate", "chiplet",
                  "liquid cooling", "immersion cooling", "ai server", "server rack",
                  "rack-scale", "superchip"]),
    "데이터센터": (3, ["data center", "data centre", "data centers", "datacenter",
                  "hyperscaler", "colocation", "server farm", "cloud capacity",
                  "compute capacity", "ai data center", "global data center",
                  "gigawatt data center", "stargate"]),
    "데이터센터투자": (3, ["data center investment", "data center spending", "data center capex",
                    "data center buildout", "data center construction", "ai capex",
                    "ai investment", "ai funding", "ai startup", "compute spending",
                    "capital expenditure", "data center delay", "data center delays",
                    "data center glut", "data center oversupply", "paused data center",
                    "scaled back", "circular financing", "ai infrastructure deal"]),
    "전력·인프라": (3, ["power grid", "electricity grid", "substation", "transformer",
                   "switchgear", "transmission line", "power demand", "power capacity",
                   "power shortage", "grid connection", "data center power", "backup power",
                   "800v", "800vdc", "hvdc", "dc power", "power shelf", "busbar"]),
    "에너지": (3, ["solar", "photovoltaic", "renewable energy", "wind power", "battery storage",
                "energy storage", "grid storage", "smr", "small modular reactor",
                "nuclear power", "nuclear reactor", "nuclear plant", "geothermal", "sofc",
                "solid oxide", "fuel cell", "gas turbine", "ge vernova", "bloom energy"]),
    "광통신": (3, ["silicon photonics", "co-packaged optics", "cpo", "optical transceiver",
                "optical interconnect", "optical networking", "800g", "1.6t", "dwdm",
                "fiber optic", "photonics", "nvlink", "infiniband"]),
    "소버린AI": (3, ["sovereign ai", "national ai", "state-backed ai", "government ai compute"]),
    "엣지AI": (3, ["edge ai", "on-device ai", "edge computing", "edge inference",
                 "ai pc", "ai smartphone", "ai laptop"]),
    "피지컬AI": (3, ["physical ai", "embodied ai", "humanoid", "robotics", "robot", "robots",
                  "autonomous", "self-driving", "robotaxi", "factory automation",
                  "industrial automation"]),
    # --- context tags only (do NOT qualify a story by themselves) ---
    "수출규제": (2, ["export control", "export controls", "export curb", "export curbs",
                 "chip ban", "entity list", "sanction", "sanctions"]),
    "미중갈등": (1, ["china", "beijing", "u.s.-china", "us-china", "taiwan"]),
    "관세": (1, ["tariff", "tariffs"]),
}

# Categories that make an article count as AI-investment news. A story must hit
# at least one of these to be included; the rest are context only.
AI_QUALIFYING: set[str] = {
    "AI", "반도체", "AI인프라", "데이터센터", "데이터센터투자",
    "전력·인프라", "에너지", "광통신", "소버린AI", "엣지AI", "피지컬AI",
}

# Pre-compile one regex per keyword (whole-word, case-insensitive).
_KEYWORD_RES: dict[str, list[tuple[str, re.Pattern]]] = {
    label: [(kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)) for kw in kws]
    for label, (_, kws) in CATEGORIES.items()
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "as",
    "at", "by", "from", "amid", "after", "over", "into", "its", "is", "are",
    "be", "new", "says", "said", "could", "will", "may", "more", "than", "that",
    "this", "you", "your", "how", "why", "what", "us", "u.s.",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _to_ts(entry) -> float | None:
    """Best-effort epoch seconds (UTC) from a feedparser entry."""
    import calendar

    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    try:
        return float(calendar.timegm(st))
    except Exception:
        return None


def _parse_feed(source: str, reliability: int, paywall: bool, url: str) -> list[dict]:
    import feedparser

    parsed = feedparser.parse(url, agent=_AGENT)
    items: list[dict] = []
    for e in parsed.entries:
        title = _strip_html(e.get("title"))
        link = e.get("link")
        if not title or not link:
            continue
        summary = _strip_html(e.get("summary") or e.get("description") or "")
        items.append(
            {
                "title": title,
                "summary": summary,
                "link": link,
                "source": source,
                "reliability": reliability,
                "paywall": paywall,
                "published_ts": _to_ts(e),
            }
        )
    return items


def _fetch_live() -> list[dict]:
    items: list[dict] = []
    for source, reliability, paywall, url in FEEDS:
        try:
            items.extend(_parse_feed(source, reliability, paywall, url))
        except Exception:
            # A single dead/blocked feed must not break the whole digest.
            continue
    return items


# --------------------------------------------------------------------------- #
# Selection (score -> filter -> dedupe -> rank)
# --------------------------------------------------------------------------- #
def score_item(item: dict) -> tuple[int, list[str]]:
    """Return (relevance score, matched Korean category labels) for an item."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    score = 0
    labels: list[str] = []
    for label, (weight, _kws) in CATEGORIES.items():
        if any(rx.search(text) for _kw, rx in _KEYWORD_RES[label]):
            score += weight
            labels.append(label)
    return score, labels


def is_ai_relevant(item: dict) -> bool:
    """True if the item is about the AI / data-center ecosystem (the feed's scope)."""
    _score, labels = score_item(item)
    return bool(set(labels) & AI_QUALIFYING)


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _is_duplicate(item: dict, kept: list[dict]) -> bool:
    """Near-duplicate if titles share most significant words (same story)."""
    toks = item["_tokens"]
    if not toks:
        return False
    for k in kept:
        ktoks = k["_tokens"]
        if not ktoks:
            continue
        inter = len(toks & ktoks)
        union = len(toks | ktoks)
        if union and inter / union >= 0.5:
            return True
        # One headline fully contained in the other (e.g. wire vs. recap).
        if inter >= 3 and (inter == len(toks) or inter == len(ktoks)):
            return True
    return False


def select(items: list[dict], max_items: int = MAX_ITEMS, now_ts: float | None = None) -> list[dict]:
    """Filter to AI/data-center news, de-duplicated, recent (ranked)."""
    now_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - MAX_AGE_HOURS * 3600

    scored: list[dict] = []
    for it in items:
        score, labels = score_item(it)
        # AI-investment scope: must touch the AI/data-center ecosystem, not just
        # a generic macro topic, and clear the minimum relevance score.
        if score < MIN_SCORE or not (set(labels) & AI_QUALIFYING):
            continue
        ts = it.get("published_ts")
        if ts is not None and ts < cutoff:
            continue
        enriched = dict(it)
        enriched["score"] = score
        enriched["categories"] = labels
        enriched.setdefault("paywall", False)
        enriched["_tokens"] = _tokens(it.get("title", ""))
        scored.append(enriched)

    # De-dup keeps the *first* version of a story, so order by what we'd rather
    # keep: free over paywalled, then most authoritative, relevant, recent.
    def _free(x: dict) -> int:
        return 0 if x.get("paywall") else 1

    scored.sort(
        key=lambda x: (_free(x), x["reliability"], x["score"], x.get("published_ts") or 0),
        reverse=True,
    )
    kept: list[dict] = []
    for it in scored:
        if _is_duplicate(it, kept):
            continue
        kept.append(it)

    # Pick the top N by relevance — a free article gets a small bonus so it
    # outranks an equally-relevant paywalled one — then present newest-first.
    kept.sort(
        key=lambda x: (x["score"] + (FREE_BONUS if not x.get("paywall") else 0),
                       x.get("published_ts") or 0),
        reverse=True,
    )
    chosen = kept[:max_items]
    chosen.sort(key=lambda x: x.get("published_ts") or 0, reverse=True)
    for it in chosen:
        it.pop("_tokens", None)
    return chosen


# --------------------------------------------------------------------------- #
# Korean summary + assembly
# --------------------------------------------------------------------------- #
def _fmt_published(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _localize(items: list[dict]) -> list[dict]:
    """Translate the headline (and a short summary) to Korean, best-effort."""
    from . import translate

    out: list[dict] = []
    for it in items:
        out.append(
            {
                "title": it["title"],
                "title_ko": translate.to_korean(it["title"]),
                "summary_ko": translate.summary_korean(it.get("summary")) or "",
                "source": it["source"],
                "reliability": it["reliability"],
                "paywall": bool(it.get("paywall")),
                "categories": it["categories"],
                "link": it["link"],
                "published": _fmt_published(it.get("published_ts")),
                "published_ts": it.get("published_ts"),
            }
        )
    return out


def _build_live() -> dict:
    selected = select(_fetch_live())
    items = _localize(selected)
    return {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(items),
        "items": items,
        "demo": False,
    }


def get_news() -> dict:
    def producer():
        return demo_data.demo_news() if _demo() else _build_live()

    return cache.get_or_set("news_digest", NEWS_TTL, producer)
