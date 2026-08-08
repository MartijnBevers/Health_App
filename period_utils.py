"""
period_utils.py - Shared "Day / Week / Month / All time" date-range logic
==============================================================================
Both the Nutrition Dashboard and Exercise Dashboard need identical
period-navigation behaviour, so it lives here once instead of being
duplicated in every page.
"""

import calendar
import pandas as pd


def get_period_range(view: str, offset: int, all_rows_df: pd.DataFrame):
    """Return (start_date, end_date, label) for the chosen view/offset.

    offset=0 is the current day/week/month. Negative offsets step
    backward (older periods); positive offsets step forward. "All time"
    ignores offset entirely and always spans every row in all_rows_df.
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

    return all_rows_df["date"].min(), all_rows_df["date"].max(), "All time"