"""
streamlit_app.py - "Log Meal" page (entry point)
====================================================
This is the page users land on: a free-text box where you describe
what you ate. That description gets sent through the LangGraph agent
(agent.py), which decides whether to log it or ask a follow-up
question.

Once this is deployed on Streamlit Community Cloud, this exact file
runs identically whether it's opened from your phone's browser or your
laptop's -- there's no separate mobile app to build or maintain, it's
just a webpage with a public URL.
"""

import streamlit as st

from auth import require_password
from db import init_db
from agent import run_agent

# Must run before anything else renders -- stops the page here if the
# user hasn't entered the correct password yet this session.
require_password()

# Make sure the meals table exists before anything tries to write to it.
# Cheap to call on every page load -- it's a no-op after the first time.
init_db()

st.set_page_config(page_title="Log meal or exercise", page_icon="📝")
st.title("📝 Log a meal or a workout")
st.caption(
    "Describe what you ate or the exercise you did, in plain language. "
    "The agent will log it, or ask a follow-up question if it needs more detail."
)

description = st.text_input(
    "What did you eat or do?",
    placeholder="e.g. a bowl of oatmeal with banana -- or -- ran 5k in 28 minutes",
)

if st.button("Log it", type="primary") and description:
    with st.spinner("Thinking..."):
        messages = run_agent(description)

    result_message = messages[-1]
    if result_message.name == "ask_clarification":
        st.warning(result_message.content)
    else:
        st.success(result_message.content)

st.divider()

col1, col2 = st.columns(2)
if col1.button("📊 View Nutrition Dashboard"):
    st.switch_page("pages/1_Dashboard.py")
if col2.button("🏃 View Exercise Dashboard"):
    st.switch_page("pages/2_Exercise.py")