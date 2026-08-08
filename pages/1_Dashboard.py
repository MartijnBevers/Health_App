"""
pages/1_Dashboard.py - Stats and visuals
============================================
This page reads everything back out of Turso via fetch_all_meals() and
shows:
  1. A view switcher (Day / Week / Month / All time) with Previous/Next
     navigation to step through periods.
  2. ONE combined bar chart covering all seven tracked nutrients, each
     shown as a percentage of its own healthy maximum -- with two green
     tick marks per bar showing where the healthy range actually sits.
     Normalizing to a percentage is what makes it possible to compare
     e.g. sodium (thousands of mg) and fruit/veg servings (single
     digits) on the same axis.
  3. A full log table underneath for the raw numbers.

Streamlit automatically turns any file inside a `pages/` folder into an
extra page in the app's sidebar -- no manual routing code needed.
"""

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_password
from db import fetch_all_meals, get_body_weight_kg, init_db, set_body_weight_kg
from period_utils import get_period_range

# Must run before anything else renders -- otherwise the Dashboard page
# would be reachable directly, bypassing the login on the main page.
require_password()

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Nutrition dashboard")


init_db()

st.subheader("Body weight")
saved_weight = get_body_weight_kg()
with st.form("body_weight_form"):
    body_weight_kg = st.number_input(
        "Current body weight (kg)",
        min_value=20.0,
        max_value=500.0,
        value=saved_weight if saved_weight is not None else 70.0,
        step=0.1,
        help="Protein targets are calculated from this value.",
    )
    if st.form_submit_button("Save weight"):
        set_body_weight_kg(body_weight_kg)
        saved_weight = body_weight_kg
        st.success("Body weight saved.")

# ---------------------------------------------------------------------------
# EDIT THESE to set your own healthy targets -- this is the ONLY place
# in the app these values live, deliberately kept out of the UI.
#
# "min"/"max" define the healthy range shown as green tick marks on the
# chart. The numbers below are common general dietary guideline figures
# (not personalized to you) just so the chart works out of the box --
# swap them for whatever targets actually make sense for your goals.
# ---------------------------------------------------------------------------
HEALTHY_RANGES = {
    "calories":           {"label": "Calories (kcal)",       "min": 1800, "max": 2200},
    "protein_g":          {"label": "Protein (g/kg)",         "min": 0.8,  "max": 2.0, "per_kg": True},
    "fiber_g":             {"label": "Fiber (g)",             "min": 25,   "max": 38},
    "saturated_fat_g":     {"label": "Saturated fat (g)",     "min": 0,    "max": 20},
    "sugar_g":             {"label": "Added sugar (g)",       "min": 0,    "max": 50},
    "sodium_mg":           {"label": "Sodium (mg)",           "min": 0,    "max": 2300},
    "fruit_veg_servings":  {"label": "Fruit/veg (servings)",  "min": 5,    "max": 10},
}


meals = fetch_all_meals()

if not meals:
    st.info("No meals logged yet -- head to the Log Meal page to add your first one.")
    st.stop()

# Turn the list of dicts into a DataFrame -- makes grouping/filtering easy.
df = pd.DataFrame(meals)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df["date"] = df["timestamp"].dt.date


# ---------------------------------------------------------------------------
# View switcher + Previous/Next navigation
# ---------------------------------------------------------------------------
if "dashboard_offset" not in st.session_state:
    st.session_state.dashboard_offset = 0

view = st.radio("View", ["Day", "Week", "Month", "All time"], horizontal=True)

# Reset the navigation offset whenever the view type itself changes, so
# switching from e.g. "Week" to "Month" doesn't carry over a confusing
# leftover offset from the other view.
if st.session_state.get("_last_dashboard_view") != view:
    st.session_state.dashboard_offset = 0
    st.session_state._last_dashboard_view = view

if view != "All time":
    nav_prev, nav_label, nav_next = st.columns([1, 3, 1])
    if nav_prev.button("\u25c0 Previous", use_container_width=True):
        st.session_state.dashboard_offset -= 1
    if nav_next.button("Next \u25b6", use_container_width=True):
        st.session_state.dashboard_offset += 1
else:
    # No navigation for "All time" -- there's only one possible range.
    nav_label = st.container()

offset = st.session_state.dashboard_offset
start_date, end_date, period_label = get_period_range(view, offset, df)
nav_label.markdown(f"### {period_label}")

period_df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]


# ---------------------------------------------------------------------------
# Combined bar chart: all seven metrics as % of their healthy maximum,
# with green tick marks showing the healthy min/max for each one.
# ---------------------------------------------------------------------------
if period_df.empty:
    st.info("No meals logged in this period.")
else:
    # Average per DAY YOU ACTUALLY LOGGED, not per calendar day -- so a
    # week where you only logged 2 days isn't unfairly diluted by the
    # 5 days you simply didn't track.
    logged_days = period_df["date"].nunique() or 1
    metric_totals = period_df[list(HEALTHY_RANGES.keys())].sum()
    metric_avg_per_day = metric_totals / logged_days

    chart_rows = []
    for column_name, info in HEALTHY_RANGES.items():
        value = metric_avg_per_day[column_name]
        # Protein is assessed relative to current body weight. Without a
        # saved weight, omitting it avoids displaying a false personalized
        # comparison.
        if info.get("per_kg"):
            if saved_weight is None:
                continue
            value = value / saved_weight
        healthy_max = info["max"]
        healthy_min = info["min"]
        # Normalize to % of the healthy MAX so every metric lands on a
        # comparable 0-ish-to-150-ish scale, regardless of raw units.
        value_pct = (value / healthy_max * 100) if healthy_max else 0
        min_pct = (healthy_min / healthy_max * 100) if healthy_max else 0
        chart_rows.append(
            {
                "metric": info["label"],
                "value": value,
                "value_pct": value_pct,
                "min_pct": min_pct,
                "max_pct": 100,
                "healthy_min": healthy_min,
                "healthy_max": healthy_max,
            }
        )
    chart_df = pd.DataFrame(chart_rows)

    if saved_weight is None:
        st.info("Add your body weight above to include protein in g/kg/day.")

    bars = alt.Chart(chart_df).mark_bar(color="#4C78A8").encode(
        x=alt.X("metric:N", title=None, sort=None, axis=alt.Axis(labelAngle=-30)),
        y=alt.Y("value_pct:Q", title="% of healthy range"),
        tooltip=[
            alt.Tooltip("metric:N", title="Metric"),
            alt.Tooltip("value:Q", title="Your avg/day", format=".1f"),
            alt.Tooltip("healthy_min:Q", title="Healthy min"),
            alt.Tooltip("healthy_max:Q", title="Healthy max"),
        ],
    )
    # Two short green ticks per bar marking the bottom and top of the
    # healthy range -- this is what lets you see "in range" at a glance
    # without the axis needing to be in real units.
    min_ticks = alt.Chart(chart_df).mark_tick(color="green", thickness=3, size=40).encode(
        x="metric:N", y="min_pct:Q"
    )
    max_ticks = alt.Chart(chart_df).mark_tick(color="green", thickness=3, size=40).encode(
        x="metric:N", y="max_pct:Q"
    )

    st.altair_chart((bars + min_ticks + max_ticks).properties(height=420), use_container_width=True)
    st.caption(
        f"Bars show your average per day, averaged over {logged_days} day(s) you "
        f"logged in this period. Green ticks mark the healthy min/max from "
        f"HEALTHY_RANGES in the code."
    )


# ---------------------------------------------------------------------------
# Full log, most recent first (whole history, not just the selected period)
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
    column_config={"sugar_g": "Added sugar (g)"},
)
