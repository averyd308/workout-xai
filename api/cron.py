import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request

import database
from bot import post_daily_message, post_weekly_leaderboard, send_pending_reminders

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

flask_app = Flask(__name__)

database.init_db()


@flask_app.route("/api/cron", methods=["GET", "POST"])
def daily_cron():
    # Vercel sets this header on cron requests; reject anything else in production
    if os.environ.get("VERCEL") and request.headers.get("x-vercel-cron") != "1":
        return "Unauthorized", 401
    post_daily_message()
    return "ok"


@flask_app.route("/api/weekly-leaderboard", methods=["GET", "POST"])
def weekly_leaderboard_cron():
    if os.environ.get("VERCEL") and request.headers.get("x-vercel-cron") != "1":
        return "Unauthorized", 401
    post_weekly_leaderboard(channel_id="C0AN6FGBF19")
    return "ok"


@flask_app.route("/api/reminders", methods=["GET", "POST"])
def reminders_cron():
    cron_secret = os.environ.get("CRON_SECRET")
    if cron_secret:
        # Accept requests from Vercel cron OR any caller with the correct secret token
        vercel_ok = request.headers.get("x-vercel-cron") == "1"
        secret_ok = request.headers.get("x-cron-secret") == cron_secret
        if not (vercel_ok or secret_ok):
            return "Unauthorized", 401
    from bot import bolt_app
    timezone = os.environ.get("TIMEZONE", "America/New_York")
    send_pending_reminders(bolt_app.client, timezone)
    return "ok"


app = flask_app
