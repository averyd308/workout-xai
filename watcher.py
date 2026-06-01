#!/usr/bin/env python3
"""
watcher.py — Local reaction watcher and data integrity checker.

Polls Slack for reactions on daily/weekend posts and dual-writes to local
SQLite (watcher.db) and Supabase so they serve as independent checks.

Usage:
  python watcher.py                     Run watcher: backfill then poll every 5 min
  python watcher.py --backfill          One-time backfill to local DB only, then exit
  python watcher.py --backfill --sync   Backfill and write any missing entries to Supabase
  python watcher.py --compare           Compare local DB vs Supabase and show discrepancies
  python watcher.py --scan-history      Scan full channel history for posts not in daily_posts

Slash commands still go to the Vercel bot — this script is a passive watcher only.
"""

import os
import sys
import time
import logging
from datetime import date, datetime, timezone, timedelta

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

import database
import local_db

CHANNEL_IDS = [c.strip() for c in os.environ["SLACK_CHANNEL_ID"].split(",") if c.strip()]
POLL_INTERVAL = 300  # seconds between polls

STRETCH_EMOJI = "person_in_lotus_position"
WORKOUT_EMOJI = "muscle"
GYM_EMOJIS = {"man-lifting-weights", "woman-lifting-weights"}
OTHER_ACTIVITY_EMOJIS = {
    "bike", "bicyclist", "mountain_bicyclist",
    "swimmer", "surfer", "rowing",
    "skier", "snowboarder", "person_climbing", "mountain_snow", "hiking_boot",
    "basketball", "soccer", "football", "tennis", "baseball", "volleyball",
    "handball",
    "badminton", "ping_pong",
    "boulder", "rock", "ladder",
    "boxing_glove", "martial_arts_uniform", "person_fencing",
    "dancer", "man_dancing", "golf",
    "athletic_shoe", "trophy", "sports_medal", "medal_sports",
}


def classify_emoji(name: str):
    """Map a reaction name to (activity_type, description), or (None, None) to skip."""
    base = name.split("::")[0]  # strip skin-tone suffixes like muscle::skin-tone-3
    if base == STRETCH_EMOJI:
        return "stretch", base
    if base == WORKOUT_EMOJI or base.startswith("muscle"):
        return "workout", base
    if base in GYM_EMOJIS:
        return "gym", base
    if base in OTHER_ACTIVITY_EMOJIS:
        return "other", base
    return None, None


def get_bot_user_id(client: WebClient) -> str:
    return client.auth_test()["user_id"]


def fetch_reactions(client: WebClient, channel_id: str, message_ts: str) -> dict:
    """Return {emoji_name: [user_id, ...]} for a message. Empty dict on error."""
    try:
        resp = client.reactions_get(channel=channel_id, timestamp=message_ts, full=True)
        return {r["name"]: r["users"] for r in resp["message"].get("reactions", [])}
    except SlackApiError as e:
        logging.warning(f"reactions.get failed {channel_id}/{message_ts}: {e.response['error']}")
        return {}


def sync_post_reactions(client: WebClient, post: dict, bot_user_id: str, write_supabase: bool):
    """
    Fetch reactions on a post and write new ones to local DB (and optionally Supabase).
    Returns (local_new, supa_new).
    """
    ch = post["channel_id"]
    ts = post["message_ts"]
    date_str = post["date"]
    reactions = fetch_reactions(client, ch, ts)

    local_new = supa_new = 0
    for emoji, users in reactions.items():
        activity_type, description = classify_emoji(emoji)
        if not activity_type:
            continue
        for user_id in users:
            if user_id == bot_user_id:
                continue
            if local_db.log_activity(user_id, activity_type, description, ch, date_str):
                local_new += 1
            if write_supabase:
                if database.log_activity(user_id, activity_type, description, ch, date_str):
                    supa_new += 1
                    logging.info(f"Synced to Supabase: {user_id} {activity_type} {date_str}")
    return local_new, supa_new


# ── Backfill ──────────────────────────────────────────────────────────────────

def load_posts_from_supabase():
    """Pull all known daily_posts from Supabase into local DB."""
    posts = database.get_all_posts()
    for p in posts:
        local_db.save_daily_post(
            p["date"], p["message_ts"], p["channel_id"],
            p.get("stretch_option", ""), p.get("workout_option", ""),
        )
    logging.info(f"Loaded {len(posts)} posts from Supabase → local DB")
    return posts


def backfill(client: WebClient, write_supabase: bool = False):
    """Scan all known posts and sync their reactions to local DB (+ Supabase if --sync)."""
    bot_id = get_bot_user_id(client)
    posts = load_posts_from_supabase()

    total_local = total_supa = 0
    logging.info(f"Backfilling {len(posts)} posts (write_supabase={write_supabase})...")
    for i, post in enumerate(posts, 1):
        l, s = sync_post_reactions(client, post, bot_id, write_supabase)
        total_local += l
        total_supa += s
        if i % 20 == 0:
            logging.info(f"  {i}/{len(posts)} processed...")
        time.sleep(0.3)  # stay within Slack rate limits

    logging.info(f"Backfill done: {total_local} new local entries, {total_supa} new Supabase entries")
    if not write_supabase and total_local:
        print("\nTip: run with --backfill --sync to also write missing entries to Supabase")


def scan_history(client: WebClient, write_supabase: bool = False):
    """
    Walk full channel history to find bot posts not in daily_posts, then track their reactions.
    This catches posts Supabase lost track of (e.g. DB outage during post).
    """
    bot_id = get_bot_user_id(client)
    known_ts = {p["message_ts"] for p in local_db.get_all_posts()}

    found = 0
    for ch in CHANNEL_IDS:
        logging.info(f"Scanning history for channel {ch}...")
        cursor = None
        while True:
            kwargs = {"channel": ch, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = client.conversations_history(**kwargs)
            except SlackApiError as e:
                logging.error(f"conversations.history error: {e.response['error']}")
                break

            for msg in resp["messages"]:
                ts = msg["ts"]
                if msg.get("user") != bot_id and msg.get("bot_id") is None:
                    continue
                if ts in known_ts:
                    continue
                # Determine date from Unix timestamp
                msg_date = str(datetime.fromtimestamp(float(ts), tz=timezone.utc).date())
                fake_post = {"channel_id": ch, "message_ts": ts, "date": msg_date}
                local_db.save_daily_post(msg_date, ts, ch)
                known_ts.add(ts)
                l, s = sync_post_reactions(client, fake_post, bot_id, write_supabase)
                if l or s:
                    logging.info(f"Orphan post {ts} ({msg_date}): {l} local, {s} supa")
                    found += 1
                time.sleep(0.3)

            if not resp.get("has_more"):
                break
            cursor = resp["response_metadata"]["next_cursor"]
            time.sleep(1)

    logging.info(f"History scan done: {found} orphaned posts with trackable reactions")


# ── Compare ───────────────────────────────────────────────────────────────────

def compare():
    """Show discrepancies between local SQLite and Supabase activity_logs."""
    supa_rows = (
        database.get_client()
        .table("activity_logs")
        .select("user_id,date,activity_type,channel_id")
        .execute()
        .data
    )
    supa_set = {
        (r["user_id"], r["date"], r["activity_type"], r.get("channel_id") or "")
        for r in supa_rows
    }
    local_set = local_db.get_all_activity_set()

    in_supa_only = supa_set - local_set
    in_local_only = local_set - supa_set

    print(f"\n{'='*60}")
    print(f"Local SQLite vs Supabase")
    print(f"{'='*60}")
    print(f"Supabase total:   {len(supa_set)}")
    print(f"Local DB total:   {len(local_set)}")
    print(f"In Supabase only: {len(in_supa_only)}")
    print(f"In local only:    {len(in_local_only)}")

    if in_supa_only:
        print(f"\n--- Supabase only ({len(in_supa_only)}) ---")
        print("(custom /workout entries, Strava, live sessions — not reaction-trackable)")
        for uid, d, atype, ch in sorted(in_supa_only):
            print(f"  {d}  {atype:<10}  {uid}  ch={ch}")

    if in_local_only:
        print(f"\n--- Local only — missed by Vercel bot ({len(in_local_only)}) ---")
        for uid, d, atype, ch in sorted(in_local_only):
            print(f"  {d}  {atype:<10}  {uid}  ch={ch}")

    print()
    if in_local_only:
        print("Run `python watcher.py --backfill --sync` to push local-only entries to Supabase.")


# ── Poll loop ─────────────────────────────────────────────────────────────────

def poll_recent(client: WebClient, bot_user_id: str, days: int = 2):
    """Check posts from the last N days for new reactions."""
    cutoff = str(date.today() - timedelta(days=days))
    posts = [p for p in local_db.get_all_posts() if p["date"] >= cutoff]
    local_new = supa_new = 0
    for post in posts:
        l, s = sync_post_reactions(client, post, bot_user_id, write_supabase=True)
        local_new += l
        supa_new += s
    if local_new or supa_new:
        logging.info(f"Poll caught: {local_new} new local, {supa_new} new Supabase entries")


def run_watcher(client: WebClient):
    local_db.init_db()
    database.init_db()

    logging.info("Starting watcher — running initial backfill...")
    backfill(client, write_supabase=True)

    bot_user_id = get_bot_user_id(client)
    logging.info(f"Watching {len(CHANNEL_IDS)} channel(s), polling every {POLL_INTERVAL}s. Ctrl+C to stop.")

    while True:
        try:
            time.sleep(POLL_INTERVAL)
            poll_recent(client, bot_user_id)
        except KeyboardInterrupt:
            logging.info("Watcher stopped.")
            break
        except Exception as e:
            logging.error(f"Poll error: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = set(sys.argv[1:])
    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

    local_db.init_db()
    database.init_db()

    if "--compare" in args:
        load_posts_from_supabase()
        compare()
    elif "--scan-history" in args:
        load_posts_from_supabase()
        scan_history(client, write_supabase="--sync" in args)
    elif "--backfill" in args:
        backfill(client, write_supabase="--sync" in args)
    else:
        run_watcher(client)
