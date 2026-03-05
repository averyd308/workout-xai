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


def post_daily_message(force=False):
    if not force and database.get_today_post():
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
                        f":running:  *{custom_suggestion['title']}*\n"
                        f"_{custom_suggestion['description']}_\n"
                        f"→ Log it with `/workout {custom_suggestion['title']}`"
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
                    "text": "Log your own activity with `/workout [description]`  •  Check your stats with `/mystats`",
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


# ── Reminder Helpers ──────────────────────────────────────────────────────────

def parse_reminder_time(text):
    """Parse a user-supplied time string into HH:MM (24h). Returns None on failure."""
    text = text.strip().lower().replace(" ", "")
    # Patterns: 9am, 9:00am, 14:30, 2:30pm, 9:00, 14
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", text)
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


def send_pending_reminders(client, timezone):
    """Send DMs to all users whose reminder time matches the current HH:MM."""
    import pytz
    tz = pytz.timezone(timezone)
    current_time = datetime.now(tz).strftime("%H:%M")
    user_ids = database.get_reminders_for_time(current_time)
    for user_id in user_ids:
        send_reminder_dm(client, user_id)
        logging.info(f"Sent reminder DM to {user_id} at {current_time}")
