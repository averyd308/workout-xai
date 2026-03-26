import sys
import os
import json
import time
import logging
import urllib.request
import urllib.parse
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request
import database
from bot import bolt_app, CHANNEL_ID

logging.basicConfig(level=logging.INFO)
flask_app = Flask(__name__)

ACTIVITY_EMOJIS = {
    "Run": ":runner:",
    "Walk": ":walking_pace:",
    "Ride": ":bike:",
    "Swim": ":swimmer:",
    "Hike": ":national_park:",
    "WeightTraining": ":muscle:",
    "Yoga": ":person_in_lotus_position:",
    "Workout": ":muscle:",
    "Elliptical": ":muscle:",
    "StairStepper": ":muscle:",
}


def get_valid_access_token(tokens):
    if tokens["expires_at"] > int(time.time()) + 60:
        return tokens["access_token"]

    data = urllib.parse.urlencode({
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }).encode()

    req = urllib.request.Request(
        "https://www.strava.com/oauth/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        new_tokens = json.loads(resp.read())

    database.save_strava_tokens(
        slack_user_id=tokens["slack_user_id"],
        athlete_id=tokens["strava_athlete_id"],
        access_token=new_tokens["access_token"],
        refresh_token=new_tokens["refresh_token"],
        expires_at=new_tokens["expires_at"],
    )
    return new_tokens["access_token"]


def fetch_activity(access_token, activity_id):
    req = urllib.request.Request(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def format_activity_message(activity, slack_user_id):
    emoji = ACTIVITY_EMOJIS.get(activity["type"], ":athletic_shoe:")
    activity_type = activity["type"]

    parts = []
    distance_m = activity.get("distance", 0)
    moving_time_s = activity.get("moving_time", 0)

    if distance_m > 0:
        distance_mi = distance_m / 1609.34
        parts.append(f"📏 {distance_mi:.2f} mi")

    if moving_time_s > 0:
        hours = moving_time_s // 3600
        minutes = (moving_time_s % 3600) // 60
        seconds = moving_time_s % 60
        duration = f"{hours}h {minutes}m" if hours else f"{minutes}m {seconds}s"
        parts.append(f"⏱️ {duration}")

    if distance_m > 0 and moving_time_s > 0 and activity["type"] in ("Run", "Walk", "Hike"):
        distance_mi = distance_m / 1609.34
        pace_s = moving_time_s / distance_mi
        parts.append(f"⚡ {int(pace_s // 60)}:{int(pace_s % 60):02d}/mi")

    stats = "  •  ".join(parts)
    url = f"https://www.strava.com/activities/{activity['id']}"
    return (
        f"{emoji} *<@{slack_user_id}> just logged a {activity_type} on Strava!*\n"
        f"{stats}\n"
        f"<{url}|View on Strava>"
    )


@flask_app.route("/api/strava/webhook", methods=["GET"])
def strava_webhook_verify():
    verify_token = os.environ.get("STRAVA_VERIFY_TOKEN", "")
    if request.args.get("hub.verify_token") != verify_token:
        return "Forbidden", 403
    return json.dumps({"hub.challenge": request.args.get("hub.challenge")}), 200, {"Content-Type": "application/json"}


@flask_app.route("/api/strava/webhook", methods=["POST"])
def strava_webhook_event():
    event = request.get_json()
    if not event:
        return "ok"
    if event.get("object_type") != "activity" or event.get("aspect_type") != "create":
        return "ok"

    athlete_id = event.get("owner_id")
    activity_id = event.get("object_id")

    tokens = database.get_strava_tokens_by_athlete(athlete_id)
    if not tokens:
        return "ok"

    STRAVA_CHANNEL_ID = "C0AN6FGBF19"
    STRAVA_START_DATE = date(2026, 3, 24)

    try:
        access_token = get_valid_access_token(tokens)
        activity = fetch_activity(access_token, activity_id)
        description = f"Strava: {activity.get('name', 'activity')} [{activity_id}]"
        if database.strava_activity_already_logged(tokens["slack_user_id"], description):
            return "ok"
        text = format_activity_message(activity, tokens["slack_user_id"])
        bolt_app.client.chat_postMessage(channel=STRAVA_CHANNEL_ID, text=text)
        if date.today() >= STRAVA_START_DATE:
            database.log_activity(tokens["slack_user_id"], "custom", description, channel_id=STRAVA_CHANNEL_ID)
    except Exception as e:
        logging.error(f"Strava webhook error: {e}")

    return "ok"


app = flask_app
