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

# (source, reliability, feed URL). Reliability breaks ties when the same story
# shows up in several outlets — the most authoritative source wins.
FEEDS: list[tuple[str, int, str]] = [
    ("Reuters", 5, "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
    ("Reuters", 5, "https://www.reutersagency.com/feed/?best-topics=tech&post_type=best"),
    ("Bloomberg", 5, "https://feeds.bloomberg.com/markets/news.rss"),
    ("Bloomberg", 5, "https://feeds.bloomberg.com/economics/news.rss"),
    ("Bloomberg", 5, "https://feeds.bloomberg.com/technology/news.rss"),
    ("FT", 5, "https://www.ft.com/rss/home"),
    ("WSJ", 5, "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("WSJ", 5, "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    ("WSJ", 5, "https://feeds.a.dj.com/rss/RSSWSJD.xml"),
    ("CNBC", 4, "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC", 4, "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC", 4, "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("Nikkei", 4, "https://asia.nikkei.com/rss/feed/nar"),
]

# Korean category label -> (weight, keyword list). A higher weight means the
# topic is more decision-relevant for an investor. Keywords are matched
# case-insensitively on whole words, so short tokens like "ai"/"fed" are safe.
CATEGORIES: dict[str, tuple[int, list[str]]] = {
    "AI": (3, ["artificial intelligence", "ai", "openai", "chatgpt", "generative ai",
               "anthropic", "llm", "copilot", "ai chip"]),
    "반도체": (3, ["semiconductor", "semiconductors", "chip", "chips", "chipmaker",
                "tsmc", "foundry", "asml", "wafer", "nvidia", "micron", "samsung electronics",
                "sk hynix", "memory chip", "hbm"]),
    "데이터센터": (3, ["data center", "data centre", "data centers", "hyperscaler",
                  "cloud capacity", "server demand"]),
    "전력·인프라": (2, ["power grid", "electricity", "nuclear power", "utility", "utilities",
                   "power demand", "transmission line", "smr", "power plant"]),
    "에너지": (2, ["oil", "crude", "opec", "natural gas", "lng", "energy", "barrel", "refinery"]),
    "미중갈등": (3, ["china", "beijing", "u.s.-china", "us-china", "taiwan", "xi jinping"]),
    "관세": (3, ["tariff", "tariffs", "trade war", "trade deal", "import duties", "levy", "levies"]),
    "수출규제": (3, ["export control", "export controls", "export curb", "export curbs",
                 "sanction", "sanctions", "chip ban", "blacklist", "entity list"]),
    "미국금리": (3, ["federal reserve", "the fed", "fomc", "interest rate", "interest rates",
                 "rate cut", "rate hike", "powell", "treasury yield", "treasury yields",
                 "inflation", "cpi", "pce", "jobs report"]),
    "환율": (2, ["dollar", "yen", "currency", "forex", "exchange rate", "yuan", "euro", "won"]),
    "원자재": (2, ["gold", "copper", "commodity", "commodities", "metals", "iron ore",
                "silver", "lithium", "rare earth"]),
    "실적·가이던스": (3, ["earnings", "guidance", "profit", "revenue", "quarterly results",
                    "forecast", "outlook", "beats estimates", "misses estimates", "results"]),
    "증시": (1, ["stocks", "stock market", "s&p 500", "nasdaq", "dow", "equities",
               "shares", "wall street", "ipo", "bond market"]),
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


def _parse_feed(source: str, reliability: int, url: str) -> list[dict]:
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
                "published_ts": _to_ts(e),
            }
        )
    return items


def _fetch_live() -> list[dict]:
    items: list[dict] = []
    for source, reliability, url in FEEDS:
        try:
            items.extend(_parse_feed(source, reliability, url))
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
    """Filter to investment-relevant, de-duplicated, recent items (ranked)."""
    now_ts = now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - MAX_AGE_HOURS * 3600

    scored: list[dict] = []
    for it in items:
        score, labels = score_item(it)
        if score < MIN_SCORE:
            continue
        ts = it.get("published_ts")
        if ts is not None and ts < cutoff:
            continue
        enriched = dict(it)
        enriched["score"] = score
        enriched["categories"] = labels
        enriched["_tokens"] = _tokens(it.get("title", ""))
        scored.append(enriched)

    # Most authoritative & relevant first, so de-dup keeps the best version.
    scored.sort(
        key=lambda x: (x["reliability"], x["score"], x.get("published_ts") or 0),
        reverse=True,
    )
    kept: list[dict] = []
    for it in scored:
        if _is_duplicate(it, kept):
            continue
        kept.append(it)

    # Pick the top N by relevance, then present newest-first.
    kept.sort(key=lambda x: (x["score"], x.get("published_ts") or 0), reverse=True)
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
