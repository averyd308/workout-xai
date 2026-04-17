import os
import re
import logging
from datetime import datetime

from slack_bolt import App

import database
import workouts

bolt_app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    process_before_response=True,
)

CHANNEL_IDS = [c.strip() for c in os.environ["SLACK_CHANNEL_ID"].split(",") if c.strip()]
CHANNEL_ID = CHANNEL_IDS[0]  # primary channel; used as fallback
STRETCH_EMOJI = "person_in_lotus_position"
WORKOUT_EMOJI = "muscle"
CUSTOM_EMOJI = "runner"
GYM_EMOJIS = ["man-lifting-weights", "woman-lifting-weights"]

# Emojis that count as "other" activity when reacted on the daily post.
# Skin-tone variants of "muscle" (e.g. muscle::skin-tone-3) are handled separately in the reaction handler.
# Add any new fitness emojis here to have them tracked.
OTHER_ACTIVITY_EMOJIS = {
    # Cycling
    "bike", "bicyclist", "mountain_bicyclist",
    # Water
    "swimmer", "surfer", "rowing",
    # Snow / outdoor
    "skier", "snowboarder", "person_climbing", "mountain_snow", "hiking_boot",
    # Court / field sports
    "basketball", "soccer", "football", "tennis", "baseball", "volleyball",
    "badminton", "ping_pong",
    # Combat / other sports
    "boxing_glove", "martial_arts_uniform", "person_fencing",
    # Dance / cardio
    "dancer", "man_dancing",
    # Golf / leisure sport
    "golf",
    # General fitness
    "athletic_shoe", "trophy", "sports_medal", "medal_sports",
}

_bot_user_id = None


def get_bot_user_id():
    global _bot_user_id
    if _bot_user_id is None:
        try:
            _bot_user_id = bolt_app.client.auth_test()["user_id"]
        except Exception:
            pass
    return _bot_user_id


def post_daily_message(channel_id=None, force=False):
    _post_daily_to_channel(channel_id or CHANNEL_ID, force=force)


def _post_daily_to_channel(channel_id, force=False):
    if not force and database.get_today_post(channel_id):
        logging.info(f"Daily post already sent today to {channel_id}, skipping.")
        return

    today = str(datetime.now().date())
    scheduled = database.get_scheduled_options(today)
    if scheduled and scheduled[0] and scheduled[2]:
        stretch = {"title": scheduled[0], "description": scheduled[1] or ""}
        workout = {"title": scheduled[2], "description": scheduled[3] or ""}
        custom_suggestion = {"title": scheduled[4], "description": scheduled[5] or ""} if scheduled[4] else None
    else:
        stretch, workout = workouts.get_daily_options()
        custom_suggestion = None

    header_text = database.get_setting("header", "Good morning! Today's movement options 🌅")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "React to log your activity — you can do one or both!"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":person_in_lotus_position:  *{stretch['title']}*\n"
                    f"_{stretch['description']}_\n"
                    f"→ React with :person_in_lotus_position: when done"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":muscle:  *{workout['title']}*\n"
                    f"_{workout['description']}_\n"
                    f"→ React with :muscle: when done"
                ),
            },
        },
    ]

    if custom_suggestion:
        blocks += [
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":runner:  *{custom_suggestion['title']}*\n"
                        f"_{custom_suggestion['description']}_\n"
                        f"→ React with :runner: when done"
                    ),
                },
            },
        ]

    blocks += [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":man-lifting-weights: :woman-lifting-weights:  *Hit the gym?*\n"
                    "→ React with :man-lifting-weights: or :woman-lifting-weights: if you did a gym workout today"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":zap:  *Did something else?*\nReact with any emoji that represents your workout to track it — a swim :swimmer:, a bike ride :bicyclist:, a hike :mountain_snow:, whatever fits!",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Check your stats with `/userstats`",
                }
            ],
        },
    ]

    result = bolt_app.client.chat_postMessage(
        channel=channel_id,
        text=f"Today's movement options: {stretch['title']} or {workout['title']}",
        blocks=blocks,
        unfurl_links=False,
        unfurl_media=False,
    )
    database.save_daily_post(today, result["ts"], channel_id, stretch["title"], workout["title"])
    logging.info(f"Daily post sent to {channel_id}: ts={result['ts']}")

    # Auto-react with activity emojis so users can tap them directly
    for emoji in [STRETCH_EMOJI, WORKOUT_EMOJI]:
        try:
            bolt_app.client.reactions_add(channel=channel_id, timestamp=result["ts"], name=emoji)
        except Exception as e:
            logging.warning(f"Failed to add reaction {emoji}: {e}")
    if custom_suggestion:
        try:
            bolt_app.client.reactions_add(channel=channel_id, timestamp=result["ts"], name=CUSTOM_EMOJI)
        except Exception as e:
            logging.warning(f"Failed to add reaction {CUSTOM_EMOJI}: {e}")
    for emoji in GYM_EMOJIS:
        try:
            bolt_app.client.reactions_add(channel=channel_id, timestamp=result["ts"], name=emoji)
        except Exception as e:
            logging.warning(f"Failed to add reaction {emoji}: {e}")


# ── Weekend Post ─────────────────────────────────────────────────────────────

def post_weekend_message(channel_id=None, force=False):
    """Post a weekend check-in message on Saturday or Sunday."""
    from datetime import datetime
    ch = channel_id or CHANNEL_ID
    today = str(datetime.now().date())

    if not force and database.get_today_post(ch):
        logging.info(f"Weekend post already sent today to {ch}, skipping.")
        return

    day_name = datetime.now().strftime("%A")  # "Saturday" or "Sunday"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Happy {day_name}! \U0001f389"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "If you are working and do a workout today, react to this message "
                    "with the proper emoji of the workout you did. It'll count towards your stats and the leaderboard!"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":person_in_lotus_position:  *Stretch*\n"
                    "→ React with :person_in_lotus_position: if you stretched"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":muscle:  *Workout*\n"
                    "→ React with :muscle: if you worked out"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":man-lifting-weights: :woman-lifting-weights:  *Hit the gym?*\n"
                    "→ React with :man-lifting-weights: or :woman-lifting-weights: if you did a gym workout"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":zap:  *Did something else?*\n"
                    "React with any emoji that represents your workout — a swim :swimmer:, "
                    "a bike ride :bicyclist:, a hike :mountain_snow:, whatever fits!"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Check your stats with `/userstats`",
                }
            ],
        },
    ]

    result = bolt_app.client.chat_postMessage(
        channel=ch,
        text=f"Happy {day_name}! React to log any workouts you do today.",
        blocks=blocks,
        unfurl_links=False,
        unfurl_media=False,
    )
    database.save_daily_post(today, result["ts"], ch, f"{day_name} stretch", f"{day_name} workout")
    logging.info(f"Weekend post sent to {ch}: ts={result['ts']}")

    # Auto-react so users can tap the emojis directly
    for emoji in [STRETCH_EMOJI, WORKOUT_EMOJI] + GYM_EMOJIS:
        try:
            bolt_app.client.reactions_add(channel=ch, timestamp=result["ts"], name=emoji)
        except Exception as e:
            logging.warning(f"Failed to add reaction {emoji}: {e}")


# ── Weekly Leaderboard Auto-Post ─────────────────────────────────────────────

def post_weekly_leaderboard(channel_id=None):
    """Post last week's leaderboard to the given channel (or all CHANNEL_IDS)."""
    from datetime import date, timedelta
    channels = [channel_id] if channel_id else CHANNEL_IDS

    last_week = date.today() - timedelta(days=7)
    sunday = last_week - timedelta(days=(last_week.weekday() + 1) % 7)
    saturday = sunday + timedelta(days=6)
    date_range = f"{sunday.strftime('%b %d')} – {saturday.strftime('%b %d')}"

    bot_id = get_bot_user_id()
    medals = ["🥇", "🥈", "🥉", "4.", "5."]

    for ch in channels:
        try:
            rows, _, _ = database.get_weekly_leaderboard(channel_id=ch, reference_date=last_week)
            rows = [r for r in rows if r[0] != bot_id]
            if not rows:
                bolt_app.client.chat_postMessage(
                    channel=ch,
                    text=f"*Weekly Leaderboard  •  {date_range}*\n\nNo activity logged last week.",
                )
                continue

            # Compute totals for everyone
            all_entries = []
            for uid, stretches, workouts, gym, custom, live, other in rows:
                other_total = sum(other.values()) if isinstance(other, dict) else other
                total = stretches + workouts + gym + custom + live + other_total
                all_entries.append((uid, stretches, workouts, gym, custom, live, other, total))

            # Find top 5 distinct totals; include everyone at those levels
            distinct_totals = sorted(set(e[-1] for e in all_entries), reverse=True)
            top5_totals = set(distinct_totals[:5])
            eligible = [e for e in all_entries if e[-1] in top5_totals]

            lines = [f"*Weekly Leaderboard  •  {date_range}*", ""]
            for rank_idx, total_val in enumerate(distinct_totals[:5]):
                group = [e for e in eligible if e[-1] == total_val]
                medal = medals[rank_idx] if rank_idx < len(medals) else f"{rank_idx + 1}."
                entries = []
                for uid, stretches, workouts, gym, custom, live, other, total in group:
                    parts = []
                    if stretches:
                        parts.append(f":person_in_lotus_position: {stretches}")
                    if workouts:
                        parts.append(f":muscle: {workouts}")
                    if gym:
                        parts.append(f":man-lifting-weights: {gym}")
                    if live:
                        parts.append(f":tv: {live}")
                    if custom:
                        parts.append(f":runner: {custom}")
                    if isinstance(other, dict):
                        for emoji, count in other.items():
                            parts.append(f"{emoji} {count}")
                    elif other:
                        parts.append(f":zap: {other}")
                    detail = "  •  ".join(parts) if parts else "no activity"
                    entries.append(f"<@{uid}>: *{total}* total  ›  {detail}")
                lines.append(f"{medal} " + ",     ".join(entries))

            bolt_app.client.chat_postMessage(
                channel=ch,
                text="\n".join(lines),
            )
            logging.info(f"Posted weekly leaderboard to {ch} for {date_range}")
        except Exception as e:
            logging.error(f"Failed to post weekly leaderboard to {ch}: {e}")


# ── Reminder Helpers ──────────────────────────────────────────────────────────

TZ_ALIASES = {
    "et": "America/New_York", "est": "America/New_York", "edt": "America/New_York",
    "ct": "America/Chicago",  "cst": "America/Chicago",  "cdt": "America/Chicago",
    "mt": "America/Denver",   "mst": "America/Denver",   "mdt": "America/Denver",
    "pt": "America/Los_Angeles", "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "utc": "UTC", "gmt": "UTC",
}


def parse_reminder_time(time_text):
    """Parse a time string into HH:MM (24h). Returns None on failure."""
    time_text = time_text.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", time_text)
    if not m:
        return None
    hour, minute, meridiem = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_timezone(tz_text, default_timezone):
    """Resolve a user-supplied timezone string to an IANA name. Returns None on failure."""
    import pytz
    if not tz_text:
        return default_timezone
    resolved = TZ_ALIASES.get(tz_text.strip().lower(), tz_text.strip())
    try:
        pytz.timezone(resolved)
        return resolved
    except pytz.exceptions.UnknownTimeZoneError:
        return None


def parse_reminder_input(text, default_timezone):
    """Parse '/setreminder 9:00am ET' into (time_str, iana_timezone) or (None, None)."""
    parts = text.strip().split(None, 1)
    time_str = parse_reminder_time(parts[0])
    if not time_str:
        return None, None
    tz = parse_timezone(parts[1] if len(parts) > 1 else None, default_timezone)
    return time_str, tz


def send_reminder_dm(client, user_id):
    """DM a user reminding them to check today's workout."""
    channels_mention = " and ".join(f"<#{c}>" for c in CHANNEL_IDS)
    today_post = database.get_today_post(CHANNEL_ID)
    if today_post:
        stretch = today_post.get("stretch_option", "today's stretch")
        workout = today_post.get("workout_option", "today's workout")
        body = (
            f":alarm_clock: *Workout reminder!*\n\n"
            f"Don't forget to check today's movement options in {channels_mention}:\n"
            f":person_in_lotus_position: *{stretch}*\n"
            f":muscle: *{workout}*\n\n"
            f"React to the post when you're done to log your activity!"
        )
    else:
        body = (
            f":alarm_clock: *Workout reminder!*\n\n"
            f"Head over to {channels_mention} to check today's movement options and get moving!"
        )
    try:
        dm = client.conversations_open(users=user_id)
        client.chat_postMessage(channel=dm["channel"]["id"], text=body)
    except Exception as e:
        logging.error(f"Failed to send reminder DM to {user_id}: {e}")


def send_pending_reminders(client, default_timezone):
    """Send DMs to all users whose reminder time matches the current time in their timezone."""
    import pytz
    now_utc = datetime.now(pytz.utc)
    timezones = database.get_distinct_reminder_timezones()
    for tz_name in timezones:
        try:
            current_time = now_utc.astimezone(pytz.timezone(tz_name)).strftime("%H:%M")
            user_ids = database.get_reminders_for_time(current_time, tz_name)
            for user_id in user_ids:
                send_reminder_dm(client, user_id)
                logging.info(f"Sent reminder DM to {user_id} at {current_time} ({tz_name})")
        except Exception as e:
            logging.error(f"Error processing reminders for timezone {tz_name}: {e}")
