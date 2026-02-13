from fastmcp import FastMCP
import os
import sqlite3
from datetime import date, datetime
import json

# Google Fit imports
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# -----------------------------
# CONFIG
# -----------------------------
DB_PATH = os.path.join("/tmp", "calorie_tracker_ai.db")

DAILY_GOAL = 2000
WATER_GOAL = 2.5
USER_GOAL = "maintain"

SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read"
]

mcp = FastMCP("CalorieTracker_Smart")

# -----------------------------
# DATABASE CONNECTION
# -----------------------------
def get_connection():
    return sqlite3.connect(DB_PATH)

# -----------------------------
# INIT DATABASE
# -----------------------------
def init_db():
    with get_connection() as c:

        c.execute("""
        CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT UNIQUE,
            total_calories REAL DEFAULT 0
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS food_entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER,
            description TEXT,
            calories REAL,
            FOREIGN KEY(log_id) REFERENCES logs(id)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS water_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT UNIQUE,
            water_liters REAL DEFAULT 0
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT UNIQUE,
            steps INTEGER DEFAULT 0
        )
        """)

init_db()

# -----------------------------
# STORE MEAL
# -----------------------------
@mcp.tool()
def store_meal(description: str, estimated_calories: float, log_date: str = ""):

    if log_date == "":
        log_date = str(date.today())

    with get_connection() as c:

        log = c.execute(
            "SELECT id FROM logs WHERE log_date=?",
            (log_date,)
        ).fetchone()

        if log is None:
            cur = c.cursor()
            cur.execute(
                "INSERT INTO logs(log_date, total_calories) VALUES (?,0)",
                (log_date,)
            )
            log_id = cur.lastrowid
        else:
            log_id = log[0]

        c.execute(
            "INSERT INTO food_entries (log_id, description, calories) VALUES (?,?,?)",
            (log_id, description, estimated_calories)
        )

        c.execute(
            "UPDATE logs SET total_calories = total_calories + ? WHERE id = ?",
            (estimated_calories, log_id)
        )

    return {
        "status": "success",
        "stored_meal": description,
        "calories_added": estimated_calories,
        "date": log_date
    }

# -----------------------------
# LOG WATER
# -----------------------------
@mcp.tool()
def log_water(amount_liters: float, log_date: str = ""):

    if log_date == "":
        log_date = str(date.today())

    with get_connection() as c:

        record = c.execute(
            "SELECT id FROM water_logs WHERE log_date=?",
            (log_date,)
        ).fetchone()

        if record is None:
            c.execute(
                "INSERT INTO water_logs(log_date, water_liters) VALUES (?,?)",
                (log_date, amount_liters)
            )
        else:
            c.execute(
                "UPDATE water_logs SET water_liters = water_liters + ? WHERE log_date=?",
                (amount_liters, log_date)
            )

        total_row = c.execute(
            "SELECT water_liters FROM water_logs WHERE log_date=?",
            (log_date,)
        ).fetchone()

        total = total_row[0] if total_row else 0.0

    if total < WATER_GOAL:
        status = "Low hydration"
    else:
        status = "Hydration goal reached"

    return {
        "status": status,
        "total_water_liters": total,
        "goal_liters": WATER_GOAL
    }

# -----------------------------
# GOOGLE FIT STEP SYNC
# -----------------------------
@mcp.tool()
def sync_google_fit_steps():

    token_json = os.getenv("GOOGLE_FIT_TOKEN")

    if not token_json:
        return {
            "status": "error",
            "message": "GOOGLE_FIT_TOKEN not configured"
        }

    creds = Credentials.from_authorized_user_info(
        json.loads(token_json),
        SCOPES
    )

    service = build("fitness", "v1", credentials=creds)

    now = datetime.utcnow()
    start_of_day = datetime(now.year, now.month, now.day)

    body = {
        "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
        "bucketByTime": {"durationMillis": 86400000},
        "startTimeMillis": int(start_of_day.timestamp() * 1000),
        "endTimeMillis": int(now.timestamp() * 1000),
    }

    response = service.users().dataset().aggregate(
        userId="me",
        body=body
    ).execute()

    steps = 0

    for bucket in response.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                steps += int(point["value"][0].get("intVal", 0))

    today = str(date.today())

    with get_connection() as c:
        c.execute(
            "INSERT OR REPLACE INTO activity_logs (log_date, steps) VALUES (?,?)",
            (today, steps)
        )

    return {
        "status": "success",
        "date": today,
        "steps_today": steps
    }

# -----------------------------
# EXERCISE SUGGESTION
# -----------------------------
@mcp.tool()
def suggest_exercise_plan():

    today = str(date.today())

    with get_connection() as c:
        data = c.execute(
            "SELECT steps FROM activity_logs WHERE log_date=?",
            (today,)
        ).fetchone()

    if data is None:
        return {
            "status": "no_data",
            "message": "No step data synced yet."
        }

    steps = data[0]

    if steps < 3000:
        level = "low"
        intensity = "beginner"
        duration = "20-30 minutes"
        focus = "light cardio and mobility"

    elif steps < 8000:
        level = "moderate"
        intensity = "intermediate"
        duration = "30 minutes"
        focus = "fat burning workout"

    else:
        level = "high"
        intensity = "advanced"
        duration = "20 minutes"
        focus = "HIIT or strength training"

    return {
        "status": "success",
        "steps_today": steps,
        "activity_level": level,
        "recommended_intensity": intensity,
        "recommended_duration": duration,
        "workout_focus": focus
    }

# -----------------------------
# RUN SERVER
# -----------------------------
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
