import sqlite3
from datetime import date, timedelta

DB_PATH = "workouts.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            message_ts TEXT,
            channel_id TEXT,
            stretch_option TEXT,
            workout_option TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            date TEXT,
            activity_type TEXT,
            description TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_daily_post(date_str, message_ts, channel_id, stretch_option, workout_option):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO daily_posts (date, message_ts, channel_id, stretch_option, workout_option) VALUES (?, ?, ?, ?, ?)",
        (date_str, message_ts, channel_id, stretch_option, workout_option),
    )
    conn.commit()
    conn.close()


def get_today_post():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM daily_posts WHERE date = ?", (str(date.today()),))
    row = c.fetchone()
    conn.close()
    return row


def get_post_by_ts(message_ts):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM daily_posts WHERE message_ts = ?", (message_ts,))
    row = c.fetchone()
    conn.close()
    return row


def log_activity(user_id, activity_type, description):
    today = str(date.today())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if activity_type != "custom":
        c.execute(
            "SELECT id FROM activity_logs WHERE user_id = ? AND date = ? AND activity_type = ?",
            (user_id, today, activity_type),
        )
        if c.fetchone():
            conn.close()
            return False
    c.execute(
        "INSERT INTO activity_logs (user_id, date, activity_type, description) VALUES (?, ?, ?, ?)",
        (user_id, today, activity_type, description),
    )
    conn.commit()
    conn.close()
    return True


def remove_activity(user_id, activity_type):
    today = str(date.today())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM activity_logs WHERE user_id = ? AND date = ? AND activity_type = ? AND id = (SELECT id FROM activity_logs WHERE user_id = ? AND date = ? AND activity_type = ? ORDER BY logged_at DESC LIMIT 1)",
        (user_id, today, activity_type, user_id, today, activity_type),
    )
    conn.commit()
    conn.close()


def get_user_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT activity_type, COUNT(*) FROM activity_logs WHERE user_id = ? GROUP BY activity_type",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def get_weekly_stats():
    week_ago = str(date.today() - timedelta(days=7))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, COUNT(*) as total FROM activity_logs WHERE date >= ? GROUP BY user_id ORDER BY total DESC",
        (week_ago,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_weekly_leaderboard():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            user_id,
            SUM(CASE WHEN activity_type IN ('stretch', 'workout') THEN 1 ELSE 0 END) AS reacts,
            SUM(CASE WHEN activity_type = 'custom' THEN 1 ELSE 0 END) AS custom
        FROM activity_logs
        WHERE date >= ?
        GROUP BY user_id
        ORDER BY (reacts + custom) DESC
        """,
        (str(monday),),
    )
    rows = c.fetchall()
    conn.close()
    return rows, monday


def get_weekly_custom_descriptions(user_id, since_date):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT description FROM activity_logs WHERE user_id = ? AND activity_type = 'custom' AND date >= ? ORDER BY logged_at",
        (user_id, str(since_date)),
    )
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_alltime_leaderboard():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT
            user_id,
            SUM(CASE WHEN activity_type IN ('stretch', 'workout') THEN 1 ELSE 0 END) AS reacts,
            SUM(CASE WHEN activity_type = 'custom' THEN 1 ELSE 0 END) AS custom
        FROM activity_logs
        GROUP BY user_id
        ORDER BY (reacts + custom) DESC
        """
    )
    rows = c.fetchall()
    conn.close()
    return rows
