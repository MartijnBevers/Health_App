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

row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(4)
row1_col1.metric("Meals logged today", len(today_df))
row1_col2.metric("Calories today", int(today_df["calories"].sum()))
row1_col3.metric("Protein today (g)", round(today_df["protein_g"].sum(), 1))
row1_col4.metric("Fiber today (g)", round(today_df["fiber_g"].sum(), 1))

row2_col1, row2_col2, row2_col3, row2_col4 = st.columns(4)
row2_col1.metric("Sat. fat today (g)", round(today_df["saturated_fat_g"].sum(), 1))
row2_col2.metric("Sugar today (g)", round(today_df["sugar_g"].sum(), 1))
row2_col3.metric("Sodium today (mg)", round(today_df["sodium_mg"].sum(), 0))
row2_col4.metric("Fruit/veg servings today", round(today_df["fruit_veg_servings"].sum(), 1))

# ---------------------------------------------------------------------------
# Trends over time
# ---------------------------------------------------------------------------
nutrient_columns = [
    "calories",
    "protein_g",
    "fiber_g",
    "saturated_fat_g",
    "sugar_g",
    "sodium_mg",
    "fruit_veg_servings",
]
daily = df.groupby("date")[nutrient_columns].sum().reset_index()

st.subheader("Calories per day")
st.bar_chart(daily, x="date", y="calories")

st.subheader("Protein per day")
st.bar_chart(daily, x="date", y="protein_g")

st.subheader("Fiber per day")
st.bar_chart(daily, x="date", y="fiber_g")

st.subheader("Saturated fat per day")
st.bar_chart(daily, x="date", y="saturated_fat_g")

st.subheader("Sugar per day")
st.bar_chart(daily, x="date", y="sugar_g")

st.subheader("Sodium per day")
st.bar_chart(daily, x="date", y="sodium_mg")

st.subheader("Fruit/vegetable servings per day")
st.bar_chart(daily, x="date", y="fruit_veg_servings")

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
    df[
        [
            "timestamp",
            "food",
            "calories",
            "protein_g",
            "fiber_g",
            "saturated_fat_g",
            "sugar_g",
            "sodium_mg",
            "fruit_veg_servings",
            "meal_type",
        ]
    ].sort_values("timestamp", ascending=False),
    use_container_width=True,
    hide_index=True,
)