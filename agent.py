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
def log_meal(
    food: str,
    calories: int,
    protein_g: float,
    meal_type: str,
    fiber_g: float,
    saturated_fat_g: float,
    added_sugar_g: float,
    sodium_mg: float,
    fruit_veg_servings: float,
) -> str:
    """Log a fully-specified meal to the database.

    Only call this when the meal description gives you enough information
    to confidently estimate ALL of: food, calories, protein, meal type,
    fiber, saturated fat, added sugar, sodium, and fruit/vegetable servings.

    Field notes for your estimates:
    - fiber_g: grams of dietary fiber.
    - added_sugar_g: grams of added sugar, excluding sugars naturally
      present in fruit, milk, and other unsweetened foods.
    - saturated_fat_g: grams of saturated fat specifically (not total fat).
    - sodium_mg: milligrams of sodium.
    - fruit_veg_servings: roughly how many standard servings of fruit or
      vegetables are in this meal (e.g. a side salad ~= 1, a plain grain
      bowl with no produce ~= 0). Estimate to the nearest 0.5.

    It's fine to estimate 0 for any of these that genuinely don't apply
    (e.g. fruit_veg_servings=0 for a food with no fruit or vegetables).
    """
    insert_meal(
        food=food,
        calories=calories,
        protein_g=protein_g,
        meal_type=meal_type,
        fiber_g=fiber_g,
        saturated_fat_g=saturated_fat_g,
        sugar_g=added_sugar_g,
        sodium_mg=sodium_mg,
        fruit_veg_servings=fruit_veg_servings,
    )
    return (
        f"Logged: {food} as {meal_type} -- {calories} kcal, {protein_g}g protein, "
        f"{fiber_g}g fiber, {saturated_fat_g}g sat fat, {added_sugar_g}g added sugar, "
        f"{sodium_mg}mg sodium, {fruit_veg_servings} fruit/veg servings."
    )


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
    "of calories, protein, fiber, saturated fat, added sugar, sodium, "
    "fruit/vegetable servings, and meal type from the description. "
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
