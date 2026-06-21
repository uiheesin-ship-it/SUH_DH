"""Send the AI news digest to a Telegram channel.

Uses only the Python standard library (urllib) so it adds no dependencies.
Credentials come from the environment and must never be committed:

  TELEGRAM_BOT_TOKEN  bot token from @BotFather
  TELEGRAM_CHAT_ID    channel id ("@my_channel" for public, "-100..." for private)

The companion entry point ``notify_telegram.py`` builds the digest, picks the
items that have not been sent yet (tracked in a small JSON state file) and posts
them. See the README "텔레그램 전송" section for setup.
"""

from __future__ import annotations

import html as _html
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.telegram.org"


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


# --------------------------------------------------------------------------- #
# Message formatting
# --------------------------------------------------------------------------- #
def _fmt_time(item: dict) -> str:
    """Prefer KST built from the publish timestamp; fall back to the raw string."""
    ts = item.get("published_ts")
    if ts:
        kst = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=9)
        return kst.strftime("%m/%d %H:%M KST")
    return str(item.get("published") or "")


def format_message(item: dict) -> str:
    """Render one news item as a Telegram HTML message."""
    title = _esc(item.get("title_ko") or item.get("title"))
    lines = [f"🤖 <b>{title}</b>"]

    summary = item.get("summary_ko")
    if summary:
        lines.append(_esc(summary))

    src = _esc(item.get("source"))
    lock = " 🔒유료" if item.get("paywall") else ""
    cats = " · ".join(item.get("categories") or [])
    meta = f"📰 {src}{lock}"
    if cats:
        meta += f"  ·  🏷 {_esc(cats)}"
    lines.append(meta)

    when = _fmt_time(item)
    if when:
        lines.append(f"🕒 {_esc(when)}")

    link = item.get("link")
    if link:
        lines.append(f'🔗 <a href="{_esc(link)}">원문 보기</a>')

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #
def send_message(token: str, chat_id: str, text: str, *, timeout: float = 20) -> dict:
    """Post a single HTML message to a chat/channel via the Bot API."""
    url = f"{API}/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,  # keep the source link preview
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_with_retry(token: str, chat_id: str, text: str, *, retries: int = 3) -> dict:
    """Send, honoring Telegram's 429 ``retry_after`` a few times before giving up."""
    for attempt in range(retries + 1):
        try:
            return send_message(token, chat_id, text)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if e.fp else ""
            if e.code == 429 and attempt < retries:
                try:
                    wait = json.loads(body).get("parameters", {}).get("retry_after", 3)
                except Exception:
                    wait = 3
                time.sleep(min(float(wait), 30))
                continue
            raise RuntimeError(f"Telegram API error {e.code}: {body[:300]}") from e
    raise RuntimeError("Telegram send failed after retries")


# --------------------------------------------------------------------------- #
# Digest source (read the dashboard's pre-built news.json)
# --------------------------------------------------------------------------- #
def fetch_digest(url: str, *, timeout: float = 20) -> dict:
    """Load the dashboard's pre-built news digest (its ``news.json``).

    Reading the same JSON the dashboard publishes guarantees the Telegram
    channel shows exactly the items on the dashboard, instead of a separate
    live fetch that drifts apart over time.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "SUH-DH-Telegram/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# De-dup state (which items were already sent)
# --------------------------------------------------------------------------- #
def item_id(item: dict) -> str:
    """Stable identity for an item (its link, else its title)."""
    return (item.get("link") or item.get("title") or "").strip()


def new_items(items: list[dict], sent_ids: set[str]) -> list[dict]:
    """Items not seen before, in the order given (digest is newest-first)."""
    out = []
    for it in items:
        iid = item_id(it)
        if iid and iid not in sent_ids:
            out.append(it)
    return out


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"sent": [], "updated": None}


def save_state(path: str, sent_ids: list[str], *, keep: int = 500) -> None:
    """Persist the most recent ``keep`` sent ids so the file stays bounded."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    data = {
        "sent": sent_ids[-keep:],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)
