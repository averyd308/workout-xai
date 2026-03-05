import sys
import os
import logging
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request
from slack_bolt.adapter.flask import SlackRequestHandler

import database
from bot import bolt_app, CHANNEL_ID, STRETCH_EMOJI, WORKOUT_EMOJI, CUSTOM_EMOJI, post_daily_message, parse_reminder_input

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

flask_app = Flask(__name__)
slack_handler = SlackRequestHandler(bolt_app)

try:
    database.init_db()
except Exception as e:
    logging.warning(f"DB init skipped: {e}")


# ── Reaction Handlers ──────────────────────────────────────────────────────────

@bolt_app.event("reaction_added")
def handle_reaction_added(event):
    if event["item"]["type"] != "message":
        return

    post = database.get_post_by_ts(event["item"]["ts"])
    if not post:
        return

    stretch_title = post["stretch_option"]
    workout_title = post["workout_option"]
    user_id = event["user"]
    emoji = event["reaction"]

    if emoji == STRETCH_EMOJI:
        logged = database.log_activity(user_id, "stretch", stretch_title)
        if logged:
            stats = database.get_user_stats(user_id)
            count = stats.get("stretch", 0)
            bolt_app.client.chat_postEphemeral(
                channel=CHANNEL_ID,
                user=user_id,
                text=f":person_in_lotus_position: Nice stretch! You've logged *{count}* stretching session{'s' if count != 1 else ''} total.",
            )

    elif emoji == WORKOUT_EMOJI:
        logged = database.log_activity(user_id, "workout", workout_title)
        if logged:
            stats = database.get_user_stats(user_id)
            count = stats.get("workout", 0)
            bolt_app.client.chat_postEphemeral(
                channel=CHANNEL_ID,
                user=user_id,
                text=f":muscle: Great workout! You've logged *{count}* workout{'s' if count != 1 else ''} total.",
            )

    elif emoji == CUSTOM_EMOJI:
        scheduled = database.get_scheduled_options(post["date"])
        custom_title = scheduled[4] if scheduled and scheduled[4] else None
        if custom_title:
            logged = database.log_activity(user_id, "custom", custom_title)
            if logged:
                stats = database.get_user_stats(user_id)
                count = stats.get("custom", 0)
                bolt_app.client.chat_postEphemeral(
                    channel=CHANNEL_ID,
                    user=user_id,
                    text=f":runner: Nice work! You've logged *{count}* custom {'activity' if count == 1 else 'activities'} total.",
                )


@bolt_app.event("reaction_removed")
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
    elif emoji == CUSTOM_EMOJI:
        database.remove_activity(user_id, "custom")


# ── Slash Commands ─────────────────────────────────────────────────────────────

@bolt_app.command("/ping")
def handle_ping(ack, respond):
    logging.info("ping handler called")
    ack()
    respond("pong!")


@bolt_app.command("/workout")
def handle_workout(ack, command):
    try:
        description = command["text"].strip()
        if not description:
            ack("Please describe your workout. Example: `/workout 30 min run`")
            return

        user_id = command["user_id"]
        database.log_activity(user_id, "custom", description)
        stats = database.get_user_stats(user_id)
        total = sum(stats.values())
        custom = stats.get("custom", 0)
        ack(
            f":white_check_mark: Logged: _{description}_\n"
            f"Custom activities: *{custom}*  •  Total logged: *{total}*"
        )
    except Exception as e:
        logging.error(f"/workout error: {e}")
        ack(f"Error: {e}")


@bolt_app.command("/userstats")
def handle_mystats(ack, command):
    try:
        stats = database.get_user_stats(command["user_id"])
    except Exception as e:
        ack(f"DB error: {e}")
        return
    if not stats:
        ack("You haven't logged anything yet! React to today's post or use `/workout` to get started.")
        return

    stretch = stats.get("stretch", 0)
    workout = stats.get("workout", 0)
    custom = stats.get("custom", 0)
    total = sum(stats.values())
    ack(
        f"*Your activity stats (all time):*\n"
        f":person_in_lotus_position:  Stretch sessions: *{stretch}*\n"
        f":muscle:  Workouts: *{workout}*\n"
        f":running:  Custom activities: *{custom}*\n"
        f"─────────────────────\n"
        f"Total: *{total}* activities"
    )


@bolt_app.command("/teamstats")
def handle_teamstats(ack, command):
    weekly = database.get_weekly_stats()
    if not weekly:
        ack("No activity logged in the past 7 days yet. Be the first!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*Team activity — last 7 days:*\n"]
    for i, (user_id, count) in enumerate(weekly):
        medal = medals[i] if i < 3 else "▪️"
        lines.append(f"{medal} <@{user_id}>: *{count}* {'activity' if count == 1 else 'activities'}")
    ack("\n".join(lines))


def _build_leaderboard_text(title, rows):
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


@bolt_app.command("/weeklyleaderboard")
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


@bolt_app.command("/leaderboard")
def handle_alltime_leaderboard(ack, respond):
    ack()
    rows = database.get_alltime_leaderboard()
    if not rows:
        respond({"text": "No activity logged yet. Be the first!", "response_type": "in_channel"})
        return
    respond(_build_leaderboard_text("All-Time Leaderboard", rows))


# ── Schedule Commands ──────────────────────────────────────────────────────────

def _parse_schedule_input(text):
    """Returns (target_date, title, description) from command text."""
    target_date = str(date.today())
    if text.lower().startswith("tomorrow "):
        text = text[9:].strip()
        target_date = str(date.today() + timedelta(days=1))
    if "|" in text:
        title, description = [p.strip() for p in text.split("|", 1)]
    else:
        title, description = text.strip(), ""
    return target_date, title, description


@bolt_app.command("/setstretch")
def handle_set_stretch(ack, command, respond):
    ack()
    text = command["text"].strip()
    if not text:
        respond("Usage: `/setstretch Title | Description`\nAdd `tomorrow` at the start to set the next day.")
        return
    target_date, title, description = _parse_schedule_input(text)
    database.set_scheduled_option(target_date, "stretch", title, description)
    respond(f":white_check_mark: Stretch set for *{target_date}*: *{title}*")


@bolt_app.command("/setexercise")
def handle_set_exercise(ack, command, respond):
    ack()
    text = command["text"].strip()
    if not text:
        respond("Usage: `/setexercise Title | Description`\nAdd `tomorrow` at the start to set the next day.")
        return
    target_date, title, description = _parse_schedule_input(text)
    database.set_scheduled_option(target_date, "workout", title, description)
    respond(f":white_check_mark: Workout set for *{target_date}*: *{title}*")


@bolt_app.command("/setcustom")
def handle_set_custom(ack, command, respond):
    ack()
    try:
        text = command["text"].strip()
        if not text:
            respond("Usage: `/setcustom Title | Description`\nAdd `tomorrow` at the start to set the next day.")
            return
        target_date, title, description = _parse_schedule_input(text)
        database.set_scheduled_option(target_date, "custom", title, description)
        respond(f":white_check_mark: Custom suggestion set for *{target_date}*: *{title}*")
    except Exception as e:
        respond(f"Error: {e}")


@bolt_app.command("/setheader")
def handle_set_header(ack, command, respond):
    ack()
    try:
        text = command["text"].strip()
        if not text:
            respond("Usage: `/setheader Your header text here`")
            return
        database.set_setting("header", text)
        respond(f":white_check_mark: Header updated to: *{text}*")
    except Exception as e:
        respond(f"Error: {e}")


@bolt_app.command("/postdaily")
def handle_post_daily(ack, respond):
    ack()
    try:
        post_daily_message(force=True)
        respond(":white_check_mark: Daily workout posted!")
    except Exception as e:
        logging.error(f"/postdaily error: {e}")
        respond(f"Error: {e}")


@bolt_app.command("/setreminder")
def handle_set_reminder(ack, command, respond):
    ack()
    try:
        text = command["text"].strip()
        if not text:
            respond("Usage: `/setreminder 9:00am ET`  or  `/setreminder 14:30 America/Chicago`\nTimezone is optional — defaults to the bot's timezone if omitted.")
            return
        default_tz = os.environ.get("TIMEZONE", "America/New_York")
        time_str, tz = parse_reminder_input(text, default_tz)
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
    except Exception as e:
        logging.error(f"/setreminder error: {e}")
        respond(f"Error: {e}")


@bolt_app.command("/cancelreminder")
def handle_cancel_reminder(ack, command, respond):
    ack()
    try:
        user_id = command["user_id"]
        existing = database.get_user_reminder(user_id)
        if not existing:
            respond("You don't have a reminder set. Use `/setreminder 9:00am` to set one.")
            return
        database.delete_user_reminder(user_id)
        respond(":white_check_mark: Your daily reminder has been cancelled.")
    except Exception as e:
        logging.error(f"/cancelreminder error: {e}")
        respond(f"Error: {e}")


# ── Route ──────────────────────────────────────────────────────────────────────

@flask_app.route("/api/slack", methods=["POST"])
@flask_app.route("/", methods=["POST"])
def slack_events():
    try:
        return slack_handler.handle(request)
    except Exception as e:
        logging.error(f"Unhandled error: {e}", exc_info=True)
        return str(e), 500


app = flask_app
