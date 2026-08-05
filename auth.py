"""
auth.py - Simple shared-password gate
=========================================
This app is for one person (you), not the general public, so a single
shared password is proportional here -- it's meant to stop a random
passerby who finds your public Streamlit URL from poking at your data,
not to withstand a determined attacker. If this ever needs to support
multiple distinct people with separate accounts, that's the point to
switch to Streamlit's built-in st.login() (Google/Microsoft OIDC)
instead of this.

Usage: call require_password() as the very FIRST thing in every page
file (streamlit_app.py and every file inside pages/), before any other
st.* calls. It blocks the rest of the page from rendering until the
correct password has been entered.
"""

import os
import secrets as secrets_module  # aliased to avoid clashing with the word "secrets" used loosely elsewhere

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

APP_PASSWORD = os.environ.get("APP_PASSWORD")


def require_password() -> None:
    """Block the rest of the page until the correct password is entered.

    Uses st.session_state to remember that this browser session already
    authenticated, so you're not asked again every time you switch
    between the Log Meal and Dashboard pages -- only once per session.
    """
    if not APP_PASSWORD:
        st.error(
            "APP_PASSWORD is not set. Add it to your .env locally, and to "
            "your Streamlit Cloud app's Secrets when deployed, before "
            "using the password gate."
        )
        st.stop()

    # Already logged in earlier in this browser session -- let the page
    # continue rendering normally.
    if st.session_state.get("authenticated", False):
        return

    st.title("🔒 Log in")
    entered_password = st.text_input("Password", type="password")

    if st.button("Log in"):
        # secrets.compare_digest avoids leaking timing information about
        # how many characters matched -- a small, cheap habit for any
        # password comparison, even a low-stakes one like this.
        if secrets_module.compare_digest(entered_password, APP_PASSWORD):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    # Nothing below this point in the calling page should render until
    # authenticated -- st.stop() halts execution right here.
    st.stop()
