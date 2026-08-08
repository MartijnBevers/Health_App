"""
pages/2_Exercise.py - Exercise dashboard
============================================
Combines THREE sources over a Day / Week / Month / All-time window:
  - chat on the homepage           (source='chat')
  - Garmin, synced automatically   (source='garmin')
  - the native Log Workout page    (strength_sets table)

Strength sets only record weight/reps, so duration/calories for those
are ESTIMATED from set count -- see estimation.py.
"""

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_password
from db import fetch_all_exercises, fetch_strength_sets, init_db
from estimation import ESTIMATED_MIN_PER_SET, ESTIMATED_KCAL_PER_MIN
from period_utils import get_period_range

require_password()
init_db()

st.set_page_config(page_title="Exercise", page_icon="🏃", layout="wide")
st.title("🏃 Exercise dashboard")

# --- Daily Garmin sync ---
try:
    from garmin_sync import sync_if_stale
    new_count = sync_if_stale()
    if new_count:
        st.toast(f"Synced {new_count} new workout(s) from Garmin.")
except RuntimeError as e:
    st.warning(f"Garmin sync skipped: {e}")
except Exception as e:
    st.warning(f"Garmin sync failed this time: {e}")

if st.button("🔄 Sync Garmin now"):
    from garmin_sync import sync_garmin_activities
    with st.spinner("Syncing with Garmin..."):
        try:
            new_count = sync_garmin_activities()
            st.success(f"Synced {new_count} new workout(s).")
        except Exception as e:
            st.error(f"Sync failed: {e}")

# --- Load both data sources ---
exercises = fetch_all_exercises()
strength_rows = fetch_strength_sets()

df = pd.DataFrame(exercises)
if not df.empty:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date

strength_df_all = pd.DataFrame(strength_rows)
if not strength_df_all.empty:
    strength_df_all["date"] = pd.to_datetime(strength_df_all["date"]).dt.date

if df.empty and strength_df_all.empty:
    st.info("No exercise logged yet -- log a workout, describe one on the homepage, or sync Garmin.")
    st.stop()

# --- View switcher + navigation ---
if "exercise_offset" not in st.session_state:
    st.session_state.exercise_offset = 0

view = st.radio("View", ["Day", "Week", "Month", "All time"], horizontal=True)

if st.session_state.get("_last_exercise_view") != view:
    st.session_state.exercise_offset = 0
    st.session_state._last_exercise_view = view

if view != "All time":
    nav_prev, nav_label, nav_next = st.columns([1, 3, 1])
    if nav_prev.button("◀ Previous", use_container_width=True, key="ex_prev"):
        st.session_state.exercise_offset -= 1
    if nav_next.button("Next ▶", use_container_width=True, key="ex_next"):
        st.session_state.exercise_offset += 1
else:
    nav_label = st.container()

offset = st.session_state.exercise_offset
bounds_df = pd.concat([
    df[["date"]] if not df.empty else pd.DataFrame(columns=["date"]),
    strength_df_all[["date"]] if not strength_df_all.empty else pd.DataFrame(columns=["date"]),
])
start_date, end_date, period_label = get_period_range(view, offset, bounds_df)
nav_label.markdown(f"### {period_label}")

period_df = df[(df["date"] >= start_date) & (df["date"] <= end_date)] if not df.empty else df
strength_df = (
    strength_df_all[(strength_df_all["date"] >= start_date) & (strength_df_all["date"] <= end_date)]
    if not strength_df_all.empty else strength_df_all
)

# --- Aggregate strength sets into daily duration/calorie estimates ---
if not strength_df.empty:
    daily_strength = strength_df.groupby("date").size().reset_index(name="total_sets")
    daily_strength["duration_min"] = daily_strength["total_sets"] * ESTIMATED_MIN_PER_SET
    daily_strength["calories_burned"] = (daily_strength["duration_min"] * ESTIMATED_KCAL_PER_MIN).round()
    daily_strength["source"] = "manual_log"
else:
    daily_strength = pd.DataFrame(columns=["date", "total_sets", "duration_min", "calories_burned", "source"])

if period_df.empty and daily_strength.empty:
    st.info("No exercise logged in this period.")
else:
    total_minutes = period_df["duration_min"].sum() + daily_strength["duration_min"].sum()
    total_calories = period_df["calories_burned"].sum() + daily_strength["calories_burned"].sum()
    active_days = pd.concat([period_df["date"], daily_strength["date"]]).nunique()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active days", active_days)
    col2.metric("Total time", f"{total_minutes:.0f} min")
    col3.metric("Calories burned", f"{total_calories:.0f} kcal")
    col4.metric("Sets logged", int(daily_strength["total_sets"].sum()) if not daily_strength.empty else 0)

    chat_garmin_daily = (
        period_df.groupby(["date", "source"])["calories_burned"].sum().reset_index()
        if not period_df.empty else pd.DataFrame(columns=["date", "source", "calories_burned"])
    )
    combined_daily = pd.concat(
        [chat_garmin_daily, daily_strength[["date", "source", "calories_burned"]]], ignore_index=True
    )
    chart = alt.Chart(combined_daily).mark_bar().encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("calories_burned:Q", title="Calories burned (estimated for strength)"),
        color=alt.Color("source:N", title="Source"),
        tooltip=["date:T", "source:N", "calories_burned:Q"],
    )
    st.altair_chart(chart.properties(height=350), use_container_width=True)

if not period_df.empty:
    st.subheader("Cardio / chat / Garmin log")
    st.dataframe(
        period_df[["timestamp", "source", "activity_type", "duration_min", "calories_burned", "intensity"]]
        .sort_values("timestamp", ascending=False),
        use_container_width=True, hide_index=True,
    )

if not strength_df.empty:
    st.subheader("Strength sets log")
    st.dataframe(
        strength_df[["date", "exercise", "category", "weight_kg", "reps", "notes"]]
        .sort_values("date", ascending=False),
        use_container_width=True, hide_index=True,
    )