"""
One-time backfill: scan all past daily post reactions and log any unrecognized
emojis as "other" activity. Safe to re-run — log_activity deduplicates.

Usage:
    cd slack-workout-bot
    python backfill_other_reactions.py
"""

import os
import sys
import logging

from slack_sdk import WebClient

import database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SKIP_EMOJIS = {"person_in_lotus_position", "muscle", "runner", "man-lifting-weights", "woman-lifting-weights", "tv"}

OTHER_ACTIVITY_EMOJIS = {
    "bike", "bicyclist", "mountain_bicyclist",
    "swimmer", "surfer", "rowing",
    "skier", "snowboarder", "person_climbing", "mountain_snow", "hiking_boot",
    "basketball", "soccer", "football", "tennis", "baseball", "volleyball",
    "badminton", "ping_pong",
    "boxing_glove", "martial_arts_uniform", "person_fencing",
    "dancer", "man_dancing",
    "golf",
    "athletic_shoe", "trophy", "sports_medal", "medal_sports",
}

def get_bot_user_id(client):
    return client.auth_test()["user_id"]

def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        sys.exit("SLACK_BOT_TOKEN not set")

    client = WebClient(token=token)
    bot_id = get_bot_user_id(client)
    logging.info(f"Bot user ID: {bot_id}")

    posts = database.get_all_posts()
    logging.info(f"Found {len(posts)} daily posts to scan")

    total_logged = 0
    total_skipped = 0

    for post in posts:
        ts = post["message_ts"]
        channel_id = post.get("channel_id")
        post_date = post["date"]

        if not ts or not channel_id:
            logging.warning(f"Skipping post {post_date} — missing ts or channel_id")
            continue

        try:
            resp = client.reactions_get(channel=channel_id, timestamp=ts, full=True)
        except Exception as e:
            logging.warning(f"Could not fetch reactions for {post_date} ({ts}): {e}")
            continue

        message = resp.get("message", {})
        reactions = message.get("reactions", [])

        for reaction in reactions:
            emoji = reaction["name"]
            if emoji in SKIP_EMOJIS:
                continue

            for user_id in reaction.get("users", []):
                if user_id == bot_id:
                    continue

                if emoji not in OTHER_ACTIVITY_EMOJIS and not emoji.startswith("muscle::"):
                    continue

                logged = database.log_activity(
                    user_id, "other", f":{emoji}:", channel_id=channel_id, date_str=post_date
                )
                if logged:
                    total_logged += 1
                    logging.info(f"  Logged :{emoji}: for {user_id} on {post_date}")
                else:
                    total_skipped += 1

    logging.info(f"Done. Logged: {total_logged}, already existed: {total_skipped}")

if __name__ == "__main__":
    main()
