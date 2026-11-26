"""The pre-router small-talk shortcut must only catch real small talk."""
import json
import os

import pytest

from app.services.small_talk_classifier import classify_small_talk

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "general_knowledge_config.json"
)

with open(_CONFIG_PATH, encoding="utf-8") as f:
    CFG = json.load(f)["general_knowledge_routing"]


@pytest.mark.parametrize("query", [
    "hi",
    "Hello!",
    "hey there",
    "Thanks a lot",
    "thank you so much",
    "good morning Saarthi",
    "How are you?",
    "What's up",
    "What is today's date?",
    "what time is it",
    "What year is it now?",
])
def test_small_talk_goes_to_general(query):
    assert classify_small_talk(query, CFG) == "GENERAL"


@pytest.mark.parametrize("query", [
    # "they" contains "hey" - the original misroute
    "For each loan product find the provisioning they would need under the IRACP norms doc",
    "Find the provisioning they would need",
    # "hi" inside other words
    "Which Delhi branches have NPAs",
    "this quarter collections",
    # greeting followed by a real request
    "hi, show me loans by branch",
    "thanks, now list the top 5 agents",
    # date phrase inside an analytics question
    "what month had the highest NPA",
    "current month collections total",
    "what year is it in the loans table",
    # digits veto
    "hello 2022",
])
def test_data_questions_are_not_small_talk(query):
    assert classify_small_talk(query, CFG) is None


def test_long_message_never_shortcut():
    query = "hello " + " ".join(["please"] * 20)
    assert classify_small_talk(query, CFG) is None


def test_empty_or_bad_input():
    assert classify_small_talk("", CFG) is None
    assert classify_small_talk("hi", None) is None
    assert classify_small_talk("hi", {}) is None
