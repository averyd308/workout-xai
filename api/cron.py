import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request

import database
from bot import post_daily_message

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


app = flask_app
