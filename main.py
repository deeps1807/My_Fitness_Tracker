from fastmcp import FastMCP
import os
import sqlite3
from datetime import date, datetime
import json
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# -----------------------------
# CONFIG
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "calorie_tracker_ai.db")

WATER_GOAL = 2.5

SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read"
]

mcp = FastMCP("CalorieTracker_Smart")

# -----------------------------
# DATABASE
# -----------------------------
def get_connection():
    return sqlite3.connect(DB_PATH)

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
            calories REAL
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
def store_meal(description, estimated_calories):

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
        "meal": description,
        "calories_added": estimated_calories,
        "date": log_date
    }

# -----------------------------
# LOG WATER
# -----------------------------
@mcp.tool()
def log_water(amount_liters):

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
        hydration_status = "low"
    else:
        hydration_status = "good"

    return {
        "status": hydration_status,
        "total_water": total,
        "goal": WATER_GOAL
    }

# -----------------------------
# SYNC STEPS
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
        "steps_today": steps
    }

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
