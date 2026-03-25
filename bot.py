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

CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
STRETCH_EMOJI = "person_in_lotus_position"
WORKOUT_EMOJI = "muscle"
CUSTOM_EMOJI = "runner"

_bot_user_id = None


def get_bot_user_id():
    global _bot_user_id
    if _bot_user_id is None:
        try:
            _bot_user_id = bolt_app.client.auth_test()["user_id"]
        except Exception:
            pass
    return _bot_user_id


def post_daily_message(force=False):
    if not force and database.get_today_post(CHANNEL_ID):
        logging.info("Daily post already sent today, skipping.")
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
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Did a separate workout? Don't forget to log it with `/workout [description]`  •  Check your stats with `/userstats`",
                }
            ],
        },
    ]

    result = bolt_app.client.chat_postMessage(
        channel=CHANNEL_ID,
        text=f"Today's movement options: {stretch['title']} or {workout['title']}",
        blocks=blocks,
    )
    database.save_daily_post(today, result["ts"], CHANNEL_ID, stretch["title"], workout["title"])
    logging.info(f"Daily post sent: ts={result['ts']}")

    # Auto-react with activity emojis so users can tap them directly
    for emoji in [STRETCH_EMOJI, WORKOUT_EMOJI]:
        try:
            bolt_app.client.reactions_add(channel=CHANNEL_ID, timestamp=result["ts"], name=emoji)
        except Exception as e:
            logging.warning(f"Failed to add reaction {emoji}: {e}")
    if custom_suggestion:
        try:
            bolt_app.client.reactions_add(channel=CHANNEL_ID, timestamp=result["ts"], name=CUSTOM_EMOJI)
        except Exception as e:
            logging.warning(f"Failed to add reaction {CUSTOM_EMOJI}: {e}")


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
    today_post = database.get_today_post()
    if today_post:
        stretch = today_post.get("stretch_option", "today's stretch")
        workout = today_post.get("workout_option", "today's workout")
        body = (
            f":alarm_clock: *Workout reminder!*\n\n"
            f"Don't forget to check today's movement options in <#{CHANNEL_ID}>:\n"
            f":person_in_lotus_position: *{stretch}*\n"
            f":muscle: *{workout}*\n\n"
            f"React to the post when you're done to log your activity!"
        )
    else:
        body = (
            f":alarm_clock: *Workout reminder!*\n\n"
            f"Head over to <#{CHANNEL_ID}> to check today's movement options and get moving!"
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
