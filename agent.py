"""
agent.py - The LangGraph tool-calling agent
==============================================
This agent now has THREE tools instead of two: log_meal, log_exercise,
and ask_clarification. The model picks whichever fits your message --
you don't need a separate box for exercise vs. food, it reads the
description and decides. Each ToolMessage is tagged with `name=` so the
UI (streamlit_app.py) can tell which tool fired without parsing text.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing import Optional

from db import (
    insert_meal,
    log_body_weight,
    log_sleep,
    set_profile_info,
)

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

    Only call this when the message describes FOOD, and gives you enough
    information to confidently estimate ALL of: food, calories, protein,
    meal type, fiber, saturated fat, added sugar, sodium, and fruit/
    vegetable servings.

    Field notes for your estimates:
    - fiber_g: grams of dietary fiber.
    - added_sugar_g: grams of added sugar, excluding sugars naturally
      present in fruit, milk, and other unsweetened foods.
    - saturated_fat_g: grams of saturated fat specifically (not total fat).
    - sodium_mg: milligrams of sodium.
    - fruit_veg_servings: roughly how many standard servings of fruit or
      vegetables are in this meal (e.g. a side salad ~= 1, a plain grain
      bowl with no produce ~= 0). Estimate to the nearest 0.5.

    It's fine to estimate 0 for any of these that genuinely don't apply.
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
def log_exercise(
    activity_type: str,
    duration_min: float,
    calories_burned: int,
    intensity: str,
) -> str:
    """Log a workout/exercise session to the database.

    Only call this when the message describes PHYSICAL EXERCISE (e.g.
    "ran 5k in 30 minutes", "did an hour of weightlifting", "30 min
    yoga session"), and you can confidently estimate calories burned
    and intensity from the activity type and duration.

    Field notes for your estimates:
    - activity_type: a short label, e.g. "running", "strength_training",
      "cycling", "yoga", "swimming".
    - calories_burned: estimate using typical calorie-burn rates for an
      average adult doing that activity at that duration/intensity.
    - intensity: one of "low", "moderate", or "high", based on how
      strenuous the activity typically is (e.g. a light walk = low,
      an easy jog = moderate, HIIT or hard running = high).
    """
    insert_exercise(
        source="chat",
        activity_type=activity_type,
        duration_min=duration_min,
        calories_burned=calories_burned,
        intensity=intensity,
    )
    return (
        f"Logged: {activity_type} for {duration_min} min ({intensity} intensity) "
        f"-- ~{calories_burned} kcal burned."
    )


@tool
def ask_clarification(question: str) -> str:
    """Ask the user a clarifying question instead of logging anything.

    Call this when the message is too vague to confidently log as either
    a meal or exercise -- e.g. missing what the food/activity actually
    was, or giving no usable detail at all (like "I did something earlier").
    """
    return f"[Clarification needed]: {question}"

@tool
def log_body_weight_tool(weight_kg: float) -> str:
    """Log the user's current body weight in kilograms.

    Call this whenever the user reports their weight, e.g. "I weigh 82kg
    today" or "log my weight as 81.5". Each call adds a new dated entry
    so weight can be tracked as a trend over time -- it never overwrites
    a previous entry.
    """
    log_body_weight(weight_kg)
    return f"Logged body weight: {weight_kg} kg."


@tool
def log_sleep_tool(hours: float) -> str:
    """Log how many hours the user slept.

    Call this whenever the user reports sleep, e.g. "I slept 7.5 hours"
    or "got 6 hours last night". Each call adds a new dated entry so
    sleep can be tracked as a trend over time.
    """
    log_sleep(hours)
    return f"Logged sleep: {hours} hours."


@tool
def update_profile(age: Optional[int] = None, height_cm: Optional[float] = None) -> str:
    """Update the user's age and/or height.

    Call this when the user states their age or height, e.g. "I'm 23
    years old" or "I'm 181cm tall". Pass only the field(s) the user
    actually mentioned and leave the other as None -- age and height
    don't need history, just the current value, so this overwrites
    rather than appending.
    """
    set_profile_info(age=age, height_cm=height_cm)
    changes = []
    if age is not None:
        changes.append(f"age = {age}")
    if height_cm is not None:
        changes.append(f"height = {height_cm} cm")
    return f"Updated profile: {', '.join(changes) if changes else 'nothing provided'}."


tools = [log_meal, ask_clarification, log_body_weight_tool, log_sleep_tool, update_profile]
tools_by_name = {t.name: t for t in tools}


# ---------------------------------------------------------------------------
# Model, with tools bound
# ---------------------------------------------------------------------------
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)
llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = (
    "You are a personal health-tracking assistant with these tools: "
    "log_meal, ask_clarification, log_body_weight_tool, log_sleep_tool, "
    "and update_profile. "
    "Call log_meal only if you can produce a reasonably confident estimate "
    "of calories, protein, fiber, saturated fat, added sugar, sodium, "
    "fruit/vegetable servings, and meal type from the description. "
    "Call log_body_weight_tool whenever the user reports their weight, "
    "log_sleep_tool whenever they report hours slept, and update_profile "
    "whenever they state their age or height. "
    "If a message is too vague to act on responsibly, call "
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
    """Run whichever tool the model chose and append the result.

    The ToolMessage is tagged with name=tool_call["name"] -- this is what
    lets streamlit_app.py tell whether a meal, an exercise, or a
    clarification question was produced, without parsing the text.
    """
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]
    selected_tool = tools_by_name[tool_call["name"]]
    result = selected_tool.invoke(tool_call["args"])
    tool_message = ToolMessage(
        content=result,
        tool_call_id=tool_call["id"],
        name=tool_call["name"],
    )
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
graph_builder.add_node("log_exercise", execute_tool)
graph_builder.add_node("ask_clarification", execute_tool)
graph_builder.add_node("log_body_weight_tool", execute_tool)
graph_builder.add_node("log_sleep_tool", execute_tool)
graph_builder.add_node("update_profile", execute_tool)

graph_builder.add_edge(START, "call_model")
graph_builder.add_conditional_edges(
    "call_model",
    route_after_model,
    {
        "log_meal": "log_meal",
        "ask_clarification": "ask_clarification",
        "log_body_weight_tool": "log_body_weight_tool",
        "log_sleep_tool": "log_sleep_tool",
        "update_profile": "update_profile",
    },
)
graph_builder.add_edge("log_meal", END)
graph_builder.add_edge("log_exercise", END)
graph_builder.add_edge("ask_clarification", END)
graph_builder.add_edge("log_body_weight_tool", END)
graph_builder.add_edge("log_sleep_tool", END)
graph_builder.add_edge("update_profile", END)

app = graph_builder.compile()


# ---------------------------------------------------------------------------
# Convenience wrapper for the UI
# ---------------------------------------------------------------------------
def run_agent(description: str) -> list:
    """Run the agent on one free-text message describing food OR exercise.

    Returns the final list of conversation messages so the caller (e.g.
    a Streamlit page) can display the agent's response -- a meal log, an
    exercise log, or a clarifying question -- by checking messages[-1].name.
    """
    initial_state: AgentState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=description),
        ]
    }
    final_state = app.invoke(initial_state)
    return final_state["messages"]