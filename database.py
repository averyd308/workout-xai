import os
from datetime import date, timedelta

from supabase import create_client


def get_client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


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
    }).execute()


def get_today_post():
    result = get_client().table("daily_posts").select("*").eq("date", str(date.today())).execute()
    return result.data[0] if result.data else None


def get_post_by_ts(message_ts):
    result = get_client().table("daily_posts").select("*").eq("message_ts", message_ts).execute()
    return result.data[0] if result.data else None


def log_activity(user_id, activity_type, description):
    today = str(date.today())
    client = get_client()
    if activity_type != "custom":
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


def remove_activity(user_id, activity_type):
    today = str(date.today())
    client = get_client()
    existing = client.table("activity_logs").select("id").eq("user_id", user_id).eq("date", today).eq("activity_type", activity_type).order("logged_at", desc=True).limit(1).execute()
    if existing.data:
        client.table("activity_logs").delete().eq("id", existing.data[0]["id"]).execute()


def get_user_stats(user_id):
    result = get_client().table("activity_logs").select("activity_type").eq("user_id", user_id).execute()
    stats = {}
    for row in result.data:
        t = row["activity_type"]
        stats[t] = stats.get(t, 0) + 1
    return stats


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
            stats[uid] = {"reacts": 0, "custom": 0}
        if row["activity_type"] in ("stretch", "workout"):
            stats[uid]["reacts"] += 1
        elif row["activity_type"] == "custom":
            stats[uid]["custom"] += 1
    rows = sorted([(uid, s["reacts"], s["custom"]) for uid, s in stats.items()], key=lambda x: x[1] + x[2], reverse=True)
    return rows, monday


def get_weekly_custom_descriptions(user_id, since_date):
    result = get_client().table("activity_logs").select("description").eq("user_id", user_id).eq("activity_type", "custom").gte("date", str(since_date)).order("logged_at").execute()
    return [r["description"] for r in result.data]


def get_alltime_leaderboard():
    result = get_client().table("activity_logs").select("user_id,activity_type").execute()
    stats = {}
    for row in result.data:
        uid = row["user_id"]
        if uid not in stats:
            stats[uid] = {"reacts": 0, "custom": 0}
        if row["activity_type"] in ("stretch", "workout"):
            stats[uid]["reacts"] += 1
        elif row["activity_type"] == "custom":
            stats[uid]["custom"] += 1
    return sorted([(uid, s["reacts"], s["custom"]) for uid, s in stats.items()], key=lambda x: x[1] + x[2], reverse=True)


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
    else:
        update_data = {"workout_title": title, "workout_description": description}
    existing = client.table("scheduled_options").select("date").eq("date", date_str).execute()
    if existing.data:
        client.table("scheduled_options").update(update_data).eq("date", date_str).execute()
    else:
        client.table("scheduled_options").insert({"date": date_str, **update_data}).execute()


def get_scheduled_options(date_str):
    result = get_client().table("scheduled_options").select("stretch_title,stretch_description,workout_title,workout_description").eq("date", date_str).execute()
    if result.data:
        r = result.data[0]
        return (r["stretch_title"], r["stretch_description"], r["workout_title"], r["workout_description"])
    return None
