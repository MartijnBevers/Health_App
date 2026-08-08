"""
insights.py - AI health coach: turn logged data into concrete tips
========================================================================
A single-shot LLM call (no tool-calling needed here -- there's nothing
to execute, just data to interpret). Takes a plain-text summary of a
period's nutrition + exercise data and returns a short list of specific,
numbers-grounded tips.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.4)

SYSTEM_PROMPT = (
    "You are a supportive, practical health coach reviewing someone's "
    "self-logged nutrition and exercise data for a chosen period. "
    "Give 3-5 CONCRETE, SPECIFIC tips grounded in the actual numbers "
    "you're given -- reference real figures (e.g. 'your sodium averaged "
    "2800mg vs a 2300mg target') rather than generic advice. Cover both "
    "diet and exercise where relevant, and prioritize the 1-2 things "
    "that would make the biggest difference rather than listing "
    "everything. Keep it encouraging, not judgmental. Do not diagnose "
    "any condition. If the data is too sparse for the period (e.g. only "
    "one day logged) say so honestly rather than overreaching. Format "
    "as a short numbered list, each tip 1-2 sentences."
)


def generate_health_tips(summary_text: str) -> str:
    """Send a plain-text data summary to the LLM and return its tips."""
    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=summary_text),
        ]
    )
    return response.content