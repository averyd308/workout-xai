import random
from datetime import date

STRETCH_OPTIONS = [
    {
        "title": "10-Min Morning Stretch",
        "description": "Full body wake-up: neck rolls, shoulder stretches, hip flexors, hamstrings",
    },
    {
        "title": "Desk Worker Relief",
        "description": "Chest opener, wrist stretches, thoracic rotation — perfect after hours of sitting",
    },
    {
        "title": "Hip Flexor Flow",
        "description": "Pigeon pose, lunge stretch, figure-4 — great for tight hips from sitting all day",
    },
    {
        "title": "Neck & Shoulder Release",
        "description": "Slow neck rolls, ear-to-shoulder, cross-body shoulder stretch — 5 minutes",
    },
    {
        "title": "Lower Back Mobility",
        "description": "Cat-cow, child's pose, knees-to-chest — relieve lower back tension",
    },
    {
        "title": "15-Min Yoga Flow",
        "description": "Sun salutations, warrior poses, forward folds — flowing and energizing",
    },
    {
        "title": "Standing Desk Break",
        "description": "Calf raises, standing quad stretch, side bends — do it right at your desk",
    },
    {
        "title": "Full Body Mobility",
        "description": "World's greatest stretch, thoracic rotations, ankle circles — 10 minutes",
    },
]

WORKOUT_OPTIONS = [
    {
        "title": "20-Min Bodyweight HIIT",
        "description": "Jumping jacks, push-ups, squats, mountain climbers — 40s on, 20s off",
    },
    {
        "title": "10-Min Core Blast",
        "description": "Planks, crunches, leg raises, Russian twists — no equipment needed",
    },
    {
        "title": "15-Min Lower Body",
        "description": "Squats, lunges, glute bridges, calf raises — feel your legs tomorrow",
    },
    {
        "title": "Upper Body Push",
        "description": "Push-ups (3 variations), tricep dips on a chair, shoulder taps — 15 min",
    },
    {
        "title": "30-Min Walk or Run",
        "description": "Get outside! Any pace counts. Fresh air + movement = instant mood boost",
    },
    {
        "title": "7-Minute Workout",
        "description": "The science-backed circuit: 12 exercises, 30s each — quick but intense",
    },
    {
        "title": "Yoga Strength Flow",
        "description": "Chair pose, warrior 2, plank flows — builds strength with yoga movements",
    },
    {
        "title": "Dance Break",
        "description": "Put on your favorite playlist and move for 15 minutes. Yes, this counts.",
    },
]


def get_daily_options():
    # Deterministic seed per date so restarts return the same options
    rng = random.Random(str(date.today()))
    return rng.choice(STRETCH_OPTIONS), rng.choice(WORKOUT_OPTIONS)
