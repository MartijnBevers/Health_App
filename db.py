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

import libsql_client
from dotenv import load_dotenv

# Locally this reads your .env file. On Streamlit Cloud, secrets are
# injected as environment variables automatically, so this line is a
# no-op there but harmless -- safe to leave in both places.
load_dotenv()

TURSO_URL = os.environ["TURSO_DATABASE_URL"]
TURSO_AUTH_TOKEN = os.environ["TURSO_AUTH_TOKEN"]


def get_client() -> libsql_client.Client:
    """Open a fresh connection to the Turso database.

    We open/close a connection per operation rather than keeping one
    long-lived connection open. Simpler to reason about, and Turso is
    built to handle many short-lived connections cheaply -- fine for a
    personal-scale app like this.
    """
    return libsql_client.create_client_sync(
        url=TURSO_URL,
        auth_token=TURSO_AUTH_TOKEN,
    )


def init_db() -> None:
    """Create the `meals` table if it doesn't already exist.

    Safe to call every time the app starts -- CREATE TABLE IF NOT
    EXISTS is a no-op if the table is already there.
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
    finally:
        client.close()


def insert_meal(food: str, calories: int, protein_g: float, meal_type: str) -> None:
    """Insert one meal row, stamped with the current time.

    Uses `?` placeholders instead of string-formatting the values into
    the SQL -- this avoids SQL injection and is the correct habit even
    for a personal project.
    """
    client = get_client()
    try:
        client.execute(
            """
            INSERT INTO meals (timestamp, food, calories, protein_g, meal_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                datetime.now().isoformat(timespec="seconds"),
                food,
                calories,
                protein_g,
                meal_type,
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
