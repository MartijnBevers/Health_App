"""
Step 4 - Real persistence: SQLite instead of a dummy list
=============================================================

This script builds directly on 03_dummy_tool_agent.py. The agent loop,
the two tools, and the branching logic are UNCHANGED -- that's the point.
Because log_meal was already its own isolated function with a clear job
("take these fields, persist them somewhere"), swapping its storage
backend from a Python list to a SQLite database doesn't touch anything
else in the graph.

What's new:
  - init_db()      creates a `meals` table (if it doesn't already exist)
                    in a local SQLite file, meal_log.db
  - log_meal(...)  now INSERTs a row into that table instead of
                    appending to an in-memory list
  - fetch_all_meals() reads everything back out, so we can confirm the
                    writes actually landed on disk

Setup: same as before, plus no new packages -- sqlite3 is in the Python
standard library.
    pip install langgraph langchain langchain-groq python-dotenv
    GROQ_API_KEY=your-key-here   in a .env file in this folder
"""

import sqlite3
from datetime import datetime
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# Reads the .env file and loads GROQ_API_KEY into the environment.
load_dotenv()


# ---------------------------------------------------------------------------
# 1. SQLite setup
# ---------------------------------------------------------------------------
# All meal logs live in this local file. Using a file (not :memory:) means
# data survives between runs -- try running this script twice and watch
# the second run's printout include the first run's entries too.
DB_PATH = "meal_log.db"


def init_db() -> None:
    """Create the `meals` table if it doesn't already exist.

    Safe to call every time the script starts -- CREATE TABLE IF NOT
    EXISTS is a no-op if the table is already there, so this never wipes
    existing data.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                food         TEXT NOT NULL,
                calories     INTEGER NOT NULL,
                protein_g    REAL NOT NULL,
                meal_type    TEXT NOT NULL
            )
            """
        )
        # `with` handles commit automatically on successful exit.


def fetch_all_meals() -> list[dict]:
    """Read every row out of the meals table, most recent first.

    Used at the end of the script to confirm the tool's writes actually
    persisted to disk (as opposed to just living in Python memory).
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row  # lets us access columns by name
        rows = conn.execute(
            "SELECT * FROM meals ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 2. Tools
# ---------------------------------------------------------------------------
@tool
def log_meal(food: str, calories: int, protein_g: float, meal_type: str) -> str:
    """Log a fully-specified meal to the database.

    Only call this when the meal description gives you enough information
    to confidently estimate the food, calories, protein, and meal type.
    """
    # INSERT the meal as a new row. Using `?` placeholders (rather than
    # f-string formatting) avoids SQL injection -- always do this even
    # for a personal project, it costs nothing and it's the right habit.
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO meals (timestamp, food, calories, protein_g, meal_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                food,
                calories,
                protein_g,
                meal_type,
            ),
        )
    return f"Logged: {food} ({calories} kcal, {protein_g}g protein) as {meal_type}."


@tool
def ask_clarification(question: str) -> str:
    """Ask the user a clarifying question instead of logging a meal.

    Call this when the meal description is too vague to confidently
    estimate nutrition info -- e.g. missing what the food actually is,
    or giving no usable detail at all (like "I ate something earlier").
    """
    return f"[Clarification needed]: {question}"


tools = [log_meal, ask_clarification]
tools_by_name = {t.name: t for t in tools}


# ---------------------------------------------------------------------------
# 3. Model, with tools bound -- unchanged from Step 3
# ---------------------------------------------------------------------------
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)
llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = (
    "You are a nutrition-logging assistant with two tools available: "
    "log_meal and ask_clarification. "
    "Call log_meal only if you can produce a reasonably confident estimate "
    "of calories, protein, food, and meal type from the description. "
    "If the description is too vague to do that responsibly, call "
    "ask_clarification instead of guessing."
)


# ---------------------------------------------------------------------------
# 4. Graph state -- unchanged from Step 3
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------------------
# 5. Nodes -- unchanged from Step 3
# ---------------------------------------------------------------------------
def call_model(state: AgentState) -> dict:
    """Send the conversation so far to the LLM and let it choose a tool."""
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def execute_tool(state: AgentState) -> dict:
    """Run whichever tool the model chose and append the result."""
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]
    selected_tool = tools_by_name[tool_call["name"]]
    result = selected_tool.invoke(tool_call["args"])
    tool_message = ToolMessage(content=result, tool_call_id=tool_call["id"])
    return {"messages": [tool_message]}


def route_after_model(state: AgentState) -> str:
    """Branch based on which tool the model picked."""
    last_message = state["messages"][-1]
    return last_message.tool_calls[0]["name"]


# ---------------------------------------------------------------------------
# 6. Build the graph -- unchanged from Step 3
# ---------------------------------------------------------------------------
graph_builder = StateGraph(AgentState)
graph_builder.add_node("call_model", call_model)
graph_builder.add_node("log_meal", execute_tool)
graph_builder.add_node("ask_clarification", execute_tool)

graph_builder.add_edge(START, "call_model")
graph_builder.add_conditional_edges(
    "call_model",
    route_after_model,
    {"log_meal": "log_meal", "ask_clarification": "ask_clarification"},
)
graph_builder.add_edge("log_meal", END)
graph_builder.add_edge("ask_clarification", END)

app = graph_builder.compile()


# ---------------------------------------------------------------------------
# 7. Run it
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Make sure the table exists before the agent tries to write to it.
    init_db()

    test_inputs = [
        "a bowl of oatmeal with banana and peanut butter for breakfast",
        "I ate something earlier",
    ]

    for description in test_inputs:
        initial_state: AgentState = {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=f"Log this meal: {description}"),
            ]
        }

        final_state = app.invoke(initial_state)

        print(f"\nInput: {description}")
        for message in final_state["messages"]:
            role = type(message).__name__
            content = getattr(message, "content", "")
            print(f"  {role}: {content}")

    print(f"\n--- Everything currently in {DB_PATH} ---")
    for row in fetch_all_meals():
        print(row)