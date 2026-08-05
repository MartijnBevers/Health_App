"""
pages/1_Dashboard.py - Stats and visuals
============================================
Streamlit automatically turns any file inside a `pages/` folder into an
extra page in the app's sidebar -- no manual routing code needed. This
page reads everything back out of Turso via fetch_all_meals() and shows
summary stats plus a couple of simple charts.
"""

import pandas as pd
import streamlit as st

from auth import require_password
from db import fetch_all_meals

# Must run before anything else renders -- otherwise the Dashboard page
# would be reachable directly, bypassing the login on the main page.
require_password()

st.set_page_config(page_title="Dashboard", page_icon="📊")
st.title("📊 Nutrition dashboard")

meals = fetch_all_meals()

if not meals:
    st.info("No meals logged yet -- head to the Log Meal page to add your first one.")
    st.stop()

# Turn the list of dicts into a DataFrame -- makes grouping/plotting easy.
df = pd.DataFrame(meals)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df["date"] = df["timestamp"].dt.date

# ---------------------------------------------------------------------------
# Today's top-line numbers
# ---------------------------------------------------------------------------
today = pd.Timestamp.now().date()
today_df = df[df["date"] == today]

col1, col2, col3 = st.columns(3)
col1.metric("Meals logged today", len(today_df))
col2.metric("Calories today", int(today_df["calories"].sum()))
col3.metric("Protein today (g)", round(today_df["protein_g"].sum(), 1))

# ---------------------------------------------------------------------------
# Trends over time
# ---------------------------------------------------------------------------
st.subheader("Calories per day")
daily = df.groupby("date")[["calories", "protein_g"]].sum().reset_index()
st.bar_chart(daily, x="date", y="calories")

st.subheader("Protein per day")
st.bar_chart(daily, x="date", y="protein_g")

# ---------------------------------------------------------------------------
# Breakdown by meal type
# ---------------------------------------------------------------------------
st.subheader("Calories by meal type")
by_type = df.groupby("meal_type")["calories"].sum()
st.bar_chart(by_type)

# ---------------------------------------------------------------------------
# Full log, most recent first
# ---------------------------------------------------------------------------
st.subheader("Full log")
st.dataframe(
    df[["timestamp", "food", "calories", "protein_g", "meal_type"]]
    .sort_values("timestamp", ascending=False),
    use_container_width=True,
    hide_index=True,
)