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

from agent import log_meal_from_text
from auth import require_password
from db import init_db

# Must run before anything else renders -- stops the page here if the
# user hasn't entered the correct password yet this session.
require_password()

# Make sure the meals table exists before anything tries to write to it.
# Cheap to call on every page load -- it's a no-op after the first time.
init_db()

st.set_page_config(page_title="Log a meal", page_icon="🍽️")
st.title("🍽️ Log a meal")
st.caption(
    "Describe what you ate in plain language. The agent will log it, "
    "or ask a follow-up question if it needs more detail."
)

description = st.text_input(
    "What did you eat?",
    placeholder="e.g. a bowl of oatmeal with banana and peanut butter",
)

if st.button("Log it", type="primary") and description:
    with st.spinner("Thinking..."):
        messages = log_meal_from_text(description)

    # The last message in the conversation is the tool's result --
    # either a log confirmation from log_meal, or a question from
    # ask_clarification. We show it differently depending on which.
    result_text = messages[-1].content
    if "Clarification needed" in result_text:
        st.warning(result_text)
    else:
        st.success(result_text)

st.divider()

# st.switch_page() navigates to another page in the app when clicked --
# this is what actually changes pages, as opposed to st.page_link which
# just renders a clickable link styled like the sidebar nav.
if st.button("📊 View Dashboard"):
    st.switch_page("pages/1_Dashboard.py")