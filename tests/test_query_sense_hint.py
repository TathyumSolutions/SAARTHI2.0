"""
Tests for QuerySenseAgent's use of (a) the router's metadata-based table
hint, (b) self-learning feedback (liked/disliked past questions), and
(c) the user's custom system instructions.

router_service.py's query_database tool call now carries a `tables`
argument - the specific table(s) the router already identified from the
live DB schema metadata (see tests/test_router_strategy.py for the
router-side wiring). This file covers the other end of that hint: does
QuerySenseAgent's own LLM prompt actually get built with it?

_call_llm_for_plan() only accepts the hint as a *starting point*, not a
hard filter - so these tests check the constructed PROMPT text (captured
by mocking the network call) rather than the final table selection, since
the LLM itself is free to add/drop tables from what's hinted.

feedback_context and system_instructions were both already threaded as
far as run_data_bridge_agent's initial_state (see langgraph_agent.py) and
SQLGeneratorAgent already used them correctly - but QuerySenseAgent, the
one step that actually picks tables/columns, never read feedback_context
from state at all, and accepted system_instructions only to silently drop
it before building the prompt. A DISLIKED remark like "picked the wrong
table" or a user's custom formatting instructions therefore had zero
effect on table/column selection. The tests below lock in the fix.
"""
import os
import sys
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.databridge_services.agents.query_sense_agent import QuerySenseAgent


def _schema():
    return {
        "tables": {
            "orders": {"description": "Sales orders", "columns": {"order_id": {}, "customer_id": {}}},
            "customers": {"description": "Customer master", "columns": {"customer_id": {}, "name": {}}},
        }
    }


def _query_sense():
    return QuerySenseAgent.QuerySense(_schema(), ollama_model="llama3", ollama_url="http://ollama:11434/api/generate")


def _mock_ollama_response(json_text):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = {"response": json_text}
    return resp


def test_valid_hint_tables_are_injected_into_the_prompt():
    """A hint naming real schema tables must appear in the prompt sent to
    the model, as a starting point for its own table selection."""
    qs = _query_sense()
    fake_json = '{"tables": ["orders", "customers"], "columns": [], "intent": "SELECTION", "aggregations": [], "group_by": [], "joins": [], "filters": [], "order_by": [], "limit": 0}'

    with patch("requests.post", return_value=_mock_ollama_response(fake_json)) as mocked_post:
        qs._call_llm_for_plan("orders per customer", "llama3", hint_tables=["orders", "customers"])

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "ROUTER-IDENTIFIED TABLE(S)" in sent_prompt
    assert "orders, customers" in sent_prompt


def test_hallucinated_hint_table_is_dropped_not_injected():
    """A hint naming a table that doesn't exist in the live schema (a
    stale or invented name from the router) must never be echoed into the
    prompt as if it were real."""
    qs = _query_sense()
    fake_json = '{"tables": [], "columns": [], "intent": "SELECTION", "aggregations": [], "group_by": [], "joins": [], "filters": [], "order_by": [], "limit": 0}'

    with patch("requests.post", return_value=_mock_ollama_response(fake_json)) as mocked_post:
        qs._call_llm_for_plan("some question", "llama3", hint_tables=["made_up_table"])

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "ROUTER-IDENTIFIED TABLE(S)" not in sent_prompt
    assert "made_up_table" not in sent_prompt


def test_hint_matching_is_case_insensitive_against_the_schema():
    """The router's LLM output may not preserve the schema's exact casing
    - the hint should still be recognized and injected."""
    qs = _query_sense()
    fake_json = '{"tables": ["orders"], "columns": [], "intent": "SELECTION", "aggregations": [], "group_by": [], "joins": [], "filters": [], "order_by": [], "limit": 0}'

    with patch("requests.post", return_value=_mock_ollama_response(fake_json)) as mocked_post:
        qs._call_llm_for_plan("orders question", "llama3", hint_tables=["Orders"])

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "ROUTER-IDENTIFIED TABLE(S)" in sent_prompt
    assert "Orders" in sent_prompt


def test_no_hint_produces_no_hint_block():
    """No hint at all (e.g. the router left `tables` empty) must not add
    an empty/dangling hint section to the prompt."""
    qs = _query_sense()
    fake_json = '{"tables": [], "columns": [], "intent": "SELECTION", "aggregations": [], "group_by": [], "joins": [], "filters": [], "order_by": [], "limit": 0}'

    with patch("requests.post", return_value=_mock_ollama_response(fake_json)) as mocked_post:
        qs._call_llm_for_plan("some question", "llama3")

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "ROUTER-IDENTIFIED TABLE(S)" not in sent_prompt


_VALID_PLAN_JSON = (
    '{"tables": ["orders"], "columns": [], "intent": "SELECTION", "aggregations": [], '
    '"group_by": [], "joins": [], "filters": [], "order_by": [], "limit": 0}'
)

_DISLIKED_FEEDBACK = (
    'COMPANY FEEDBACK CONTEXT:\n'
    '- A similar question was DISLIKED before, with this remark: '
    '"picked the wrong table, should have used customers not orders" - avoid this problem.'
)


def test_disliked_feedback_context_reaches_the_prompt():
    """Self-learning feedback (liked/disliked past questions) must inform
    table/column selection, not just SQL generation downstream - a
    DISLIKED remark about the wrong table being picked has to actually
    reach the step that picks the table."""
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_VALID_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan("orders per customer", "llama3", feedback_context=_DISLIKED_FEEDBACK)

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert _DISLIKED_FEEDBACK in sent_prompt
    assert "DISLIKED note is still relevant" in sent_prompt


def test_no_feedback_context_produces_no_feedback_block():
    """No feedback available must not add a dangling/empty feedback
    section to the prompt."""
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_VALID_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan("orders per customer", "llama3")

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "COMPANY FEEDBACK CONTEXT" not in sent_prompt


def test_system_instructions_reach_the_prompt():
    """system_instructions was previously accepted as a parameter and
    threaded all the way down here, but never actually inserted into the
    prompt - a user's custom persona/formatting instructions had zero
    effect on table/column selection."""
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_VALID_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan(
            "orders per customer", "llama3",
            system_instructions="Always refer to customers as 'clients'.",
        )

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "Always refer to customers as 'clients'." in sent_prompt
    assert "USER CUSTOM FORMATTING INSTRUCTIONS" in sent_prompt


def test_blank_system_instructions_produce_no_block():
    """Whitespace-only system_instructions must not add a dangling
    section to the prompt."""
    qs = _query_sense()
    with patch("requests.post", return_value=_mock_ollama_response(_VALID_PLAN_JSON)) as mocked_post:
        qs._call_llm_for_plan("orders per customer", "llama3", system_instructions="   ")

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert "USER CUSTOM FORMATTING INSTRUCTIONS" not in sent_prompt


def test_execute_threads_state_feedback_context_into_the_prompt():
    """End-to-end through the LangGraph node interface: execute() must
    read state["feedback_context"] (set by run_data_bridge_agent's
    initial_state) and carry it all the way into the LLM prompt, not just
    accept-and-drop it the way system_instructions previously was."""
    agent = QuerySenseAgent(_schema(), ollama_model="llama3", ollama_url="http://ollama:11434/api/generate")
    state = {
        "user_query": "orders per customer",
        "model_name": "llama3",
        "custom_key": "",
        "system_instructions": "",
        "feedback_context": _DISLIKED_FEEDBACK,
        "hint_tables": [],
    }

    with patch("requests.post", return_value=_mock_ollama_response(_VALID_PLAN_JSON)) as mocked_post:
        agent.execute(state)

    sent_prompt = mocked_post.call_args.kwargs["json"]["prompt"]
    assert _DISLIKED_FEEDBACK in sent_prompt
