"""
db.py - Database layer (Turso / libSQL)
=========================================
This module is the ONLY place that knows how to talk to the database.
Every other file (the agent's tools, the Streamlit pages) calls the
functions here instead of writing SQL directly. That's what lets us
swap local SQLite for hosted Turso without touching the agent logic
at all -- same pattern as when local SQLite replaced the dummy list
back in Step 4.

Turso is a hosted, SQLite-compatible database (built on libSQL), so the
schema and SQL below are almost identical to what you had before. The
real difference is *how* we connect: a URL + auth token instead of a
local file path -- which is exactly what makes this reachable from a
Streamlit Community Cloud deployment, from your phone, from anywhere.

Setup:
    pip install libsql-client python-dotenv

    Create a Turso database (one-time, via the Turso CLI or dashboard),
    then add these to your .env file (locally) and to your Streamlit
    Cloud app's Secrets (when deployed):
        TURSO_DATABASE_URL=libsql://your-db-name-yourusername.turso.io
        TURSO_AUTH_TOKEN=your-token-here
"""

import os
from datetime import datetime
from pathlib import Path

import libsql_client
from dotenv import load_dotenv

# Point load_dotenv() at the .env file sitting next to THIS file, rather
# than relying on the current working directory. Without this, running
# `streamlit run streamlit_app.py` from a different folder (or Streamlit
# launching from its own working directory) can silently fail to find
# .env, since load_dotenv() with no arguments only searches upward from
# wherever the process was started, not from where db.py lives.
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)


def _require_env(key: str) -> str:
    """Fetch an environment variable, or raise a clear, actionable error.

    Plain os.environ[key] raises a bare KeyError with no context, which
    is confusing to debug. This gives you the exact file path it looked
    for, so a missing/misnamed .env is obvious immediately.
    """
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Missing environment variable '{key}'. Expected it in "
            f"{env_path} (locally) or in Streamlit Cloud's Secrets "
            f"(when deployed). Double check the file exists, is named "
            f"exactly '.env', and that '{key}=...' is spelled correctly "
            f"inside it."
        )
    return value


TURSO_URL = _require_env("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = _require_env("TURSO_AUTH_TOKEN")


def get_client() -> libsql_client.Client:
    """Open a fresh connection to the Turso database.

    We open/close a connection per operation rather than keeping one
    long-lived connection open. Simpler to reason about, and Turso is
    built to handle many short-lived connections cheaply -- fine for a
    personal-scale app like this.

    NOTE: we force the HTTPS transport instead of the WebSocket one.
    The `libsql://` scheme makes this client connect over WebSocket
    (wss://), which currently fails its handshake (HTTP 400) against
    newer Turso databases created via the web dashboard. Swapping the
    scheme to `https://` makes the same client talk plain HTTP instead,
    which is more broadly compatible and avoids that handshake entirely.
    """
    http_url = TURSO_URL.replace("libsql://", "https://", 1)
    return libsql_client.create_client_sync(
        url=http_url,
        auth_token=TURSO_AUTH_TOKEN,
    )


def init_db() -> None:
    """Create the `meals` table if it doesn't already exist, and make
    sure it has every column this version of the app expects.

    Safe to call every time the app starts. CREATE TABLE IF NOT EXISTS
    is a no-op if the table is already there -- and for a table that
    already exists from before this update, we check which columns are
    genuinely missing (via PRAGMA table_info) and only add those. Old
    rows simply get 0 for any new fields, since we don't know their
    real values retroactively.
    """
    client = get_client()
    try:
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                food         TEXT NOT NULL,
                calories     INTEGER NOT NULL,
                protein_g    REAL NOT NULL,
                meal_type    TEXT NOT NULL
            )
            """
        )

        # We check which columns already exist FIRST, rather than just
        # trying ALTER TABLE and catching the "already exists" error.
        # Reason: libsql_client's HTTP transport has a bug where a
        # failed ALTER TABLE raises a raw KeyError('result') instead of
        # a readable exception, so we can't reliably detect "duplicate
        # column" from the error message. Checking first avoids ever
        # triggering that error path.
        existing_columns = _get_existing_columns(client, "meals")

        # Each of these gets added only if missing, so this dict can
        # just keep growing as you track more nutrients over time.
        new_columns = {
            "fiber_g": "REAL NOT NULL DEFAULT 0",
            "saturated_fat_g": "REAL NOT NULL DEFAULT 0",
            "sugar_g": "REAL NOT NULL DEFAULT 0",
            "sodium_mg": "REAL NOT NULL DEFAULT 0",
            "fruit_veg_servings": "REAL NOT NULL DEFAULT 0",
        }
        for column_name, column_definition in new_columns.items():
            if column_name not in existing_columns:
                client.execute(
                    f"ALTER TABLE meals ADD COLUMN {column_name} {column_definition}"
                )

        # profile: age and height DON'T need history -- just the current
        # value -- so they live as columns on this single-row table, same
        # pattern as the old body_weight_kg used to (before weight got its
        # own log table below, since weight DOES need history).
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                body_weight_kg REAL,
                updated_at TEXT NOT NULL
            )
            """
        )
        profile_columns = _get_existing_columns(client, "profile")
        new_profile_columns = {
            "age": "INTEGER",
            "height_cm": "REAL",
        }
        for column_name, column_definition in new_profile_columns.items():
            if column_name not in profile_columns:
                client.execute(
                    f"ALTER TABLE profile ADD COLUMN {column_name} {column_definition}"
                )

        # Weight and sleep both need progress-over-time, so each gets its
        # own append-only log table (one row per entry logged), rather than
        # a single overwritable value.
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS body_weight_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                weight_kg REAL NOT NULL
            )
            """
        )
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS sleep_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                hours     REAL NOT NULL
            )
            """
        )
            

        client.execute(
            """
            CREATE TABLE IF NOT EXISTS exercises (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp           TEXT NOT NULL,   -- when the workout happened
                source              TEXT NOT NULL,   -- 'chat' or 'garmin'
                activity_type       TEXT NOT NULL,   -- e.g. 'running', 'strength_training'
                duration_min        REAL NOT NULL,
                calories_burned     INTEGER NOT NULL,
                intensity           TEXT NOT NULL,   -- 'low' | 'moderate' | 'high'
                garmin_activity_id  TEXT              -- NULL for chat-logged entries
            )
            """
        )
        # Partial unique index: only enforces uniqueness where an activity
        # actually came from Garmin. This is what lets us re-run the Garmin
        # sync every day without ever creating duplicate rows for the same
        # workout -- INSERT OR IGNORE below will silently skip a repeat.
        client.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_exercises_garmin_id
            ON exercises(garmin_activity_id)
            WHERE garmin_activity_id IS NOT NULL
            """
        )

        client.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_garmin_sync TEXT
            )
            """
        )

        client.execute(
            """
            CREATE TABLE IF NOT EXISTS exercise_catalog (
                name     TEXT PRIMARY KEY,
                category TEXT NOT NULL
            )
            """
        )
        client.execute(
            """
            CREATE TABLE IF NOT EXISTS strength_sets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT NOT NULL,   -- when the set was logged
                date       TEXT NOT NULL,   -- session date (YYYY-MM-DD), for grouping sets into a workout
                exercise   TEXT NOT NULL,
                category   TEXT,
                weight_kg  REAL,
                reps       INTEGER,
                notes      TEXT
            )
            """
        )

        # Seed a small default catalog on first run -- INSERT OR IGNORE
        # makes this a no-op on every call after the first.
        default_exercises = [
            ("Bench Press", "Chest"), ("Incline Dumbbell Press", "Chest"), ("Push Up", "Chest"),
            ("Deadlift", "Back"), ("Pull Up", "Back"), ("Barbell Row", "Back"), ("Lat Pulldown", "Back"),
            ("Squat", "Legs"), ("Leg Press", "Legs"), ("Romanian Deadlift", "Legs"),
            ("Overhead Press", "Shoulders"), ("Lateral Raise", "Shoulders"),
            ("Bicep Curl", "Arms"), ("Tricep Pushdown", "Arms"),
            ("Plank", "Core"),
        ]
        for name, category in default_exercises:
            client.execute(
                "INSERT OR IGNORE INTO exercise_catalog (name, category) VALUES (?, ?)",
                [name, category],
            )

    finally:
        client.close()


def _get_existing_columns(client: libsql_client.Client) -> set[str]:
    """Return the set of column names currently on the meals table.

    Uses SQLite's PRAGMA table_info, which returns one row per existing
    column with fields (cid, name, type, notnull, dflt_value, pk) -- we
    only need the 'name' field here.
    """
    result = client.execute("PRAGMA table_info(meals)")
    name_index = result.columns.index("name")
    return {row[name_index] for row in result.rows}


def insert_meal(
    food: str,
    calories: int,
    protein_g: float,
    meal_type: str,
    fiber_g: float = 0,
    saturated_fat_g: float = 0,
    sugar_g: float = 0,
    sodium_mg: float = 0,
    fruit_veg_servings: float = 0,
) -> None:
    """Insert one meal row, stamped with the current time.

    The five nutrient fields after meal_type default to 0 so that any
    existing caller passing only the original four arguments keeps
    working without changes.

    Uses `?` placeholders instead of string-formatting the values into
    the SQL -- this avoids SQL injection and is the correct habit even
    for a personal project.
    """
    client = get_client()
    try:
        client.execute(
            """
            INSERT INTO meals (
                timestamp, food, calories, protein_g, meal_type,
                fiber_g, saturated_fat_g, sugar_g, sodium_mg, fruit_veg_servings
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                datetime.now().isoformat(timespec="seconds"),
                food,
                calories,
                protein_g,
                meal_type,
                fiber_g,
                saturated_fat_g,
                sugar_g,
                sodium_mg,
                fruit_veg_servings,
            ],
        )
    finally:
        client.close()


def fetch_all_meals() -> list[dict]:
    """Return every logged meal, most recent first, as a list of dicts.

    Converting rows to dicts here (rather than leaving them as raw tuples)
    means the Streamlit dashboard can work with plain, readable data
    without needing to know anything about the underlying client library.
    """
    client = get_client()
    try:
        result = client.execute("SELECT * FROM meals ORDER BY id DESC")
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        client.close()


def log_body_weight(weight_kg: float) -> None:
    """Append a new body-weight entry, stamped with the current time.

    We INSERT a new row rather than overwriting a single value -- that's
    what lets the dashboard plot weight as a trend over time instead of
    only ever showing "today's" number.
    """
    client = get_client()
    try:
        client.execute(
            "INSERT INTO body_weight_log (timestamp, weight_kg) VALUES (?, ?)",
            [datetime.now().isoformat(timespec="seconds"), weight_kg],
        )
    finally:
        client.close()


def fetch_body_weight_log() -> list[dict]:
    """Return every logged body-weight entry, most recent first."""
    client = get_client()
    try:
        result = client.execute("SELECT * FROM body_weight_log ORDER BY id DESC")
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        client.close()


def get_latest_body_weight_kg() -> float | None:
    """Return the most recently logged body weight, or None if none yet.

    This is what protein-per-kg targets on the dashboard should read
    from -- always the latest entry, never a value that can go stale.
    """
    client = get_client()
    try:
        result = client.execute(
            "SELECT weight_kg FROM body_weight_log ORDER BY id DESC LIMIT 1"
        )
        if not result.rows:
            return None
        return float(result.rows[0][0])
    finally:
        client.close()


def log_sleep(hours: float) -> None:
    """Append a new sleep entry, dated to TODAY.

    People usually report sleep in the morning, referring to last
    night -- but we keep this simple and just stamp "today" rather than
    trying to guess "last night" as a separate date. Good enough for a
    personal tracker; easy to revisit later if it ever feels off.
    """
    client = get_client()
    try:
        client.execute(
            "INSERT INTO sleep_log (timestamp, hours) VALUES (?, ?)",
            [datetime.now().isoformat(timespec="seconds"), hours],
        )
    finally:
        client.close()


def fetch_sleep_log() -> list[dict]:
    """Return every logged sleep entry, most recent first."""
    client = get_client()
    try:
        result = client.execute("SELECT * FROM sleep_log ORDER BY id DESC")
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        client.close()


def set_profile_info(age: int | None = None, height_cm: float | None = None) -> None:
    """Update age and/or height. Pass only the field(s) that changed --
    the other keeps whatever was already stored.

    Unlike weight/sleep, age and height don't need history, so this
    overwrites the single stored value in place instead of appending.
    """
    client = get_client()
    try:
        current = client.execute("SELECT age, height_cm FROM profile WHERE id = 1")
        existing_age = current.rows[0][0] if current.rows else None
        existing_height = current.rows[0][1] if current.rows else None

        new_age = age if age is not None else existing_age
        new_height = height_cm if height_cm is not None else existing_height

        client.execute(
            """
            INSERT INTO profile (id, age, height_cm, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                age = excluded.age,
                height_cm = excluded.height_cm,
                updated_at = excluded.updated_at
            """,
            [new_age, new_height, datetime.now().isoformat(timespec="seconds")],
        )
    finally:
        client.close()


def get_profile_info() -> dict:
    """Return {'age': ..., 'height_cm': ...}, with None for anything not yet set."""
    client = get_client()
    try:
        result = client.execute("SELECT age, height_cm FROM profile WHERE id = 1")
        if not result.rows:
            return {"age": None, "height_cm": None}
        return {"age": result.rows[0][0], "height_cm": result.rows[0][1]}
    finally:
        client.close()

def insert_exercise(
    source: str,
    activity_type: str,
    duration_min: float,
    calories_burned: int,
    intensity: str,
    garmin_activity_id: str | None = None,
    timestamp: str | None = None,
) -> bool:
    """Insert one exercise row. Returns True if a new row was actually
    inserted, False if it was skipped as a duplicate.

    Chat-logged workouts (garmin_activity_id=None) always insert -- the
    partial unique index only applies where garmin_activity_id IS NOT NULL,
    so multiple NULLs are fine. Garmin-imported workouts use INSERT OR
    IGNORE, so re-syncing the same days is always safe to repeat.

    timestamp defaults to "now" for chat-logged entries; Garmin imports
    pass the workout's real start time instead.
    """
    client = get_client()
    try:
        result = client.execute(
            """
            INSERT OR IGNORE INTO exercises (
                timestamp, source, activity_type, duration_min,
                calories_burned, intensity, garmin_activity_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                timestamp or datetime.now().isoformat(timespec="seconds"),
                source,
                activity_type,
                duration_min,
                calories_burned,
                intensity,
                garmin_activity_id,
            ],
        )
        return result.rows_affected > 0
    finally:
        client.close()


def fetch_all_exercises() -> list[dict]:
    """Return every logged exercise, most recent first, as a list of dicts."""
    client = get_client()
    try:
        result = client.execute("SELECT * FROM exercises ORDER BY id DESC")
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        client.close()


def get_last_garmin_sync() -> str | None:
    """Return the ISO timestamp of the last successful Garmin sync, or
    None if a sync has never run."""
    client = get_client()
    try:
        result = client.execute("SELECT last_garmin_sync FROM sync_state WHERE id = 1")
        if not result.rows:
            return None
        return result.rows[0][0]
    finally:
        client.close()


def set_last_garmin_sync(timestamp: str) -> None:
    """Record that a Garmin sync just ran, so sync_if_stale() knows not
    to run again for another 24h."""
    client = get_client()
    try:
        client.execute(
            """
            INSERT INTO sync_state (id, last_garmin_sync)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET last_garmin_sync = excluded.last_garmin_sync
            """,
            [timestamp],
        )
    finally:
        client.close()

def fetch_exercise_catalog() -> list[dict]:
    """Return every exercise in the catalog (name + category), A-Z."""
    client = get_client()
    try:
        result = client.execute("SELECT name, category FROM exercise_catalog ORDER BY name")
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        client.close()


def add_exercise_to_catalog(name: str, category: str) -> None:
    """Add a new exercise so it shows up in the picker next time."""
    client = get_client()
    try:
        client.execute(
            "INSERT OR IGNORE INTO exercise_catalog (name, category) VALUES (?, ?)",
            [name, category],
        )
    finally:
        client.close()


def insert_strength_set(
    date: str, exercise: str, category: str, weight_kg: float, reps: int, notes: str = ""
) -> None:
    """Log one set -- one row per set, same model FitNotes uses.
    `date` is the workout day (YYYY-MM-DD); `timestamp` is "now"."""
    client = get_client()
    try:
        client.execute(
            """
            INSERT INTO strength_sets (timestamp, date, exercise, category, weight_kg, reps, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [datetime.now().isoformat(timespec="seconds"), date, exercise, category, weight_kg, reps, notes],
        )
    finally:
        client.close()


def fetch_strength_sets(date: str | None = None) -> list[dict]:
    """Return logged sets, most recent first. Pass `date` (YYYY-MM-DD)
    to filter to one day; omit it to get the full history."""
    client = get_client()
    try:
        if date:
            result = client.execute("SELECT * FROM strength_sets WHERE date = ? ORDER BY id DESC", [date])
        else:
            result = client.execute("SELECT * FROM strength_sets ORDER BY id DESC")
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        client.close()


def delete_strength_set(set_id: int) -> None:
    """Delete one logged set by id -- for fixing a mis-entered weight/reps."""
    client = get_client()
    try:
        client.execute("DELETE FROM strength_sets WHERE id = ?", [set_id])
    finally:
        client.close()


def _get_existing_columns(client: libsql_client.Client, table_name: str) -> set[str]:
    """Return the set of column names currently on the given table.

    Made generic (was meals-only before) so it can also check the
    `profile` table when we add age/height columns to it below.
    """
    result = client.execute(f"PRAGMA table_info({table_name})")
    name_index = result.columns.index("name")
    return {row[name_index] for row in result.rows}