import sys
import os
import json
import logging
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request
import database

logging.basicConfig(level=logging.INFO)
flask_app = Flask(__name__)


@flask_app.route("/api/strava/callback")
def strava_callback():
    error = request.args.get("error")
    code = request.args.get("code")
    slack_user_id = request.args.get("state")

    if error or not code or not slack_user_id:
        return "<h2>Connection cancelled or failed. You can close this tab.</h2>"

    data = urllib.parse.urlencode({
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "code": code,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://www.strava.com/oauth/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read())
    except Exception as e:
        logging.error(f"Strava token exchange error: {e}")
        return f"<h2>Error connecting to Strava. Please try again.</h2>"

    database.save_strava_tokens(
        slack_user_id=slack_user_id,
        athlete_id=token_data["athlete"]["id"],
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
    )

    athlete_name = token_data["athlete"]["firstname"]
    return f"""
    <html><body style="font-family:sans-serif;text-align:center;padding:60px">
    <h2>✅ Connected, {athlete_name}!</h2>
    <p>Your Strava account is now linked to the workout bot.<br>
    Future activities will be automatically posted to Slack.</p>
    <p>You can close this tab.</p>
    </body></html>
    """


app = flask_app
