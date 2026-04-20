import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "watcher.db")


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS daily_posts (
                date           TEXT NOT NULL,
                message_ts     TEXT NOT NULL,
                channel_id     TEXT NOT NULL,
                stretch_option TEXT DEFAULT '',
                workout_option TEXT DEFAULT '',
                PRIMARY KEY (date, channel_id)
            );
            CREATE TABLE IF NOT EXISTS activity_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                date          TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                description   TEXT DEFAULT '',
                channel_id    TEXT DEFAULT '',
                logged_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, date, activity_type, channel_id)
            );
        """)


def save_daily_post(date_str, message_ts, channel_id, stretch_option="", workout_option=""):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO daily_posts VALUES (?, ?, ?, ?, ?)",
            (date_str, message_ts, channel_id, stretch_option, workout_option),
        )


def get_all_posts():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM daily_posts ORDER BY date").fetchall()]


def get_post_by_ts(message_ts):
    with _conn() as c:
        row = c.execute("SELECT * FROM daily_posts WHERE message_ts=?", (message_ts,)).fetchone()
        return dict(row) if row else None


def log_activity(user_id, activity_type, description, channel_id, date_str):
    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO activity_logs (user_id, date, activity_type, description, channel_id) VALUES (?,?,?,?,?)",
                (user_id, date_str, activity_type, description or "", channel_id or ""),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_activity(user_id, activity_type, date_str, channel_id=""):
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM activity_logs WHERE user_id=? AND date=? AND activity_type=? AND channel_id=? ORDER BY logged_at DESC LIMIT 1",
            (user_id, date_str, activity_type, channel_id),
        ).fetchone()
        if row:
            c.execute("DELETE FROM activity_logs WHERE id=?", (row["id"],))


def get_user_stats(user_id, channel_id=None):
    with _conn() as c:
        if channel_id:
            rows = c.execute(
                "SELECT activity_type FROM activity_logs WHERE user_id=? AND channel_id=?",
                (user_id, channel_id),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT activity_type FROM activity_logs WHERE user_id=?", (user_id,)
            ).fetchall()
    stats = {}
    for r in rows:
        t = r["activity_type"]
        stats[t] = stats.get(t, 0) + 1
    return stats


def get_all_activity_set():
    """Return set of (user_id, date, activity_type, channel_id) for diffing against Supabase."""
    with _conn() as c:
        rows = c.execute(
            "SELECT user_id, date, activity_type, channel_id FROM activity_logs"
        ).fetchall()
    return {(r["user_id"], r["date"], r["activity_type"], r["channel_id"] or "") for r in rows}


def get_stats_summary(channel_id=None):
    """Return {user_id: {activity_type: count}} for all users."""
    with _conn() as c:
        if channel_id:
            rows = c.execute(
                "SELECT user_id, activity_type FROM activity_logs WHERE channel_id=?", (channel_id,)
            ).fetchall()
        else:
            rows = c.execute("SELECT user_id, activity_type FROM activity_logs").fetchall()
    stats = {}
    for r in rows:
        uid, t = r["user_id"], r["activity_type"]
        stats.setdefault(uid, {})[t] = stats[uid].get(t, 0) + 1
    return stats
