"""
End-to-end router tests for the two guards that run before/around the
router decision:

- ":as_of"-style placeholders are filled with today's date before any LLM
  sees the question; other placeholders make the router ask the user.
- Several query_database calls for one question are merged into one DB run
  (the failing supplier on-time-delivery run split into two parallel DB
  tracks that both timed out on a local Ollama).

The router LLM and the DB track are mocked - only router_service's own
orchestration is under test.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_service
from app.services.router_llm import RouterModel

_FAKE_ROUTER_MODEL = RouterModel(label="gpt-4o-mini", provider="openai", chat_model=MagicMock())

QUESTION = ("For each supplier with at least 3 received POs in the 12 months to :as_of, what is the "
            "on-time delivery percentage? List the 10 lowest with their home plant.")

DB_RESULT = {
    "answer": "Lowest on-time suppliers listed.", "steps": ["db step"], "sql": "SELECT ...",
    "table": [{"supplier_name": "A", "on_time_pct": 40.0, "plant_name": "P1"}],
    "chart": {}, "insights": [], "error": False, "strategy": "s",
    "sources": ["purchase_orders<Database>"], "main_query": "SELECT ...", "related_queries": [],
}


def _run(question, router_calls):
    seen = {"db_calls": [], "router_prompts": []}

    def fake_invoke(llm, messages, *, purpose, **kwargs):
        if purpose == "router.decision":
            return SimpleNamespace(content="", tool_calls=router_calls)
        raise AssertionError(f"unexpected LLM call {purpose}")

    def fake_build_messages(user_query, *args, **kwargs):
        seen["router_prompts"].append(user_query)
        return []

    def fake_db(args, ctx):
        seen["db_calls"].append(args)
        return dict(DB_RESULT)

    dispatch = dict(router_service.TOOL_DISPATCH)
    dispatch["query_database"] = fake_db
    with patch.object(router_service, "tracked_invoke", side_effect=fake_invoke), \
         patch.object(router_service, "TOOL_DISPATCH", dispatch), \
         patch.object(router_service, "_load_router_config", return_value={"routing_menu": {"datasources": {}}}), \
         patch.object(router_service, "fetch_and_translate_tools", return_value=[]), \
         patch.object(router_service, "load_rag_config", return_value={"self_learning": {"enabled": False}}), \
         patch.object(router_service, "_build_router_messages", side_effect=fake_build_messages), \
         patch.object(router_service, "_log_query", return_value="Q0001"), \
         patch.object(router_service, "select_router_model", return_value=_FAKE_ROUTER_MODEL):
        response = router_service.RouterService().get_smart_response(question, session_id="guards")
    return response, seen


def test_split_db_calls_run_as_one_db_track_with_placeholder_filled():
    router_calls = [
        {"name": "query_database", "args": {"question": "on-time % per supplier",
                                            "tables": ["purchase_orders", "suppliers"]}},
        {"name": "query_database", "args": {"question": "home plant per supplier",
                                            "tables": ["suppliers", "plants"]}},
    ]
    response, seen = _run(QUESTION, router_calls)

    assert len(seen["db_calls"]) == 1
    db_args = seen["db_calls"][0]
    assert db_args["tables"] == ["purchase_orders", "suppliers", "plants"]
    assert ":as_of" not in db_args["question"]
    assert ":as_of" not in seen["router_prompts"][0]
    assert response["router_decision"] == "DB"
    assert response["table"] == DB_RESULT["table"]


def test_unknown_placeholder_asks_the_user_without_calling_any_source():
    response, seen = _run("Downtime hours at :plant last month", router_calls=[])
    assert ":plant" in response["answer"]
    assert seen["router_prompts"] == []
    assert seen["db_calls"] == []
