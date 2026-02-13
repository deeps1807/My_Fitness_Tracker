from fastmcp import FastMCP
import os
import sqlite3
from datetime import date, datetime
import json
from typing import Optional, Dict, Any

# Google Fit imports
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# -----------------------------
# CONFIG
# -----------------------------
DB_PATH: str = os.path.join("/tmp", "calorie_tracker_ai.db")

DAILY_GOAL: int = 2000
WATER_GOAL: float = 2.5
USER_GOAL: str = "maintain"

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/fitness.activity.read"
]

mcp: FastMCP = FastMCP("CalorieTracker_Smart")

# -----------------------------
# DATABASE HELPER
# -----------------------------
def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)

# -----------------------------
# INIT DATABASE
# -----------------------------
def init_db() -> None:
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
def store_meal(
    description: str,
    estimated_calories: float,
    log_date: Optional[str] = None
) -> Dict[str, Any]:

    log_date = log_date or str(date.today())

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
            log_id: int = cur.lastrowid
        else:
            log_id = int(log[0])

        c.execute("""
            INSERT INTO food_entries (log_id, description, calories)
            VALUES (?,?,?)
        """, (log_id, description, estimated_calories))

        c.execute("""
            UPDATE logs
            SET total_calories = total_calories + ?
            WHERE id = ?
        """, (estimated_calories, log_id))

    return {
        "stored": description,
        "calories_added": estimated_calories,
        "date": log_date
    }

# -----------------------------
# LOG WATER
# -----------------------------
@mcp.tool()
def log_water(
    amount_liters: float,
    log_date: Optional[str] = None
) -> Dict[str, Any]:

    log_date = log_date or str(date.today())

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

        total: float = float(total_row[0]) if total_row else 0.0

    status: str = (
        "⚠️ Low hydration." if total < WATER_GOAL else "✅ Hydration good."
    )

    return {
        "total_water": total,
        "status": status
    }

# -----------------------------
# GOOGLE FIT STEP SYNC
# -----------------------------
@mcp.tool()
def sync_google_fit_steps() -> Dict[str, Any]:

    token_json: Optional[str] = os.getenv("GOOGLE_FIT_TOKEN")

    if not token_json:
        return {"error": "GOOGLE_FIT_TOKEN not configured"}

    creds: Credentials = Credentials.from_authorized_user_info(
        json.loads(token_json),
        SCOPES
    )

    service = build("fitness", "v1", credentials=creds)

    now: datetime = datetime.utcnow()
    start_of_day: datetime = datetime(now.year, now.month, now.day)

    body: Dict[str, Any] = {
        "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
        "bucketByTime": {"durationMillis": 86400000},
        "startTimeMillis": int(start_of_day.timestamp() * 1000),
        "endTimeMillis": int(now.timestamp() * 1000),
    }

    response: Dict[str, Any] = service.users().dataset().aggregate(
        userId="me",
        body=body
    ).execute()

    steps: int = 0

    for bucket in response.get("bucket", []):
        for dataset in bucket.get("dataset", []):
            for point in dataset.get("point", []):
                steps += int(point["value"][0].get("intVal", 0))

    today: str = str(date.today())

    with get_connection() as c:
        c.execute("""
            INSERT OR REPLACE INTO activity_logs (log_date, steps)
            VALUES (?,?)
        """, (today, steps))

    return {
        "date": today,
        "steps_today": steps
    }

# -----------------------------
# EXERCISE SUGGESTION ENGINE
# -----------------------------
@mcp.tool()
def suggest_exercise_plan() -> Dict[str, Any]:

    today: str = str(date.today())

    with get_connection() as c:
        data = c.execute("""
            SELECT steps FROM activity_logs WHERE log_date=?
        """, (today,)).fetchone()

    if data is None:
        return {"message": "No step data synced yet."}

    steps: int = int(data[0])

    if steps < 3000:
        level: str = "low"
        intensity: str = "beginner"
        duration: str = "20-30 minutes"
        focus: str = "light cardio and mobility"

    elif 3000 <= steps < 8000:
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
        "steps_today": steps,
        "activity_level": level,
        "recommended_intensity": intensity,
        "recommended_duration": duration,
        "workout_focus": focus
    }

# -----------------------------
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
