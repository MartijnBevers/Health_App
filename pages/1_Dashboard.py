"""
pages/1_Dashboard.py - Health overview dashboard
=====================================================
Redesigned as a compact "oversight" dashboard (inspired by typical
health-checkup dashboard templates):

  1. TOP ROW (3 cards): your general stats (age/height/weight/BMI),
     sleep hours as a bar chart, and today's calories.
  2. MIDDLE: the nutrient breakdown chart you already had, with the
     same Day/Week/Month/All-time navigation.
  3. BOTTOM: an overall health score (donut) + your top 3 tips for the
     selected period -- calculated from how many nutrition metrics and
     your sleep fall inside their healthy ranges.
  4. Full raw log at the very bottom, unchanged.

NOTE: "calories out" (burned via exercise) isn't wired in yet -- see
the comment near CALORIES CARD below for what's needed to add it.
"""

import calendar

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_password
from db import (
    fetch_all_meals,
    fetch_sleep_log,
    get_latest_body_weight_kg,
    get_profile_info,
    init_db,
)

require_password()
st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Health dashboard")
init_db()

# ---------------------------------------------------------------------------
# Load raw data once, up front -- every section below reuses these.
# ---------------------------------------------------------------------------
meals = fetch_all_meals()
df = pd.DataFrame(meals)
if not df.empty:
    # format="mixed" parses each row's timestamp independently instead of
    # assuming they're all identical -- this is the same fix as the crash
    # you hit on the Exercise page, applied here too as a precaution.
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
    df["date"] = df["timestamp"].dt.date

sleep_log = fetch_sleep_log()
sleep_df = pd.DataFrame(sleep_log)
if not sleep_df.empty:
    sleep_df["timestamp"] = pd.to_datetime(sleep_df["timestamp"], format="mixed")
    sleep_df["date"] = sleep_df["timestamp"].dt.date
    # If sleep is ever logged twice in one day, average those entries --
    # otherwise this just returns that single value per day.
    daily_sleep = sleep_df.groupby("date")["hours"].mean().reset_index()
else:
    daily_sleep = pd.DataFrame(columns=["date", "hours"])

profile_info = get_profile_info()
latest_weight = get_latest_body_weight_kg()

# ---------------------------------------------------------------------------
# EDIT THESE to set your own healthy targets -- unchanged from before.
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
SLEEP_TARGET = {"min": 7, "max": 9}


# ===========================================================================
# TOP ROW: general stats | sleep | calories today
# ===========================================================================
stats_col, sleep_col, calories_col = st.columns(3)

with stats_col:
    with st.container(border=True):
        st.markdown("##### 🧍 Your stats")
        row1a, row1b = st.columns(2)
        row1a.metric("Age", profile_info["age"] if profile_info["age"] is not None else "—")
        row1b.metric(
            "Height",
            f"{profile_info['height_cm']:.0f} cm" if profile_info["height_cm"] is not None else "—",
        )
        row2a, row2b = st.columns(2)
        row2a.metric("Weight", f"{latest_weight:.1f} kg" if latest_weight is not None else "—")
        if profile_info["height_cm"] and latest_weight:
            bmi = latest_weight / ((profile_info["height_cm"] / 100) ** 2)
            row2b.metric("BMI", f"{bmi:.1f}")
        else:
            row2b.metric("BMI", "—")
        st.caption("Tell the agent your age/height/weight in chat to update these.")

with sleep_col:
    with st.container(border=True):
        if not daily_sleep.empty:
            last_7_nights = daily_sleep.sort_values("date").tail(7).copy()
            last_7_nights["day_label"] = pd.to_datetime(last_7_nights["date"]).dt.strftime("%a")
            avg_sleep_7d = last_7_nights["hours"].mean()

            st.markdown(f"##### 😴 Sleep — {avg_sleep_7d:.1f}h avg (last 7 nights)")
            sleep_chart = (
                alt.Chart(last_7_nights)
                .mark_bar(color="#4C78A8")
                .encode(
                    x=alt.X("day_label:N", title=None, sort=last_7_nights["day_label"].tolist()),
                    y=alt.Y("hours:Q", title="Hours"),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date"),
                        alt.Tooltip("hours:Q", title="Hours", format=".1f"),
                    ],
                )
                .properties(height=180)
            )
            st.altair_chart(sleep_chart, use_container_width=True)
        else:
            st.markdown("##### 😴 Sleep")
            st.info("No sleep logged yet — tell the agent your sleep hours in chat.")

with calories_col:
    with st.container(border=True):
        st.markdown("##### 🔥 Calories today")
        if not df.empty:
            today = pd.Timestamp.now().date()
            calories_today = df.loc[df["date"] == today, "calories"].sum()
        else:
            calories_today = 0
        st.metric("Consumed", f"{calories_today:.0f} kcal")
        # ---------------------------------------------------------------
        # CALORIES CARD -- "burned" isn't wired up yet.
        # To add it: share the db.py function that fetches exercise
        # sessions (whatever pages/2_Exercise.py and 3_Log_Workout.py
        # call), plus estimation.py, so calories burned today can be
        # summed and shown here as "Burned" + a "Net" = consumed - burned.
        # ---------------------------------------------------------------
        st.caption("Burned (from exercise) — coming soon.")


# ===========================================================================
# MIDDLE: nutrient breakdown chart, with the same period navigation
# ===========================================================================
if df.empty:
    st.info("No meals logged yet -- head to the Log Meal page to add your first one.")
else:
    def get_period_range(view: str, offset: int, all_meals_df: pd.DataFrame):
        """Return (start_date, end_date, label) for the chosen view/offset.

        offset=0 is the current day/week/month. Negative offsets step
        backward (older periods); positive offsets step forward. "All time"
        ignores offset entirely and always spans every logged meal.
        """
        today = pd.Timestamp.now().date()

        if view == "Day":
            day = today + pd.Timedelta(days=offset)
            return day, day, day.strftime("%A, %d %B %Y")

        if view == "Week":
            this_monday = today - pd.Timedelta(days=today.weekday())
            start = this_monday + pd.Timedelta(weeks=offset)
            end = start + pd.Timedelta(days=6)
            return start, end, f"Week of {start:%d %b} \u2013 {end:%d %b %Y}"

        if view == "Month":
            month_index = today.month - 1 + offset
            year = today.year + month_index // 12
            month = month_index % 12 + 1
            start = pd.Timestamp(year=year, month=month, day=1).date()
            last_day_num = calendar.monthrange(year, month)[1]
            end = pd.Timestamp(year=year, month=month, day=last_day_num).date()
            return start, end, start.strftime("%B %Y")

        return all_meals_df["date"].min(), all_meals_df["date"].max(), "All time"

    st.subheader("Nutrition breakdown")

    if "dashboard_offset" not in st.session_state:
        st.session_state.dashboard_offset = 0

    view = st.radio("View", ["Day", "Week", "Month", "All time"], horizontal=True)

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
        nav_label = st.container()

    offset = st.session_state.dashboard_offset
    start_date, end_date, period_label = get_period_range(view, offset, df)
    nav_label.markdown(f"### {period_label}")

    period_df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

    chart_df = pd.DataFrame()  # populated below if there's data, reused by the health score section

    if period_df.empty:
        st.info("No meals logged in this period.")
    else:
        logged_days = period_df["date"].nunique() or 1
        metric_totals = period_df[list(HEALTHY_RANGES.keys())].sum()
        metric_avg_per_day = metric_totals / logged_days

        chart_rows = []
        for column_name, info in HEALTHY_RANGES.items():
            value = metric_avg_per_day[column_name]
            if info.get("per_kg"):
                if latest_weight is None:
                    continue
                value = value / latest_weight
            healthy_max = info["max"]
            healthy_min = info["min"]
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

        if latest_weight is None:
            st.info("Tell the agent your weight in chat to include protein in g/kg/day.")

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

    # =======================================================================
    # BOTTOM: overall health score (donut) + top tips for THIS SAME PERIOD
    # =======================================================================
    def compute_health_score_and_tips(chart_df: pd.DataFrame, sleep_avg_hours: float | None):
        """Score 0-100 = average of how "in range" each metric is, plus
        sleep. Metrics inside their healthy range score 100; metrics
        outside lose points proportional to how far outside they are.

        Also returns up to 3 tips, worst-offending metric first, so the
        person always sees the things most worth fixing.
        """
        scores = []
        tips = []  # (severity, text) -- sorted and trimmed to top 3 below

        for row in chart_df.itertuples():
            if row.healthy_min <= row.value <= row.healthy_max:
                scores.append(100)
                continue
            if row.value < row.healthy_min:
                severity = (row.healthy_min - row.value) / row.healthy_min * 100 if row.healthy_min else 0
                tips.append((severity, f"{row.metric} is below the healthy range — try to increase it."))
            else:
                severity = (row.value - row.healthy_max) / row.healthy_max * 100 if row.healthy_max else 0
                tips.append((severity, f"{row.metric} is above the healthy range — try to reduce it."))
            scores.append(max(0, 100 - severity))

        if sleep_avg_hours is not None:
            if SLEEP_TARGET["min"] <= sleep_avg_hours <= SLEEP_TARGET["max"]:
                scores.append(100)
            else:
                if sleep_avg_hours < SLEEP_TARGET["min"]:
                    severity = (SLEEP_TARGET["min"] - sleep_avg_hours) / SLEEP_TARGET["min"] * 100
                    tips.append((severity, f"You're averaging {sleep_avg_hours:.1f}h sleep — aim for 7-9h."))
                else:
                    severity = (sleep_avg_hours - SLEEP_TARGET["max"]) / SLEEP_TARGET["max"] * 100
                    tips.append((severity, f"You're averaging {sleep_avg_hours:.1f}h sleep — a bit above typical."))
                scores.append(max(0, 100 - severity))

        if not scores:
            return None, []

        overall_score = round(sum(scores) / len(scores))
        tips.sort(key=lambda t: -t[0])
        top_tips = [text for _, text in tips[:3]]
        return overall_score, top_tips

    # Sleep average for the SAME period as the chart above (not just last 7).
    if not daily_sleep.empty:
        period_sleep = daily_sleep[(daily_sleep["date"] >= start_date) & (daily_sleep["date"] <= end_date)]
        period_avg_sleep = period_sleep["hours"].mean() if not period_sleep.empty else None
    else:
        period_avg_sleep = None

    overall_score, top_tips = compute_health_score_and_tips(chart_df, period_avg_sleep)

    st.subheader("Health score")
    with st.container(border=True):
        if overall_score is None:
            st.info("Log some meals and/or sleep in this period to get a health score.")
        else:
            donut_col, tips_col = st.columns([1, 2])

            with donut_col:
                score_df = pd.DataFrame(
                    {"category": ["score", "remaining"], "value": [overall_score, 100 - overall_score]}
                )
                donut = (
                    alt.Chart(score_df)
                    .mark_arc(innerRadius=55, outerRadius=80)
                    .encode(
                        theta="value:Q",
                        color=alt.Color(
                            "category:N",
                            scale=alt.Scale(domain=["score", "remaining"], range=["#4C78A8", "#3a3f4b"]),
                            legend=None,
                        ),
                    )
                    .properties(height=180, width=180)
                )
                st.altair_chart(donut, use_container_width=False)
                status = "Healthy" if overall_score >= 70 else ("Needs attention" if overall_score >= 40 else "At risk")
                st.markdown(f"**{overall_score}/100 — {status}**")

            with tips_col:
                st.markdown("**Top tips for this period:**")
                if top_tips:
                    for tip in top_tips:
                        st.markdown(f"- {tip}")
                else:
                    st.markdown("Everything's within healthy range — nice work!")

    # =======================================================================
    # Full log, most recent first (whole history, not just the period)
    # =======================================================================
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