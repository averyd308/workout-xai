import os
import json
from datetime import date, timedelta

from supabase import create_client

_DEFAULT_TEMPLATES = [
    {
        "id": "push-day",
        "name": "Push Day",
        "exercises": [
            {"name": "Warm-up Jumping Jacks", "duration_seconds": 60, "rest_seconds": 15, "description": "Jump with arms and legs out simultaneously", "video_url": ""},
            {"name": "Push-ups", "duration_seconds": 45, "rest_seconds": 15, "description": "Lower chest to floor, push back up. Modify by dropping to knees.", "video_url": "https://www.youtube.com/watch?v=IODxDxX7oi4"},
            {"name": "Pike Push-ups", "duration_seconds": 45, "rest_seconds": 15, "description": "Hips high in inverted V shape, lower head toward floor.", "video_url": ""},
            {"name": "Tricep Dips", "duration_seconds": 45, "rest_seconds": 15, "description": "Use a chair behind you, lower by bending elbows, push back up.", "video_url": ""},
            {"name": "Diamond Push-ups", "duration_seconds": 45, "rest_seconds": 15, "description": "Hands form a diamond shape below chest.", "video_url": ""},
            {"name": "Cool-down Stretch", "duration_seconds": 60, "rest_seconds": 0, "description": "Gentle chest opener, shoulder cross-body stretch, wrist circles.", "video_url": ""},
        ],
    },
    {
        "id": "core-blast",
        "name": "Core Blast",
        "exercises": [
            {"name": "Warm-up March", "duration_seconds": 60, "rest_seconds": 15, "description": "March in place with high knees to get blood flowing.", "video_url": ""},
            {"name": "Plank Hold", "duration_seconds": 45, "rest_seconds": 15, "description": "Straight line from head to heels. Squeeze glutes and core.", "video_url": ""},
            {"name": "Crunches", "duration_seconds": 45, "rest_seconds": 15, "description": "Feet flat on floor, curl shoulders toward knees. Exhale on the way up.", "video_url": ""},
            {"name": "Leg Raises", "duration_seconds": 45, "rest_seconds": 15, "description": "Lie flat, raise straight legs to 90 degrees, lower slowly.", "video_url": ""},
            {"name": "Russian Twists", "duration_seconds": 45, "rest_seconds": 15, "description": "Sit at 45 degrees, feet off floor, twist torso side to side.", "video_url": ""},
            {"name": "Mountain Climbers", "duration_seconds": 45, "rest_seconds": 15, "description": "Plank position, drive knees alternately to chest. Keep hips level.", "video_url": ""},
            {"name": "Cool-down Stretch", "duration_seconds": 60, "rest_seconds": 0, "description": "Seated forward fold, child pose, lying twist.", "video_url": ""},
        ],
    },
    {
        "id": "full-body",
        "name": "Full Body",
        "exercises": [
            {"name": "Jumping Jacks", "duration_seconds": 45, "rest_seconds": 15, "description": "Classic cardio warm-up. Arms and legs out simultaneously.", "video_url": ""},
            {"name": "Squats", "duration_seconds": 45, "rest_seconds": 15, "description": "Feet shoulder-width, lower until thighs are parallel to floor. Chest up.", "video_url": ""},
            {"name": "Push-ups", "duration_seconds": 45, "rest_seconds": 15, "description": "Lower chest to floor, push back up. Modify by dropping to knees.", "video_url": "https://www.youtube.com/watch?v=IODxDxX7oi4"},
            {"name": "Reverse Lunges", "duration_seconds": 45, "rest_seconds": 15, "description": "Step back, lower back knee toward floor. Alternate legs.", "video_url": ""},
            {"name": "Plank Hold", "duration_seconds": 45, "rest_seconds": 15, "description": "Hold a straight line from head to heels.", "video_url": ""},
            {"name": "Burpees", "duration_seconds": 30, "rest_seconds": 20, "description": "Drop to push-up position, jump feet to hands, jump up with arms raised.", "video_url": ""},
            {"name": "Cool-down Stretch", "duration_seconds": 60, "rest_seconds": 0, "description": "Standing quad stretch, hamstring stretch, shoulder rolls.", "video_url": ""},
        ],
    },
]


_client = None

def get_client():
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


def init_db():
    # Tables are created in Supabase SQL editor — this is a no-op
    pass


def save_daily_post(date_str, message_ts, channel_id, stretch_option, workout_option):
    get_client().table("daily_posts").upsert({
        "date": date_str,
        "message_ts": message_ts,
        "channel_id": channel_id,
        "stretch_option": stretch_option,
        "workout_option": workout_option,
    }, on_conflict="date").execute()


def get_today_post(channel_id=None):
    query = get_client().table("daily_posts").select("*").eq("date", str(date.today()))
    if channel_id:
        query = query.eq("channel_id", channel_id)
    result = query.execute()
    return result.data[0] if result.data else None


def get_post_by_ts(message_ts):
    result = get_client().table("daily_posts").select("*").eq("message_ts", message_ts).execute()
    return result.data[0] if result.data else None


def log_activity(user_id, activity_type, description):
    today = str(date.today())
    client = get_client()
    if activity_type == "live":
        # Deduplicate per session (description holds the session ID), not per day
        existing = client.table("activity_logs").select("id").eq("user_id", user_id).eq("activity_type", "live").eq("description", description).execute()
        if existing.data:
            return False
    elif activity_type != "custom":
        existing = client.table("activity_logs").select("id").eq("user_id", user_id).eq("date", today).eq("activity_type", activity_type).execute()
        if existing.data:
            return False
    client.table("activity_logs").insert({
        "user_id": user_id,
        "date": today,
        "activity_type": activity_type,
        "description": description,
    }).execute()
    return True


def remove_activity(user_id, activity_type, description=None):
    today = str(date.today())
    client = get_client()
    query = client.table("activity_logs").select("id").eq("user_id", user_id).eq("activity_type", activity_type)
    if description:
        query = query.eq("description", description)
    else:
        query = query.eq("date", today)
    existing = query.order("logged_at", desc=True).limit(1).execute()
    if existing.data:
        client.table("activity_logs").delete().eq("id", existing.data[0]["id"]).execute()


def get_user_stats(user_id):
    result = get_client().table("activity_logs").select("activity_type").eq("user_id", user_id).execute()
    stats = {}
    for row in result.data:
        t = row["activity_type"]
        stats[t] = stats.get(t, 0) + 1
    return stats


def get_custom_activity_logs(user_id):
    """Return list of (description, date_str) for all custom activities, newest first."""
    result = get_client().table("activity_logs").select("description,date").eq("user_id", user_id).eq("activity_type", "custom").order("date", desc=True).execute()
    return [(row["description"], row["date"]) for row in result.data]


def get_weekly_stats():
    week_ago = str(date.today() - timedelta(days=7))
    result = get_client().table("activity_logs").select("user_id").gte("date", week_ago).execute()
    counts = {}
    for row in result.data:
        uid = row["user_id"]
        counts[uid] = counts.get(uid, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)


def get_weekly_leaderboard():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    result = get_client().table("activity_logs").select("user_id,activity_type").gte("date", str(monday)).execute()
    stats = {}
    for row in result.data:
        uid = row["user_id"]
        if uid not in stats:
            stats[uid] = {"stretch": 0, "workout": 0, "custom": 0, "live": 0}
        t = row["activity_type"]
        if t in stats[uid]:
            stats[uid][t] += 1
    rows = sorted([(uid, s["stretch"], s["workout"], s["custom"], s["live"]) for uid, s in stats.items()], key=lambda x: x[1] + x[2] + x[3] + x[4], reverse=True)
    return rows, monday


def get_weekly_custom_logs(user_id, since_date):
    """Return list of (description, date_str) for custom activities since since_date."""
    result = get_client().table("activity_logs").select("description,date").eq("user_id", user_id).eq("activity_type", "custom").gte("date", str(since_date)).order("date").execute()
    return [(r["description"], r["date"]) for r in result.data]


def get_alltime_leaderboard():
    result = get_client().table("activity_logs").select("user_id,activity_type").execute()
    stats = {}
    for row in result.data:
        uid = row["user_id"]
        if uid not in stats:
            stats[uid] = {"stretch": 0, "workout": 0, "custom": 0, "live": 0}
        t = row["activity_type"]
        if t in stats[uid]:
            stats[uid][t] += 1
    return sorted([(uid, s["stretch"], s["workout"], s["custom"], s["live"]) for uid, s in stats.items()], key=lambda x: x[1] + x[2] + x[3] + x[4], reverse=True)


def get_setting(key, default=None):
    result = get_client().table("settings").select("value").eq("key", key).execute()
    return result.data[0]["value"] if result.data else default


def set_setting(key, value):
    client = get_client()
    existing = client.table("settings").select("key").eq("key", key).execute()
    if existing.data:
        client.table("settings").update({"value": value}).eq("key", key).execute()
    else:
        client.table("settings").insert({"key": key, "value": value}).execute()


def set_scheduled_option(date_str, option_type, title, description):
    client = get_client()
    if option_type == "stretch":
        update_data = {"stretch_title": title, "stretch_description": description}
    elif option_type == "workout":
        update_data = {"workout_title": title, "workout_description": description}
    else:
        update_data = {"custom_title": title, "custom_description": description}
    existing = client.table("scheduled_options").select("date").eq("date", date_str).execute()
    if existing.data:
        client.table("scheduled_options").update(update_data).eq("date", date_str).execute()
    else:
        client.table("scheduled_options").insert({"date": date_str, **update_data}).execute()


def get_scheduled_options(date_str):
    result = get_client().table("scheduled_options").select("stretch_title,stretch_description,workout_title,workout_description,custom_title,custom_description").eq("date", date_str).execute()
    if result.data:
        r = result.data[0]
        return (r.get("stretch_title"), r.get("stretch_description"), r.get("workout_title"), r.get("workout_description"), r.get("custom_title"), r.get("custom_description"))
    return None


# ── Strava Tokens ─────────────────────────────────────────────────────────────

def save_strava_tokens(slack_user_id, athlete_id, access_token, refresh_token, expires_at):
    client = get_client()
    data = {
        "slack_user_id": slack_user_id,
        "strava_athlete_id": athlete_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }
    existing = client.table("strava_tokens").select("slack_user_id").eq("slack_user_id", slack_user_id).execute()
    if existing.data:
        client.table("strava_tokens").update(data).eq("slack_user_id", slack_user_id).execute()
    else:
        client.table("strava_tokens").insert(data).execute()


def get_strava_tokens_by_slack_user(slack_user_id):
    result = get_client().table("strava_tokens").select("*").eq("slack_user_id", slack_user_id).execute()
    return result.data[0] if result.data else None


def get_strava_tokens_by_athlete(athlete_id):
    result = get_client().table("strava_tokens").select("*").eq("strava_athlete_id", athlete_id).execute()
    return result.data[0] if result.data else None


def delete_strava_tokens(slack_user_id):
    get_client().table("strava_tokens").delete().eq("slack_user_id", slack_user_id).execute()


# ── User Reminders ────────────────────────────────────────────────────────────

def set_user_reminder(user_id, reminder_time, timezone):
    """Store a personal reminder time (HH:MM, 24h) and IANA timezone for a user."""
    client = get_client()
    existing = client.table("user_reminders").select("user_id").eq("user_id", user_id).execute()
    if existing.data:
        client.table("user_reminders").update({"reminder_time": reminder_time, "timezone": timezone}).eq("user_id", user_id).execute()
    else:
        client.table("user_reminders").insert({"user_id": user_id, "reminder_time": reminder_time, "timezone": timezone}).execute()


def get_user_reminder(user_id):
    """Return (reminder_time, timezone) for a user, or None."""
    result = get_client().table("user_reminders").select("reminder_time,timezone").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]["reminder_time"], result.data[0]["timezone"]
    return None


def delete_user_reminder(user_id):
    """Remove a user's personal reminder."""
    get_client().table("user_reminders").delete().eq("user_id", user_id).execute()


def get_distinct_reminder_timezones():
    """Return list of unique IANA timezone strings stored in user_reminders."""
    result = get_client().table("user_reminders").select("timezone").execute()
    return list(set(row["timezone"] for row in result.data if row.get("timezone")))


def get_reminders_for_time(time_str, timezone):
    """Return list of user_ids whose reminder_time and timezone match."""
    result = get_client().table("user_reminders").select("user_id").eq("reminder_time", time_str).eq("timezone", timezone).execute()
    return [row["user_id"] for row in result.data]


# ── Workout Templates & Sessions ──────────────────────────────────────────────

def get_workout_templates():
    result = get_client().table("workout_templates").select("*").execute()
    return result.data


def get_workout_template(template_id):
    result = get_client().table("workout_templates").select("*").eq("id", template_id).execute()
    return result.data[0] if result.data else None


def get_workout_template_by_name(name):
    """Case-insensitive exact match on name."""
    result = get_client().table("workout_templates").select("*").ilike("name", name).execute()
    return result.data[0] if result.data else None


def seed_workout_templates():
    """Insert default templates if the table is empty."""
    client = get_client()
    existing = client.table("workout_templates").select("id").execute()
    existing_ids = {r["id"] for r in existing.data}
    for t in _DEFAULT_TEMPLATES:
        if t["id"] not in existing_ids:
            client.table("workout_templates").insert({
                "id": t["id"],
                "name": t["name"],
                "exercises": t["exercises"],
            }).execute()


def create_workout_session(session_id, template_id, host_slack_user_id, host_token, channel_id, youtube_url=None, message_ts=None):
    data = {
        "id": session_id,
        "host_slack_user_id": host_slack_user_id,
        "host_token": host_token,
        "status": "waiting",
        "current_exercise_index": 0,
        "paused_elapsed": 0,
        "channel_id": channel_id,
    }
    if template_id is not None:
        data["template_id"] = template_id
    if youtube_url is not None:
        data["youtube_url"] = youtube_url
    if message_ts is not None:
        data["message_ts"] = message_ts
    get_client().table("workout_sessions").insert(data).execute()


def get_workout_session_by_ts(message_ts):
    result = get_client().table("workout_sessions").select("*").eq("message_ts", message_ts).execute()
    return result.data[0] if result.data else None


def get_active_session_for_channel(channel_id):
    """Return the most recent non-finished session for a channel, or None."""
    result = (
        get_client()
        .table("workout_sessions")
        .select("*")
        .eq("channel_id", channel_id)
        .neq("status", "finished")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def finish_old_sessions_for_channel(channel_id, except_session_id):
    """Mark all non-finished sessions for a channel as finished, except the given one."""
    get_client().table("workout_sessions").update({"status": "finished"}).eq("channel_id", channel_id).neq("status", "finished").neq("id", except_session_id).execute()


def get_workout_session(session_id):
    result = get_client().table("workout_sessions").select("*").eq("id", session_id).execute()
    return result.data[0] if result.data else None


def update_workout_session(session_id, data):
    get_client().table("workout_sessions").update(data).eq("id", session_id).execute()


def add_session_participant(session_id, display_name):
    client = get_client()
    existing = client.table("session_participants").select("id").eq("session_id", session_id).eq("display_name", display_name).execute()
    if existing.data:
        return
    client.table("session_participants").insert({
        "session_id": session_id,
        "display_name": display_name,
    }).execute()


def get_session_participants(session_id):
    result = get_client().table("session_participants").select("*").eq("session_id", session_id).order("joined_at").execute()
    return result.data


def mark_participant_ready(session_id, display_name):
    get_client().table("session_participants").update({"is_ready": True}).eq("session_id", session_id).eq("display_name", display_name).execute()


def add_session_message(session_id, display_name, message):
    get_client().table("session_messages").insert({
        "session_id": session_id,
        "display_name": display_name,
        "message": message,
    }).execute()


def get_session_messages(session_id, limit=100):
    try:
        result = get_client().table("session_messages").select("display_name,message,created_at").eq("session_id", session_id).order("created_at").limit(limit).execute()
        return result.data
    except Exception:
        return []
