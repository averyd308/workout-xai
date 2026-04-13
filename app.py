import os
import sys
import logging
from datetime import datetime, date, timedelta

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

import database
import workouts
from bot import parse_reminder_input, send_pending_reminders

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = App(token=os.environ["SLACK_BOT_TOKEN"])
scheduler = BackgroundScheduler()


CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
POST_HOUR = int(os.environ.get("POST_HOUR", 9))
POST_MINUTE = int(os.environ.get("POST_MINUTE", 0))
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")

STRETCH_EMOJI = "person_in_lotus_position"
WORKOUT_EMOJI = "muscle"
GYM_EMOJIS = ["man-lifting-weights", "woman-lifting-weights"]


# ── Daily Post ────────────────────────────────────────────────────────────────

def post_daily_message(force=False):
    if not force and database.get_today_post():
        logging.info("Daily post already sent today, skipping.")
        return

    stretch, workout = workouts.get_daily_options()
    today = str(datetime.now().date())

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Good afternoon! Today's movement options 🌅"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "React to log your activity — you can do one or both!",
            },
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
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Log your own activity with `/workout [description]`  •  Check your stats with `/userstats`",
                }
            ],
        },
    ]

    result = app.client.chat_postMessage(
        channel=CHANNEL_ID,
        text=f"Today's movement options: {stretch['title']} or {workout['title']}",
        blocks=blocks,
    )
    database.save_daily_post(today, result["ts"], CHANNEL_ID, stretch["title"], workout["title"])
    logging.info(f"Daily post sent: ts={result['ts']}")


# ── Reaction Handlers ─────────────────────────────────────────────────────────


@app.event("reaction_added")
def handle_reaction_added(event):
    if event["item"]["type"] != "message":
        return

    post = database.get_post_by_ts(event["item"]["ts"])
    if not post:
        return

    _, _, _, _, stretch_title, workout_title = post
    user_id = event["user"]
    emoji = event["reaction"]

    if emoji == STRETCH_EMOJI:
        logged = database.log_activity(user_id, "stretch", stretch_title)
        if logged:
            stats = database.get_user_stats(user_id)
            count = stats.get("stretch", 0)
            app.client.chat_postEphemeral(
                channel=CHANNEL_ID,
                user=user_id,
                text=f":person_in_lotus_position: Nice stretch! You've logged *{count}* stretching session{'s' if count != 1 else ''} total.",
            )

    elif emoji == WORKOUT_EMOJI:
        logged = database.log_activity(user_id, "workout", workout_title)
        if logged:
            stats = database.get_user_stats(user_id)
            count = stats.get("workout", 0)
            app.client.chat_postEphemeral(
                channel=CHANNEL_ID,
                user=user_id,
                text=f":muscle: Great workout! You've logged *{count}* workout{'s' if count != 1 else ''} total.",
            )

    elif emoji in GYM_EMOJIS:
        logged = database.log_activity(user_id, "gym", "Gym workout")
        if logged:
            stats = database.get_user_stats(user_id)
            count = stats.get("gym", 0)
            app.client.chat_postEphemeral(
                channel=CHANNEL_ID,
                user=user_id,
                text=f":man-lifting-weights: Gym session logged! You've hit the gym *{count}* {'time' if count == 1 else 'times'} total.",
            )


@app.event("reaction_removed")
def handle_reaction_removed(event):
    if event["item"]["type"] != "message":
        return

    post = database.get_post_by_ts(event["item"]["ts"])
    if not post:
        return

    user_id = event["user"]
    emoji = event["reaction"]

    if emoji == STRETCH_EMOJI:
        database.remove_activity(user_id, "stretch")
    elif emoji == WORKOUT_EMOJI:
        database.remove_activity(user_id, "workout")
    elif emoji in GYM_EMOJIS:
        database.remove_activity(user_id, "gym")


# ── Slash Commands ────────────────────────────────────────────────────────────

@app.command("/workout")
def handle_workout(ack, command, respond):
    ack()
    description = command["text"].strip()
    if not description:
        respond("Please describe your workout. Example: `/workout 30 min run`")
        return

    user_id = command["user_id"]
    database.log_activity(user_id, "custom", description)
    stats = database.get_user_stats(user_id)
    total = sum(stats.values())
    custom = stats.get("custom", 0)
    respond(
        f":white_check_mark: Logged: _{description}_\n"
        f"Custom activities: *{custom}*  •  Total logged: *{total}*"
    )


@app.command("/userstats")
def handle_mystats(ack, command, respond):
    ack()
    stats = database.get_user_stats(command["user_id"])
    if not stats:
        respond("You haven't logged anything yet! React to today's post or use `/workout` to get started.")
        return

    stretch = stats.get("stretch", 0)
    workout = stats.get("workout", 0)
    gym = stats.get("gym", 0)
    custom = stats.get("custom", 0)
    total = sum(stats.values())

    respond(
        f"*Your activity stats (all time):*\n"
        f":person_in_lotus_position:  Stretch sessions: *{stretch}*\n"
        f":muscle:  Workouts: *{workout}*\n"
        f":man-lifting-weights:  Gym sessions: *{gym}*\n"
        f":running:  Custom activities: *{custom}*\n"
        f"─────────────────────\n"
        f"Total: *{total}* activities"
    )


@app.command("/teamstats")
def handle_teamstats(ack, command, respond):
    ack()
    weekly = database.get_weekly_stats()
    if not weekly:
        respond("No activity logged in the past 7 days yet. Be the first!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*Team activity — last 7 days:*\n"]
    for i, (user_id, count) in enumerate(weekly):
        medal = medals[i] if i < 3 else "▪️"
        lines.append(f"{medal} <@{user_id}>: *{count}* {'activity' if count == 1 else 'activities'}")

    respond("\n".join(lines))


# ── Leaderboards ──────────────────────────────────────────────────────────────

def _build_leaderboard_blocks(title, rows):
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (user_id, reacts, custom) in enumerate(rows):
        total = reacts + custom
        medal = medals[i] if i < 3 else f"{i + 1}."
        parts = []
        if reacts:
            parts.append(f":muscle: {reacts} react{'s' if reacts != 1 else ''}")
        if custom:
            parts.append(f":running: {custom} custom")
        detail = "  •  ".join(parts) if parts else "no activity"
        lines.append(f"{medal} <@{user_id}>: *{total}* total  ›  {detail}")
    return {"text": f"*{title}*\n\n" + "\n".join(lines), "response_type": "in_channel"}


@app.command("/pg-weeklyleaderboard")
def handle_weekly_leaderboard(ack, respond):
    ack()
    rows, monday = database.get_weekly_leaderboard()
    if not rows:
        respond({"text": "No activity logged this week yet. Be the first!", "response_type": "in_channel"})
        return

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    today = date.today()
    title = f"*Weekly Leaderboard  •  {monday.strftime('%b %d')} – {today.strftime('%b %d')}*"
    lines = [title, ""]
    for i, (user_id, reacts, custom) in enumerate(rows[:5]):
        total = reacts + custom
        medal = medals[i]
        parts = []
        if reacts:
            parts.append(f":muscle: {reacts} react{'s' if reacts != 1 else ''}")
        if custom:
            parts.append(f":running: {custom} custom")
        detail = "  •  ".join(parts) if parts else "no activity"
        lines.append(f"{medal} <@{user_id}>: *{total}* total  ›  {detail}")
        if custom:
            descriptions = database.get_weekly_custom_descriptions(user_id, monday)
            lines.append(f"     _{', '.join(descriptions)}_")

    respond({"text": "\n".join(lines), "response_type": "in_channel"})


@app.command("/pg-leaderboard")
def handle_alltime_leaderboard(ack, respond):
    ack()
    rows = database.get_alltime_leaderboard()
    if not rows:
        respond({"text": "No activity logged yet. Be the first!", "response_type": "in_channel"})
        return
    respond(_build_leaderboard_blocks("All-Time Leaderboard", rows))


# ── Reminder Commands ─────────────────────────────────────────────────────────

@app.command("/setreminder")
def handle_set_reminder(ack, command, respond):
    ack()
    text = command["text"].strip()
    if not text:
        respond("Usage: `/setreminder 9:00am ET`  or  `/setreminder 14:30 America/Chicago`\nTimezone is optional — defaults to the bot's timezone if omitted.")
        return
    time_str, tz = parse_reminder_input(text, TIMEZONE)
    if not time_str:
        respond(":x: Couldn't parse that time. Try something like `9:00am ET`, `2:30pm PT`, or `14:30 America/Chicago`.")
        return
    if not tz:
        respond(":x: Couldn't recognise that timezone. Try an abbreviation like `ET`, `CT`, `MT`, `PT`, or a full name like `America/New_York`.")
        return
    user_id = command["user_id"]
    database.set_user_reminder(user_id, time_str, tz)
    h, m = int(time_str[:2]), int(time_str[3:])
    ampm = "am" if h < 12 else "pm"
    display_h = h % 12 or 12
    display = f"{display_h}:{m:02d}{ampm}"
    respond(f":alarm_clock: Got it! I'll DM you a reminder at *{display} {tz}* each day to check the workout.")


@app.command("/cancelreminder")
def handle_cancel_reminder(ack, command, respond):
    ack()
    user_id = command["user_id"]
    existing = database.get_user_reminder(user_id)
    if not existing:
        respond("You don't have a reminder set. Use `/setreminder 9:00am` to set one.")
        return
    database.delete_user_reminder(user_id)
    respond(":white_check_mark: Your daily reminder has been cancelled.")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    database.init_db()

    scheduler.add_job(
        post_daily_message,
        trigger="cron",
        hour=POST_HOUR,
        minute=POST_MINUTE,
        timezone=TIMEZONE,
    )
    scheduler.add_job(
        send_pending_reminders,
        trigger="cron",
        minute="*",
        timezone=TIMEZONE,
        args=[app.client, TIMEZONE],
    )
    scheduler.start()
    logging.info(f"Scheduler started — daily post at {POST_HOUR}:{POST_MINUTE:02d} ({TIMEZONE}), reminders checked every minute")

    if "--post-now" in sys.argv:
        logging.info("--post-now flag detected, posting immediately...")
        post_daily_message(force=True)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
