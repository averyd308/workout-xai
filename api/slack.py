import sys
import os
import logging
import secrets
import urllib.parse
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request
from slack_bolt.adapter.flask import SlackRequestHandler

import re
import time as _time

import database
from bot import bolt_app, CHANNEL_ID, CHANNEL_IDS, STRETCH_EMOJI, WORKOUT_EMOJI, CUSTOM_EMOJI, GYM_EMOJIS, OTHER_ACTIVITY_EMOJIS, post_daily_message, parse_reminder_input, get_bot_user_id

LIVE_EMOJI = "tv"

_YOUTUBE_RE = re.compile(
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?[^\s]*v=|youtu\.be/)([a-zA-Z0-9_-]{11})'
)

def _extract_youtube_id(text):
    m = _YOUTUBE_RE.search(text)
    return m.group(1) if m else None

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

    user_id = event["user"]
    if user_id == get_bot_user_id():
        return

    post = database.get_post_by_ts(event["item"]["ts"])
    emoji = event["reaction"]

    if not post:
        if emoji == LIVE_EMOJI:
            session = database.get_workout_session_by_ts(event["item"]["ts"])
            if session:
                ch = session["channel_id"]
                logged = database.log_activity(user_id, "live", f"Live workout ({session['id']})", channel_id=ch)
                if logged:
                    stats = database.get_user_stats(user_id, channel_id=ch)
                    count = stats.get("live", 0)
                    bolt_app.client.chat_postEphemeral(
                        channel=ch,
                        user=user_id,
                        text=f":tv: Logged! You've joined *{count}* live workout{'s' if count != 1 else ''} in this channel.",
                    )
        return

    post_channel = post.get("channel_id") or CHANNEL_ID
    stretch_title = post["stretch_option"]
    workout_title = post["workout_option"]

    if emoji == STRETCH_EMOJI:
        logged = database.log_activity(user_id, "stretch", stretch_title, channel_id=post_channel)
        if logged:
            stats = database.get_user_stats(user_id, channel_id=post_channel)
            count = stats.get("stretch", 0)
            bolt_app.client.chat_postEphemeral(
                channel=post_channel,
                user=user_id,
                text=f":person_in_lotus_position: Nice stretch! You've logged *{count}* stretching session{'s' if count != 1 else ''} in this channel.",
            )

    elif emoji == WORKOUT_EMOJI:
        logged = database.log_activity(user_id, "workout", workout_title, channel_id=post_channel)
        if logged:
            stats = database.get_user_stats(user_id, channel_id=post_channel)
            count = stats.get("workout", 0)
            bolt_app.client.chat_postEphemeral(
                channel=post_channel,
                user=user_id,
                text=f":muscle: Great workout! You've logged *{count}* workout{'s' if count != 1 else ''} in this channel.",
            )

    elif emoji == CUSTOM_EMOJI:
        scheduled = database.get_scheduled_options(post["date"])
        custom_title = scheduled[4] if scheduled and scheduled[4] else None
        if custom_title:
            logged = database.log_activity(user_id, "custom", "", channel_id=post_channel)
            if logged:
                from datetime import datetime as dt
                d = dt.strptime(post["date"], "%Y-%m-%d")
                date_display = f"{d.strftime('%b')} {d.day}"
                stats = database.get_user_stats(user_id, channel_id=post_channel)
                count = stats.get("custom", 0)
                bolt_app.client.chat_postEphemeral(
                    channel=post_channel,
                    user=user_id,
                    text=f":runner: Logged! You did the custom workout on *{date_display}*. That's *{count}* custom {'activity' if count == 1 else 'activities'} in this channel.",
                )

    elif emoji in GYM_EMOJIS:
        logged = database.log_activity(user_id, "gym", "Gym workout", channel_id=post_channel)
        if logged:
            stats = database.get_user_stats(user_id, channel_id=post_channel)
            count = stats.get("gym", 0)
            bolt_app.client.chat_postEphemeral(
                channel=post_channel,
                user=user_id,
                text=f":man-lifting-weights: Gym session logged! You've hit the gym *{count}* {'time' if count == 1 else 'times'} in this channel.",
            )

    elif emoji in OTHER_ACTIVITY_EMOJIS or emoji.startswith("muscle::"):
        logged = database.log_activity(user_id, "other", f":{emoji}:", channel_id=post_channel)
        if logged:
            stats = database.get_user_stats(user_id, channel_id=post_channel)
            count = stats.get("other", 0)
            bolt_app.client.chat_postEphemeral(
                channel=post_channel,
                user=user_id,
                text=f":{emoji}: Activity logged! You've logged *{count}* other {'activity' if count == 1 else 'activities'} in this channel.",
            )


@bolt_app.event("reaction_removed")
def handle_reaction_removed(event):
    if event["item"]["type"] != "message":
        return

    post = database.get_post_by_ts(event["item"]["ts"])
    user_id = event["user"]
    emoji = event["reaction"]

    if not post:
        if emoji == LIVE_EMOJI:
            session = database.get_workout_session_by_ts(event["item"]["ts"])
            if session:
                database.remove_activity(user_id, "live", description=f"Live workout ({session['id']})")
        return

    if emoji == STRETCH_EMOJI:
        database.remove_activity(user_id, "stretch")
    elif emoji == WORKOUT_EMOJI:
        database.remove_activity(user_id, "workout")
    elif emoji == CUSTOM_EMOJI:
        database.remove_activity(user_id, "custom")
    elif emoji in GYM_EMOJIS:
        database.remove_activity(user_id, "gym")
    elif emoji in OTHER_ACTIVITY_EMOJIS or emoji.startswith("muscle::"):
        database.remove_activity(user_id, "other", description=f":{emoji}:")


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
        channel_id = command.get("channel_id")
        database.log_activity(user_id, "custom", description, channel_id=channel_id)
        stats = database.get_user_stats(user_id, channel_id=channel_id)
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
        channel_id = command.get("channel_id") or CHANNEL_ID
        stats = database.get_user_stats(command["user_id"], channel_id=channel_id)
    except Exception as e:
        ack(f"DB error: {e}")
        return
    if not stats:
        ack("You haven't logged anything yet in this channel! React to today's post or use `/workout` to get started.")
        return

    stretch = stats.get("stretch", 0)
    workout = stats.get("workout", 0)
    gym = stats.get("gym", 0)
    custom = stats.get("custom", 0)
    live = stats.get("live", 0)
    total = sum(stats.values())
    lines = [
        "*Your activity stats (this channel):*",
        f":person_in_lotus_position:  Stretch sessions: *{stretch}*",
        f":muscle:  Workouts: *{workout}*",
        f":man-lifting-weights:  Gym sessions: *{gym}*",
        f":tv:  Live workouts: *{live}*",
        f":runner:  Custom activities: *{custom}*",
        "─────────────────────",
        f"Total: *{total}* activities",
    ]
    ack("\n".join(lines))


@bolt_app.command("/teamstats")
def handle_teamstats(ack, command):
    channel_id = command.get("channel_id")
    weekly = [(uid, c) for uid, c in database.get_weekly_stats(channel_id=channel_id) if uid != get_bot_user_id()]
    if not weekly:
        ack("No activity logged in the past 7 days yet. Be the first!")
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = ["*Team activity — last 7 days:*\n"]
    for i, (user_id, count) in enumerate(weekly):
        medal = medals[i] if i < 3 else "▪️"
        lines.append(f"{medal} <@{user_id}>: *{count}* {'activity' if count == 1 else 'activities'}")
    ack("\n".join(lines))


def _filter_bot_rows(rows):
    bot_id = get_bot_user_id()
    if bot_id:
        return [r for r in rows if r[0] != bot_id]
    return rows


def _build_leaderboard_text(title, rows):
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (user_id, stretches, workouts, gym, custom, live, other) in enumerate(rows):
        other_total = sum(other.values()) if isinstance(other, dict) else other
        total = stretches + workouts + gym + custom + live + other_total
        medal = medals[i] if i < 3 else f"{i + 1}."
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
        lines.append(f"{medal} <@{user_id}>: *{total}* total  ›  {detail}")
    return {"text": f"*{title}*\n\n" + "\n".join(lines), "response_type": "in_channel"}


@bolt_app.command("/pg-weeklyleaderboard")
def handle_weekly_leaderboard(ack, command, respond):
    ack()
    channel_id = command.get("channel_id")
    rows, sunday, saturday = database.get_weekly_leaderboard(channel_id=channel_id)
    rows = _filter_bot_rows(rows)
    if not rows:
        respond({"text": f"No activity logged this week yet ({sunday.strftime('%b %d')} – {saturday.strftime('%b %d')}). Be the first!", "response_type": "in_channel"})
        return

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    title = f"*Weekly Leaderboard  •  {sunday.strftime('%b %d')} – {saturday.strftime('%b %d')}*"
    lines = [title, ""]
    for i, (user_id, stretches, workouts, gym, custom, live, other) in enumerate(rows[:5]):
        other_total = sum(other.values()) if isinstance(other, dict) else other
        total = stretches + workouts + gym + custom + live + other_total
        medal = medals[i]
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
        lines.append(f"{medal} <@{user_id}>: *{total}* total  ›  {detail}")
    respond({"text": "\n".join(lines), "response_type": "in_channel"})


@bolt_app.command("/pg-leaderboard")
def handle_alltime_leaderboard(ack, command, respond):
    ack()
    channel_id = command.get("channel_id")
    rows = _filter_bot_rows(database.get_alltime_leaderboard(channel_id=channel_id))
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
def handle_post_daily(ack, command, respond):
    ack()
    try:
        post_daily_message(channel_id=command.get("channel_id"), force=True)
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


# ── Group Workout Commands ─────────────────────────────────────────────────────

def _start_workout_modal_view():
    return {
        "type": "modal",
        "callback_id": "start_workout_modal",
        "title": {"type": "plain_text", "text": "Start Live Workout"},
        "submit": {"type": "plain_text", "text": "Start Session"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Paste the YouTube video everyone will follow along to. The join link will be posted to the channel and you'll get the host link via DM.",
                },
            },
            {
                "type": "input",
                "block_id": "youtube_block",
                "label": {"type": "plain_text", "text": "YouTube URL"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "youtube_url",
                    "placeholder": {"type": "plain_text", "text": "https://youtube.com/watch?v=..."},
                },
            },
        ],
    }


def _start_live_session(user_id, client, youtube_url=None, channel_id=None):
    """Create a live video session, post to channel, and send host an ephemeral."""
    session_id = secrets.token_urlsafe(8)
    host_token = secrets.token_urlsafe(16)
    base_url = os.environ.get("APP_URL", "https://workout-xai.vercel.app")
    join_url = f"{base_url}/workout?id={session_id}"
    host_url = f"{base_url}/workout?id={session_id}&host_token={host_token}"
    post_channel = channel_id or CHANNEL_ID

    msg = client.chat_postMessage(
        channel=post_channel,
        text=f":tv: <@{user_id}> started a group video workout! Join here: {join_url}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":tv: *<@{user_id}> is starting a group video workout!*\n"
                        f"Everyone will watch and follow along in sync.\n\n"
                        f"<{join_url}|:arrow_right:  Click here to join the live session>\n\n"
                        f"_React with :tv: after the workout to log your participation!_"
                    ),
                },
            }
        ],
    )
    database.create_workout_session(session_id, None, user_id, host_token, post_channel, youtube_url=youtube_url, message_ts=msg["ts"])
    database.finish_old_sessions_for_channel(post_channel, session_id)

    try:
        client.reactions_add(channel=post_channel, timestamp=msg["ts"], name=LIVE_EMOJI)
    except Exception as e:
        logging.warning(f"Failed to add reaction {LIVE_EMOJI}: {e}")

    dm_note = "Press *Start* when everyone is ready!" if youtube_url else "Set the video with `/setvideo [YouTube URL]`, then press *Start*."
    try:
        client.chat_postEphemeral(
            channel=post_channel,
            user=user_id,
            text=(
                f":crown: *Your host link (only you can see this):*\n{host_url}\n\n"
                f"_Keep this link private — it gives you host controls._\n\n"
                f"{dm_note}"
            ),
        )
    except Exception as e:
        logging.error(f"live session ephemeral error: {e}")


def _open_start_modal(client, trigger_id, channel_id=None):
    view = _start_workout_modal_view()
    view["private_metadata"] = channel_id or CHANNEL_ID
    client.views_open(trigger_id=trigger_id, view=view)


@bolt_app.command("/startliveyt")
def handle_start_video_session(ack, command, client):
    ack()
    _open_start_modal(client, command["trigger_id"], channel_id=command["channel_id"])


@bolt_app.shortcut("start_live_workout")
def handle_start_live_shortcut(ack, shortcut, client):
    ack()
    _open_start_modal(client, shortcut["trigger_id"])


@bolt_app.action("start_live_workout_btn")
def handle_start_workout_button(ack, body, client):
    ack()
    _open_start_modal(client, body["trigger_id"], channel_id=body.get("channel", {}).get("id"))


@bolt_app.view("start_workout_modal")
def handle_start_workout_modal(ack, view, body, client):
    raw = (view["state"]["values"]["youtube_block"]["youtube_url"]["value"] or "").strip()
    video_id = _extract_youtube_id(raw)
    if not video_id:
        ack(response_action="errors", errors={"youtube_block": "Please enter a valid YouTube URL (youtube.com/watch?v=... or youtu.be/...)"})
        return
    ack()
    try:
        channel_id = view.get("private_metadata") or CHANNEL_ID
        _start_live_session(body["user"]["id"], client, youtube_url=f"https://www.youtube.com/watch?v={video_id}", channel_id=channel_id)
    except Exception as e:
        logging.error(f"start_workout_modal error: {e}")


@bolt_app.command("/postworkoutbutton")
def handle_post_workout_button(ack, command, client, respond):
    ack()
    client.chat_postMessage(
        channel=command.get("channel_id") or CHANNEL_ID,
        text="Start a live workout session",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":tv: *Ready for a group workout?*\nClick below to start a live session — you'll pick the YouTube video and the join link will be posted here.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "▶  Start Live Workout"},
                        "style": "primary",
                        "action_id": "start_live_workout_btn",
                    }
                ],
            },
        ],
    )
    respond(":white_check_mark: Button posted!")


# ── Menu Button Handlers ───────────────────────────────────────────────────────

@bolt_app.action("menu_my_stats")
def handle_menu_my_stats(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id") or CHANNEL_ID
    try:
        stats = database.get_user_stats(user_id, channel_id=channel_id)
        if not stats:
            client.chat_postEphemeral(channel=channel_id, user=user_id,
                text="You haven't logged anything yet in this channel! React to today's post or use the Log Workout button.")
            return
        stretch = stats.get("stretch", 0)
        workout = stats.get("workout", 0)
        custom  = stats.get("custom", 0)
        live    = stats.get("live", 0)
        total   = sum(stats.values())
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=(
            "*Your activity stats (this channel):*\n"
            f":person_in_lotus_position:  Stretch sessions: *{stretch}*\n"
            f":muscle:  Workouts: *{workout}*\n"
            f":tv:  Live workouts: *{live}*\n"
            f":runner:  Custom activities: *{custom}*\n"
            "─────────────────────\n"
            f"Total: *{total}* activities"
        ))
    except Exception as e:
        logging.error(f"menu_my_stats error: {e}")


@bolt_app.action("menu_weekly_leaderboard")
def handle_menu_weekly_leaderboard(ack, body, client):
    ack()
    channel_id = body.get("channel", {}).get("id") or CHANNEL_ID
    try:
        rows, monday = database.get_weekly_leaderboard()
        rows = _filter_bot_rows(rows)
        if not rows:
            client.chat_postMessage(channel=channel_id, text="No activity logged this week yet. Be the first!")
            return
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        today = date.today()
        lines = [f"*Weekly Leaderboard  •  {monday.strftime('%b %d')} – {today.strftime('%b %d')}*", ""]
        for i, (uid, stretches, workouts, custom, live) in enumerate(rows[:5]):
            total = stretches + workouts + custom + live
            parts = []
            if stretches: parts.append(f":person_in_lotus_position: {stretches}")
            if workouts:  parts.append(f":muscle: {workouts}")
            if live:      parts.append(f":tv: {live}")
            if custom:    parts.append(f":runner: {custom}")
            lines.append(f"{medals[i]} <@{uid}>: *{total}* total  ›  {'  •  '.join(parts) or 'no activity'}")
        client.chat_postMessage(channel=channel_id, text="\n".join(lines))
    except Exception as e:
        logging.error(f"menu_weekly_leaderboard error: {e}")


@bolt_app.action("menu_alltime_leaderboard")
def handle_menu_alltime_leaderboard(ack, body, client):
    ack()
    channel_id = body.get("channel", {}).get("id") or CHANNEL_ID
    try:
        rows = _filter_bot_rows(database.get_alltime_leaderboard())
        if not rows:
            client.chat_postMessage(channel=channel_id, text="No activity logged yet. Be the first!")
            return
        result = _build_leaderboard_text("All-Time Leaderboard", rows)
        client.chat_postMessage(channel=channel_id, text=result["text"])
    except Exception as e:
        logging.error(f"menu_alltime_leaderboard error: {e}")


@bolt_app.action("menu_log_workout")
def handle_menu_log_workout(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "log_workout_modal",
            "title": {"type": "plain_text", "text": "Log Workout"},
            "submit": {"type": "plain_text", "text": "Log It"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [{
                "type": "input",
                "block_id": "workout_block",
                "label": {"type": "plain_text", "text": "What did you do?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "workout_description",
                    "placeholder": {"type": "plain_text", "text": "e.g. 30 min run, 20 min yoga…"},
                },
            }],
        },
    )


@bolt_app.view("log_workout_modal")
def handle_log_workout_modal(ack, view, body, client):
    description = (view["state"]["values"]["workout_block"]["workout_description"]["value"] or "").strip()
    if not description:
        ack(response_action="errors", errors={"workout_block": "Please describe your workout."})
        return
    ack()
    user_id = body["user"]["id"]
    try:
        database.log_activity(user_id, "custom", description)
        stats = database.get_user_stats(user_id)
        dm = client.conversations_open(users=user_id)
        client.chat_postMessage(channel=dm["channel"]["id"], text=(
            f":white_check_mark: Logged: _{description}_\n"
            f"Custom activities: *{stats.get('custom', 0)}*  •  Total logged: *{sum(stats.values())}*"
        ))
    except Exception as e:
        logging.error(f"log_workout_modal error: {e}")


@bolt_app.action("menu_connect_strava")
def handle_menu_connect_strava(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel_id = body.get("channel", {}).get("id") or CHANNEL_ID
    try:
        client_id = os.environ.get("STRAVA_CLIENT_ID", "")
        redirect_uri = urllib.parse.quote("https://workout-xai.vercel.app/api/strava/callback")
        auth_url = (
            f"https://www.strava.com/oauth/authorize?client_id={client_id}"
            f"&redirect_uri={redirect_uri}&response_type=code"
            f"&scope=activity:read_all&state={user_id}"
        )
        client.chat_postEphemeral(channel=channel_id, user=user_id,
            text=f":strava: <{auth_url}|Click here to connect your Strava account> — only you can see this link.")
    except Exception as e:
        logging.error(f"menu_connect_strava error: {e}")


@bolt_app.action("menu_set_reminder")
def handle_menu_set_reminder(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "set_reminder_modal",
            "title": {"type": "plain_text", "text": "Set Daily Reminder"},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Get a daily DM reminder to check the workout post."},
                },
                {
                    "type": "input",
                    "block_id": "reminder_block",
                    "label": {"type": "plain_text", "text": "Reminder Time"},
                    "hint": {"type": "plain_text", "text": "Examples: 9:00am ET  •  2:30pm PT  •  14:30 America/Chicago"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "reminder_time",
                        "placeholder": {"type": "plain_text", "text": "9:00am ET"},
                    },
                },
            ],
        },
    )


@bolt_app.view("set_reminder_modal")
def handle_set_reminder_modal(ack, view, body, client):
    text = (view["state"]["values"]["reminder_block"]["reminder_time"]["value"] or "").strip()
    default_tz = os.environ.get("TIMEZONE", "America/New_York")
    time_str, tz = parse_reminder_input(text, default_tz)
    if not time_str:
        ack(response_action="errors", errors={"reminder_block": "Couldn't parse that time. Try '9:00am ET' or '14:30 America/Chicago'."})
        return
    if not tz:
        ack(response_action="errors", errors={"reminder_block": "Couldn't recognise that timezone. Try ET, CT, MT, or PT."})
        return
    ack()
    user_id = body["user"]["id"]
    try:
        database.set_user_reminder(user_id, time_str, tz)
        h, m = int(time_str[:2]), int(time_str[3:])
        display = f"{h % 12 or 12}:{m:02d}{'am' if h < 12 else 'pm'}"
        dm = client.conversations_open(users=user_id)
        client.chat_postMessage(channel=dm["channel"]["id"],
            text=f":alarm_clock: Got it! I'll DM you a reminder at *{display} {tz}* each day.")
    except Exception as e:
        logging.error(f"set_reminder_modal error: {e}")


@bolt_app.command("/postmenu")
def handle_post_menu(ack, command, client, respond):
    ack()
    client.chat_postMessage(
        channel=command.get("channel_id") or CHANNEL_ID,
        text="Workout Menu",
        blocks=[
            {"type": "header", "text": {"type": "plain_text", "text": "🏋️  Periodic Gains Menu"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*📊  Stats & Leaderboards*"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "My Stats"},             "action_id": "menu_my_stats"},
                {"type": "button", "text": {"type": "plain_text", "text": "Weekly Leaderboard"},  "action_id": "menu_weekly_leaderboard"},
                {"type": "button", "text": {"type": "plain_text", "text": "All-Time Leaderboard"},"action_id": "menu_alltime_leaderboard"},
            ]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*📝  Log Activity*"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Log Workout"},   "action_id": "menu_log_workout"},
                {"type": "button", "text": {"type": "plain_text", "text": "Connect Strava"},"action_id": "menu_connect_strava"},
            ]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*⏰  Settings*"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Set Daily Reminder"}, "action_id": "menu_set_reminder"},
            ]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*📺  Live Workouts*"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "▶  Start Live Workout"}, "style": "primary", "action_id": "start_live_workout_btn"},
            ]},
        ],
    )
    respond(":white_check_mark: Menu posted! Pin that message so everyone can find it.")


@bolt_app.command("/setvideo")
def handle_set_video(ack, command, respond):
    ack()
    try:
        text = command["text"].strip()
        if not text:
            respond(
                "Usage: `/setvideo https://youtube.com/watch?v=...`\n"
                "Changes the video for the current active session and resets playback to the start."
            )
            return

        video_id = _extract_youtube_id(text)
        if not video_id:
            respond(":x: Please provide a valid YouTube URL (youtube.com/watch?v=... or youtu.be/...)")
            return

        session = database.get_active_session_for_channel(command.get("channel_id") or CHANNEL_ID)
        if not session:
            respond(":x: No active session found. Start one with `/startlive [YouTube URL]`.")
            return

        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        database.update_workout_session(session["id"], {
            "youtube_url": youtube_url,
            "status": "waiting",
            "exercise_start_time": None,
            "paused_elapsed": 0,
        })

        respond(f":white_check_mark: Video updated! Press *Start Video* in the session to begin.\n{youtube_url}")
    except Exception as e:
        logging.error(f"/setvideo error: {e}")
        respond(f"Error: {e}")


# ── Strava Commands ────────────────────────────────────────────────────────────

@bolt_app.command("/connectstrava")
def handle_connect_strava(ack, command):
    user_id = command["user_id"]
    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    redirect_uri = urllib.parse.quote("https://workout-xai.vercel.app/api/strava/callback")
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&state={user_id}"
    )
    ack(f":strava: <{auth_url}|Click here to connect your Strava account> — only you can see this link.")


@bolt_app.command("/disconnectstrava")
def handle_disconnect_strava(ack, command):
    user_id = command["user_id"]
    existing = database.get_strava_tokens_by_slack_user(user_id)
    if not existing:
        ack("You don't have a Strava account connected.")
        return
    database.delete_strava_tokens(user_id)
    ack(":white_check_mark: Your Strava account has been disconnected.")


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
