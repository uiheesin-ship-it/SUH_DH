#!/usr/bin/env python3
"""Push newly-selected AI news items to a Telegram channel.

Run on a schedule (see .github/workflows/telegram.yml, every 30 min). Each run:
  1. loads the AI news digest — by default the *same* news.json the dashboard
     publishes (TELEGRAM_NEWS_URL), so the channel mirrors the dashboard exactly,
  2. drops items already sent (tracked in a small JSON state file),
  3. posts the rest to the channel, newest at the bottom,
  4. updates the state file (the workflow commits it back so the next run
     remembers what was already delivered).

Env:
  TELEGRAM_BOT_TOKEN     bot token from @BotFather
  TELEGRAM_CHAT_ID       "@channel" (public) or "-100..." (private channel id)
  TELEGRAM_NEWS_URL      dashboard news.json to mirror (default: the GitHub Pages
                         site). Set empty to fetch news live instead.
  TELEGRAM_STATE         state file path (default: state/telegram_sent.json)
  TELEGRAM_MAX_PER_RUN   cap messages per run (default 10; 0 = no cap)
  TELEGRAM_SEND_FIRST_RUN  set to 1 to also send on the very first (seeding) run
  SUH_DH_DEMO=1          use sample data (offline)

Flags:
  --dry-run   print messages instead of sending (also auto-enabled if creds missing)
  --seed      mark current items as sent without sending (prime the state file)
  --live      fetch news live (ignore TELEGRAM_NEWS_URL) instead of the dashboard
"""

from __future__ import annotations

import json
import os
import sys
import time

from app import news, telegram

STATE_PATH = os.environ.get("TELEGRAM_STATE", "state/telegram_sent.json")
MAX_PER_RUN = int(os.environ.get("TELEGRAM_MAX_PER_RUN", "10"))
# The dashboard build commits its news digest here (build.py). Reading this
# committed file keeps the channel identical to the dashboard, with no live
# re-fetch that drifts apart. Can be an http(s):// URL instead if preferred.
DEFAULT_NEWS_SOURCE = "data/news.json"
NEWS_SOURCE = os.environ.get("TELEGRAM_NEWS_URL", DEFAULT_NEWS_SOURCE).strip()


def load_digest() -> dict:
    """Mirror the dashboard's news.json by default; fall back to a live fetch."""
    demo = os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")
    if demo or "--live" in sys.argv or not NEWS_SOURCE:
        return news.get_news()
    try:
        if NEWS_SOURCE.startswith(("http://", "https://", "file:")):
            digest = telegram.fetch_digest(NEWS_SOURCE)
        else:
            with open(NEWS_SOURCE, encoding="utf-8") as f:
                digest = json.load(f)
        print(f"Loaded dashboard digest from {NEWS_SOURCE}")
        return digest
    except Exception as e:
        # Don't go silent if the file/site is briefly unavailable — fetch live so
        # the channel still gets news (it may differ from the dashboard this once).
        print(f"Dashboard digest unavailable ({e}); falling back to live fetch.")
        return news.get_news()


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    dry_run = "--dry-run" in sys.argv or not (token and chat)
    seed_only = "--seed" in sys.argv

    if dry_run and not (token and chat) and "--dry-run" not in sys.argv:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set -> dry-run (no messages sent).")

    digest = load_digest()
    items = digest.get("items", [])
    print(f"Digest: {len(items)} item(s){' [DEMO]' if digest.get('demo') else ''}.")

    had_state = os.path.exists(STATE_PATH)
    state = telegram.load_state(STATE_PATH)
    sent_ids = list(state.get("sent", []))
    sent_set = set(sent_ids)

    fresh = telegram.new_items(items, sent_set)  # newest-first
    fresh.reverse()  # send oldest-first so the newest lands at the bottom

    # First ever run with no history: prime the state without flooding the
    # channel (unless explicitly told to send), so subscribers only get genuinely
    # new headlines from here on.
    first_run = not had_state and not sent_ids
    send_first = os.environ.get("TELEGRAM_SEND_FIRST_RUN", "") in ("1", "true", "True")
    if seed_only or (first_run and not send_first and not dry_run):
        for it in items:
            iid = telegram.item_id(it)
            if iid and iid not in sent_set:
                sent_ids.append(iid)
                sent_set.add(iid)
        telegram.save_state(STATE_PATH, sent_ids)
        print(f"Seeded {len(items)} item(s) without sending (first run / --seed).")
        return 0

    if not fresh:
        print("No new items to send.")
        return 0

    to_send = fresh[:MAX_PER_RUN] if MAX_PER_RUN > 0 else fresh
    sent_count = 0
    for it in to_send:
        text = telegram.format_message(it)
        if dry_run:
            print("------\n" + text)
        else:
            telegram.send_with_retry(token, chat, text)
            time.sleep(1)  # be gentle with the Bot API
        sent_ids.append(telegram.item_id(it))
        sent_count += 1

    # Dry-run is a pure preview: don't mark items as sent (so once real creds are
    # set, nothing is silently skipped).
    if not dry_run:
        telegram.save_state(STATE_PATH, sent_ids)
    queued = len(fresh) - sent_count
    suffix = " (dry-run)" if dry_run else ""
    print(f"Sent {sent_count} item(s){suffix}." + (f" {queued} queued for next run." if queued else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
