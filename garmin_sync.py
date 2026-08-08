"""
garmin_sync.py - Pull recent activities from Garmin Connect
================================================================
Uses the UNOFFICIAL `garminconnect` library, which logs into your normal
Garmin Connect account (same email/password as the phone app) and reads
the same data the Garmin Connect web dashboard shows you.

This is NOT Garmin's official Health API -- that program is a business-
only, approval-gated integration meant for companies, not personal
projects. `garminconnect` is what most hobbyist dashboards use instead.
It works well in practice but two things to know: it's against the
letter of Garmin's Terms of Service, and it can break if Garmin changes
its login flow (no official support). For a single-user personal
dashboard like this one, that's a reasonable trade-off.

Setup:
    pip install garminconnect

    Add to your .env (and Streamlit Cloud Secrets when deployed):
        GARMIN_EMAIL=your-garmin-email@example.com
        GARMIN_PASSWORD=your-garmin-password
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

from db import insert_exercise, get_last_garmin_sync, set_last_garmin_sync

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")


def _estimate_intensity(calories: float, duration_min: float) -> str:
    """Rough calories-per-minute -> intensity mapping, so Garmin-imported
    workouts land on the same low/moderate/high scale as chat-logged ones
    (Garmin gives us calories + duration directly, not an intensity label).
    """
    if duration_min <= 0:
        return "low"
    cal_per_min = calories / duration_min
    if cal_per_min < 6:
        return "low"
    if cal_per_min < 10:
        return "moderate"
    return "high"


def sync_garmin_activities(days_back: int = 3) -> int:
    """Fetch recent activities from Garmin Connect and insert any new ones.

    Looks back `days_back` days (default 3) rather than just "today", so
    a day the app wasn't opened doesn't silently lose that day's workout.
    Duplicates are impossible to create -- see the unique index on
    garmin_activity_id in db.py -- so it's always safe to re-run this.

    Returns the number of NEW activities inserted.
    """
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise RuntimeError(
            "Missing GARMIN_EMAIL / GARMIN_PASSWORD. Add them to your .env "
            "(locally) or Streamlit Cloud Secrets (when deployed)."
        )

    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()

    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    activities = client.get_activities_by_date(start_date, end_date)

    inserted_count = 0
    for activity in activities:
        garmin_id = str(activity.get("activityId"))
        activity_type = activity.get("activityType", {}).get("typeKey", "unknown")
        duration_min = round((activity.get("duration") or 0) / 60, 1)  # Garmin gives seconds
        calories_burned = int(activity.get("calories") or 0)
        timestamp = activity.get("startTimeLocal") or datetime.now().isoformat(timespec="seconds")
        intensity = _estimate_intensity(calories_burned, duration_min)

        was_inserted = insert_exercise(
            source="garmin",
            activity_type=activity_type,
            duration_min=duration_min,
            calories_burned=calories_burned,
            intensity=intensity,
            garmin_activity_id=garmin_id,
            timestamp=timestamp,
        )
        if was_inserted:
            inserted_count += 1

    set_last_garmin_sync(datetime.now().isoformat(timespec="seconds"))
    return inserted_count


def sync_if_stale(min_hours_between_syncs: int = 24) -> int | None:
    """Run sync_garmin_activities() only if it hasn't run in the last
    `min_hours_between_syncs` hours. Returns the count of new activities,
    or None if skipped because it's not due yet.

    Streamlit Community Cloud has no cron jobs / background scheduler, so
    this is how we get "once a day" syncing anyway: every time the
    Exercise page loads, we check a timestamp stored in the database and
    only actually hit Garmin's servers if 24h have really passed. If the
    app isn't opened for a few days, it just catches up via days_back the
    next time someone visits.
    """
    last_sync = get_last_garmin_sync()
    if last_sync is not None:
        last_sync_dt = datetime.fromisoformat(last_sync)
        if datetime.now() - last_sync_dt < timedelta(hours=min_hours_between_syncs):
            return None
    return sync_garmin_activities()