import os
from contextlib import contextmanager
from datetime import date, timedelta

import psycopg2


@contextmanager
def get_conn():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_posts (
                id SERIAL PRIMARY KEY,
                date TEXT UNIQUE,
                message_ts TEXT,
                channel_id TEXT,
                stretch_option TEXT,
                workout_option TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                date TEXT,
                activity_type TEXT,
                description TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def save_daily_post(date_str, message_ts, channel_id, stretch_option, workout_option):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO daily_posts (date, message_ts, channel_id, stretch_option, workout_option)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (date) DO UPDATE SET
                message_ts = EXCLUDED.message_ts,
                channel_id = EXCLUDED.channel_id,
                stretch_option = EXCLUDED.stretch_option,
                workout_option = EXCLUDED.workout_option
            """,
            (date_str, message_ts, channel_id, stretch_option, workout_option),
        )


def get_today_post():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM daily_posts WHERE date = %s", (str(date.today()),))
        return c.fetchone()


def get_post_by_ts(message_ts):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM daily_posts WHERE message_ts = %s", (message_ts,))
        return c.fetchone()


def log_activity(user_id, activity_type, description):
    today = str(date.today())
    with get_conn() as conn:
        c = conn.cursor()
        if activity_type != "custom":
            c.execute(
                "SELECT id FROM activity_logs WHERE user_id = %s AND date = %s AND activity_type = %s",
                (user_id, today, activity_type),
            )
            if c.fetchone():
                return False
        c.execute(
            "INSERT INTO activity_logs (user_id, date, activity_type, description) VALUES (%s, %s, %s, %s)",
            (user_id, today, activity_type, description),
        )
        return True


def remove_activity(user_id, activity_type):
    today = str(date.today())
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            DELETE FROM activity_logs WHERE id = (
                SELECT id FROM activity_logs
                WHERE user_id = %s AND date = %s AND activity_type = %s
                ORDER BY logged_at DESC LIMIT 1
            )
            """,
            (user_id, today, activity_type),
        )


def get_user_stats(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT activity_type, COUNT(*) FROM activity_logs WHERE user_id = %s GROUP BY activity_type",
            (user_id,),
        )
        return {row[0]: row[1] for row in c.fetchall()}


def get_weekly_stats():
    week_ago = str(date.today() - timedelta(days=7))
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_id, COUNT(*) as total FROM activity_logs WHERE date >= %s GROUP BY user_id ORDER BY total DESC",
            (week_ago,),
        )
        return c.fetchall()


def get_weekly_leaderboard():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT
                user_id,
                SUM(CASE WHEN activity_type IN ('stretch', 'workout') THEN 1 ELSE 0 END) AS reacts,
                SUM(CASE WHEN activity_type = 'custom' THEN 1 ELSE 0 END) AS custom
            FROM activity_logs
            WHERE date >= %s
            GROUP BY user_id
            ORDER BY (reacts + custom) DESC
            """,
            (str(monday),),
        )
        return c.fetchall(), monday


def get_weekly_custom_descriptions(user_id, since_date):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT description FROM activity_logs WHERE user_id = %s AND activity_type = 'custom' AND date >= %s ORDER BY logged_at",
            (user_id, str(since_date)),
        )
        return [row[0] for row in c.fetchall()]


def get_alltime_leaderboard():
    with get_conn() as conn:
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
        return c.fetchall()
