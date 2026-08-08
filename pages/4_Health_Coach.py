"""
pages/4_Health_Coach.py - AI Health Coach
=============================================
Pulls together everything logged for the current Day/Week/Month --
nutrition from meals, plus exercise from chat/Garmin AND the native
Log Workout strength sets -- and asks the LLM for concrete tips.
See insights.py for the actual prompt.
"""

import pandas as pd
import streamlit as st

from auth import require_password
from db import fetch_all_meals, fetch_all_exercises, fetch_strength_sets, get_body_weight_kg, init_db
from estimation import ESTIMATED_MIN_PER_SET, ESTIMATED_KCAL_PER_MIN
from health_ranges import HEALTHY_RANGES
from insights import generate_health_tips
from period_utils import get_period_range

require_password()
init_db()

st.set_page_config(page_title="Health Coach", page_icon="🧭")
st.title("🧭 AI Health Coach")
st.caption("Get concrete tips based on what you've actually logged this period.")

view = st.radio("Period", ["Day", "Week", "Month"], horizontal=True)

# --- Load every data source ---
meals_df = pd.DataFrame(fetch_all_meals())
if not meals_df.empty:
    meals_df["timestamp"] = pd.to_datetime(meals_df["timestamp"])
    meals_df["date"] = meals_df["timestamp"].dt.date

exercise_df = pd.DataFrame(fetch_all_exercises())
if not exercise_df.empty:
    exercise_df["timestamp"] = pd.to_datetime(exercise_df["timestamp"])
    exercise_df["date"] = exercise_df["timestamp"].dt.date

strength_df = pd.DataFrame(fetch_strength_sets())
if not strength_df.empty:
    strength_df["date"] = pd.to_datetime(strength_df["date"]).dt.date

body_weight = get_body_weight_kg()

if meals_df.empty and exercise_df.empty and strength_df.empty:
    st.info("Nothing logged yet -- log a few meals and workouts first.")
    st.stop()

# --- Filter to the CURRENT period (offset=0 -- today/this week/this month) ---
all_dates = pd.concat([
    meals_df[["date"]] if not meals_df.empty else pd.DataFrame(columns=["date"]),
    exercise_df[["date"]] if not exercise_df.empty else pd.DataFrame(columns=["date"]),
    strength_df[["date"]] if not strength_df.empty else pd.DataFrame(columns=["date"]),
])
start_date, end_date, period_label = get_period_range(view, 0, all_dates)
st.markdown(f"### {period_label}")

period_meals = meals_df[(meals_df["date"] >= start_date) & (meals_df["date"] <= end_date)] if not meals_df.empty else meals_df
period_exercise = exercise_df[(exercise_df["date"] >= start_date) & (exercise_df["date"] <= end_date)] if not exercise_df.empty else exercise_df
period_strength = strength_df[(strength_df["date"] >= start_date) & (strength_df["date"] <= end_date)] if not strength_df.empty else strength_df


def build_summary() -> str:
    """Turn the period's data into a compact plain-text summary for the
    LLM -- deliberately just facts/numbers, no advice, so the model does
    all the interpreting itself."""
    lines = [f"Period: {period_label} ({view})"]

    if body_weight:
        lines.append(f"Body weight: {body_weight} kg")

    if not period_meals.empty:
        logged_days = period_meals["date"].nunique()
        lines.append(f"\nNutrition -- logged on {logged_days} day(s):")
        for column, info in HEALTHY_RANGES.items():
            avg_per_day = period_meals[column].sum() / logged_days
            if info.get("per_kg") and body_weight:
                avg_per_day = avg_per_day / body_weight
            lines.append(
                f"- {info['label']}: avg {avg_per_day:.1f}/day "
                f"(healthy range {info['min']}-{info['max']})"
            )
    else:
        lines.append("\nNutrition: no meals logged this period.")

    if not period_exercise.empty:
        lines.append(f"\nCardio/other exercise ({len(period_exercise)} session(s)):")
        by_type = period_exercise.groupby("activity_type").agg(
            sessions=("activity_type", "count"),
            total_minutes=("duration_min", "sum"),
            total_calories=("calories_burned", "sum"),
        )
        for activity_type, row in by_type.iterrows():
            lines.append(
                f"- {activity_type}: {int(row['sessions'])} session(s), "
                f"{row['total_minutes']:.0f} min total, ~{row['total_calories']:.0f} kcal"
            )
    else:
        lines.append("\nCardio/other exercise: none logged this period.")

    if not period_strength.empty:
        sessions = period_strength["date"].nunique()
        total_sets = len(period_strength)
        est_minutes = total_sets * ESTIMATED_MIN_PER_SET
        est_calories = est_minutes * ESTIMATED_KCAL_PER_MIN
        by_category = period_strength.groupby("category").size().sort_values(ascending=False)
        lines.append(
            f"\nStrength training: {sessions} session(s), {total_sets} sets total "
            f"(~{est_minutes:.0f} min, ~{est_calories:.0f} kcal estimated)"
        )
        lines.append(
            "Sets by muscle group: "
            + ", ".join(f"{cat} ({count})" for cat, count in by_category.items())
        )
    else:
        lines.append("\nStrength training: none logged this period.")

    return "\n".join(lines)


summary_text = build_summary()

with st.expander("Data sent to the AI"):
    st.text(summary_text)

if st.button("💡 Get tips", type="primary"):
    with st.spinner("Analyzing your data..."):
        tips = generate_health_tips(summary_text)
    st.markdown(tips)
    st.caption("Not medical advice -- for general guidance only.")