"""
agent.py - The LangGraph tool-calling agent
==============================================
This is the same agent from 03/04_*.py -- same two tools, same
branching logic, same graph shape. The only change is that log_meal
now calls insert_meal() from db.py instead of talking to sqlite3
directly. The agent itself doesn't know or care whether that write
ends up in a local file or a hosted Turso database -- that's the whole
benefit of keeping storage behind its own module.

log_meal_from_text() is new: a small wrapper that takes a plain string
and returns the final conversation, so the Streamlit page doesn't need
to know anything about LangChain message objects or graph state.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from db import insert_meal


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool
def log_meal(food: str, calories: int, protein_g: float, meal_type: str) -> str:
    """Log a fully-specified meal to the database.

    Only call this when the meal description gives you enough information
    to confidently estimate the food, calories, protein, and meal type.
    """
    insert_meal(food, calories, protein_g, meal_type)
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
# Model, with tools bound
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
# Graph state
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------------------
# Nodes
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
# Build the graph
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
# Convenience wrapper for the UI
# ---------------------------------------------------------------------------
def log_meal_from_text(description: str) -> list:
    """Run the agent on one free-text meal description.

    Returns the final list of conversation messages so the caller (e.g.
    a Streamlit page) can display the agent's response -- either a log
    confirmation or a clarifying question -- without needing to know
    anything about LangGraph internals.
    """
    initial_state: AgentState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Log this meal: {description}"),
        ]
    }
    final_state = app.invoke(initial_state)
    return final_state["messages"]
