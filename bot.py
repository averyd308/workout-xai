import os
import logging
from datetime import datetime

from slack_bolt import App

import database
import workouts

bolt_app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
STRETCH_EMOJI = "person_in_lotus_position"
WORKOUT_EMOJI = "muscle"


def post_daily_message(force=False):
    if not force and database.get_today_post():
        logging.info("Daily post already sent today, skipping.")
        return

    today = str(datetime.now().date())
    scheduled = database.get_scheduled_options(today)
    if scheduled and scheduled[0] and scheduled[2]:
        stretch = {"title": scheduled[0], "description": scheduled[1] or ""}
        workout = {"title": scheduled[2], "description": scheduled[3] or ""}
    else:
        stretch, workout = workouts.get_daily_options()

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Good morning! Today's movement options 🌅"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "React to log your activity — you can do one or both!"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":person_in_lotus_position:  *{stretch['title']}*\n"
                    f"_{stretch['description']}_\n"
                    f"→ React with :person_in_lotus_position: when done"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":muscle:  *{workout['title']}*\n"
                    f"_{workout['description']}_\n"
                    f"→ React with :muscle: when done"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Log your own activity with `/workout [description]`  •  Check your stats with `/mystats`",
                }
            ],
        },
    ]

    result = bolt_app.client.chat_postMessage(
        channel=CHANNEL_ID,
        text=f"Today's movement options: {stretch['title']} or {workout['title']}",
        blocks=blocks,
    )
    database.save_daily_post(today, result["ts"], CHANNEL_ID, stretch["title"], workout["title"])
    logging.info(f"Daily post sent: ts={result['ts']}")
