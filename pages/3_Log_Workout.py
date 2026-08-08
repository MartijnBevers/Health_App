"""
pages/3_Log_Workout.py - Log a strength workout, FitNotes-style
====================================================================
Fast, no-fuss set logging: pick an exercise, type a weight and rep
count, hit Add -- repeat for every set. Writes straight into your own
database, so nothing needs exporting or syncing.
"""

import datetime as dt

import streamlit as st

from auth import require_password
from db import (
    add_exercise_to_catalog,
    delete_strength_set,
    fetch_exercise_catalog,
    fetch_strength_sets,
    init_db,
    insert_strength_set,
)

require_password()
init_db()

st.set_page_config(page_title="Log Workout", page_icon="🏋️")
st.title("🏋️ Log a workout")

session_date = st.date_input("Workout date", value=dt.date.today())
date_str = session_date.isoformat()

catalog = fetch_exercise_catalog()
exercise_names = [e["name"] for e in catalog]
category_by_name = {e["name"]: e["category"] for e in catalog}

ADD_NEW = "+ Add new exercise..."
selected = st.selectbox("Exercise", exercise_names + [ADD_NEW])

if selected == ADD_NEW:
    new_name = st.text_input("New exercise name")
    new_category = st.selectbox(
        "Category", ["Chest", "Back", "Legs", "Shoulders", "Arms", "Core", "Cardio", "Other"]
    )
    if st.button("Add to catalog") and new_name:
        add_exercise_to_catalog(new_name, new_category)
        st.success(f"Added '{new_name}' to your exercise catalog.")
        st.rerun()
    st.stop()

category = category_by_name.get(selected, "Other")

col1, col2 = st.columns(2)
weight_kg = col1.number_input("Weight (kg)", min_value=0.0, step=2.5, value=20.0)
reps = col2.number_input("Reps", min_value=0, step=1, value=8)
notes = st.text_input("Notes (optional)", placeholder="e.g. felt easy, add 2.5kg next time")

if st.button("➕ Add set", type="primary"):
    insert_strength_set(
        date=date_str, exercise=selected, category=category,
        weight_kg=weight_kg, reps=int(reps), notes=notes,
    )
    st.success(f"Logged: {selected} -- {weight_kg}kg x {reps}")
    st.rerun()

st.divider()
st.subheader(f"Session log -- {session_date.strftime('%A, %d %B %Y')}")

sets_today = fetch_strength_sets(date=date_str)
if not sets_today:
    st.info("No sets logged for this day yet.")
else:
    seen_exercises = []
    for s in sets_today:
        if s["exercise"] not in seen_exercises:
            seen_exercises.append(s["exercise"])

    for exercise_name in seen_exercises:
        exercise_sets = [s for s in sets_today if s["exercise"] == exercise_name]
        st.markdown(f"**{exercise_name}**")
        for s in reversed(exercise_sets):
            set_col, delete_col = st.columns([5, 1])
            label = f"{s['weight_kg']}kg x {s['reps']}"
            if s["notes"]:
                label += f" -- _{s['notes']}_"
            set_col.write(label)
            if delete_col.button("🗑️", key=f"del_{s['id']}"):
                delete_strength_set(s["id"])
                st.rerun()