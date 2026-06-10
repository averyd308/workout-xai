"""
Backfill channel_id on all activity_log rows that are missing it.

Scans every daily post ever made, re-reads its Slack reactions, then:
  - Updates existing rows that have NULL channel_id to the correct channel.
  - Inserts rows that are genuinely missing.

Safe to re-run — rows that already have a channel_id are untouched.

Usage:
    cd slack-workout-bot
    python backfill_channel_ids.py
"""

import os
import sys
import logging

from dotenv import load_dotenv
load_dotenv()

from slack_sdk import WebClient
import database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STRETCH_EMOJI = "person_in_lotus_position"
WORKOUT_EMOJI = "muscle"
CUSTOM_EMOJI = "runner"
GYM_EMOJIS = {"man-lifting-weights", "woman-lifting-weights"}
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
    "walking", "walking-the-dog", "walking_the_dog", "man-walking",
    "wood",
    "lawnmower-unscreen",
}


def _patch_channel_id(db_client, user_id, date_str, activity_type, description, channel_id):
    """
    Set channel_id on a row that currently has NULL channel_id.
    Returns the number of rows updated.
    """
    query = (
        db_client.table("activity_logs")
        .update({"channel_id": channel_id})
        .eq("user_id", user_id)
        .eq("date", date_str)
        .eq("activity_type", activity_type)
        .is_("channel_id", "null")
    )
    if activity_type == "other":
        query = query.eq("description", description)
    result = query.execute()
    return len(result.data)


def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        sys.exit("SLACK_BOT_TOKEN not set")

    client = WebClient(token=token)
    bot_id = client.auth_test()["user_id"]
    db = database.get_client()
    logging.info(f"Bot user ID: {bot_id}")

    posts = database.get_all_posts()
    logging.info(f"Scanning {len(posts)} daily posts")

    total_patched = 0
    total_inserted = 0
    total_skipped = 0

    for post in posts:
        ts = post.get("message_ts")
        channel_id = post.get("channel_id")
        post_date = post["date"]

        if not ts or not channel_id:
            logging.warning(f"Skipping {post_date} — missing ts or channel_id")
            continue

        try:
            resp = client.reactions_get(channel=channel_id, timestamp=ts, full=True)
        except Exception as e:
            logging.warning(f"Could not fetch reactions for {post_date} ({ts}): {e}")
            continue

        scheduled = database.get_scheduled_options(post_date)
        custom_title = scheduled[4] if scheduled and scheduled[4] else None
        stretch_title = post.get("stretch_option", "")
        workout_title = post.get("workout_option", "")

        for reaction in resp.get("message", {}).get("reactions", []):
            emoji = reaction["name"]
            for user_id in reaction.get("users", []):
                if user_id == bot_id:
                    continue

                if emoji == STRETCH_EMOJI or emoji.startswith("person_in_lotus_position::") or emoji.startswith("woman_in_lotus_position"):
                    activity_type, description = "stretch", stretch_title
                elif emoji == WORKOUT_EMOJI or emoji.startswith("muscle::"):
                    activity_type, description = "workout", workout_title
                elif emoji in GYM_EMOJIS:
                    activity_type, description = "gym", "Gym workout"
                elif emoji == CUSTOM_EMOJI:
                    if not custom_title:
                        continue
                    activity_type, description = "custom", ""
                elif emoji == "man-walking" or emoji.startswith("man-walking::"):
                    activity_type, description = "other", ":walking:"
                    # Normalize any existing row stored under the old emoji description
                    old_desc = f":{emoji}:"
                    result = db.table("activity_logs").update({"description": ":walking:"}).eq("user_id", user_id).eq("date", post_date).eq("activity_type", "other").eq("description", old_desc).execute()
                    if result.data:
                        total_patched += len(result.data)
                        logging.info(f"  Normalized man-walking desc for {user_id} on {post_date}")
                        continue
                elif emoji in OTHER_ACTIVITY_EMOJIS:
                    activity_type, description = "other", f":{emoji}:"
                else:
                    continue

                # First try to patch an existing NULL-channel row
                patched = _patch_channel_id(db, user_id, post_date, activity_type, description, channel_id)
                if patched:
                    total_patched += patched
                    logging.info(f"  Patched {activity_type} for {user_id} on {post_date} -> {channel_id}")
                    continue

                # Otherwise insert if genuinely missing
                logged = database.log_activity(user_id, activity_type, description, channel_id=channel_id, date_str=post_date)
                if logged:
                    total_inserted += 1
                    logging.info(f"  Inserted {activity_type} for {user_id} on {post_date}")
                else:
                    total_skipped += 1

    logging.info(f"Done. Patched: {total_patched}, Inserted: {total_inserted}, Already correct: {total_skipped}")


if __name__ == "__main__":
    main()
