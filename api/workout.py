import sys
import os
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request, jsonify
import database

logging.basicConfig(level=logging.INFO)
flask_app = Flask(__name__)

try:
    database.seed_workout_templates()
except Exception as e:
    logging.warning(f"Template seed skipped: {e}")


@flask_app.route("/api/workout/templates")
def list_templates():
    templates = database.get_workout_templates()
    return jsonify(templates)


@flask_app.route("/api/workout/session/<session_id>")
def get_session(session_id):
    session = database.get_workout_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    template = database.get_workout_template(session["template_id"])
    if not template:
        return jsonify({"error": "Template not found"}), 404
    participants = database.get_session_participants(session_id)
    return jsonify({"session": session, "template": template, "participants": participants})


@flask_app.route("/api/workout/session/<session_id>/join", methods=["POST"])
def join_session(session_id):
    data = request.get_json() or {}
    name = str(data.get("name", "")).strip()[:50]
    if not name:
        return jsonify({"error": "Name required"}), 400
    session = database.get_workout_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    database.add_session_participant(session_id, name)
    return jsonify({"ok": True})


@flask_app.route("/api/workout/session/<session_id>/control", methods=["POST"])
def control_session(session_id):
    data = request.get_json() or {}
    host_token = data.get("host_token")
    action = data.get("action")

    session = database.get_workout_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if session["host_token"] != host_token:
        return jsonify({"error": "Unauthorized"}), 403

    template = database.get_workout_template(session["template_id"])
    exercises = template["exercises"]
    num_exercises = len(exercises)
    now = time.time()

    if action == "start":
        database.update_workout_session(session_id, {
            "status": "active",
            "exercise_start_time": now,
            "paused_elapsed": 0,
        })

    elif action == "pause" and session["status"] == "active":
        start = session.get("exercise_start_time") or now
        elapsed = (now - start) + (session.get("paused_elapsed") or 0)
        database.update_workout_session(session_id, {
            "status": "paused",
            "paused_elapsed": elapsed,
        })

    elif action == "resume" and session["status"] == "paused":
        database.update_workout_session(session_id, {
            "status": "active",
            "exercise_start_time": now,
        })

    elif action == "next":
        idx = session["current_exercise_index"] + 1
        if idx >= num_exercises:
            database.update_workout_session(session_id, {"status": "finished"})
        else:
            database.update_workout_session(session_id, {
                "current_exercise_index": idx,
                "exercise_start_time": now,
                "paused_elapsed": 0,
                "status": "active",
            })

    elif action == "prev":
        idx = max(0, session["current_exercise_index"] - 1)
        database.update_workout_session(session_id, {
            "current_exercise_index": idx,
            "exercise_start_time": now,
            "paused_elapsed": 0,
            "status": "active",
        })

    elif action == "finish":
        database.update_workout_session(session_id, {"status": "finished"})

    return jsonify({"ok": True})


app = flask_app
