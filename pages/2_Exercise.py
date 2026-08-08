"""
pages/2_Exercise.py - Exercise dashboard
============================================
Shows exercise volume over a Day / Week / Month / All-time window,
combining workouts from both sources:
  - the AI chat on the homepage (source='chat')
  - Garmin Connect, synced automatically (source='garmin')

On every page load, this checks whether >=24h have passed since the
last Garmin sync and pulls new activities if so -- see garmin_sync.py
for why "check on page load" replaces a real cron job here.
"""

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_password
from db import fetch_all_exercises, init_db
from period_utils import get_period_range

require_password()
init_db()

st.set_page_config(page_title="Exercise", page_icon="🏃", layout="wide")
st.title("🏃 Exercise dashboard")

# --- Daily Garmin sync (runs at most once every 24h) ---
try:
    from garmin_sync import sync_if_stale
    new_count = sync_if_stale()
    if new_count:
        st.toast(f"Synced {new_count} new workout(s) from Garmin.")
except RuntimeError as e:
    st.warning(f"Garmin sync skipped: {e}")
except Exception as e:
    # The unofficial Garmin API can fail (login flow changes, temp
    # outage) -- never let that crash the whole dashboard.
    st.warning(f"Garmin sync failed this time: {e}")

if st.button("🔄 Sync Garmin now"):
    from garmin_sync import sync_garmin_activities
    with st.spinner("Syncing with Garmin..."):
        try:
            new_count = sync_garmin_activities()
            st.success(f"Synced {new_count} new workout(s).")
        except Exception as e:
            st.error(f"Sync failed: {e}")

exercises = fetch_all_exercises()

if not exercises:
    st.info("No exercise logged yet -- describe a workout on the homepage, or sync Garmin.")
    st.stop()

df = pd.DataFrame(exercises)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df["date"] = df["timestamp"].dt.date

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
start_date, end_date, period_label = get_period_range(view, offset, df)
nav_label.markdown(f"### {period_label}")

period_df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

if period_df.empty:
    st.info("No exercise logged in this period.")
else:
    col1, col2, col3 = st.columns(3)
    col1.metric("Workouts", len(period_df))
    col2.metric("Total time", f"{period_df['duration_min'].sum():.0f} min")
    col3.metric("Calories burned", f"{period_df['calories_burned'].sum():.0f} kcal")

    # Calories burned per day, colored by source (chat vs Garmin).
    daily = period_df.groupby(["date", "source"])["calories_burned"].sum().reset_index()
    chart = alt.Chart(daily).mark_bar().encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("calories_burned:Q", title="Calories burned"),
        color=alt.Color("source:N", title="Source"),
        tooltip=["date:T", "source:N", "calories_burned:Q"],
    )
    st.altair_chart(chart.properties(height=350), use_container_width=True)

st.subheader("Full log")
st.dataframe(
    df[["timestamp", "source", "activity_type", "duration_min", "calories_burned", "intensity"]]
    .sort_values("timestamp", ascending=False),
    use_container_width=True,
    hide_index=True,
)