"""
Tests for RouterService's metadata-driven resource selection and the
DB-track strategy/steps generation.

Two things are covered here:

1. The router doesn't just pick a data source TYPE (DB/FILES/API/
   SPREADSHEET) - the tool schemas in router_service.py (query_database,
   search_documents, call_external_api, query_spreadsheet_data) each
   require a structured resource-selector argument (tables /
   document_codes / tool_name) populated from the live metadata already
   in the router's prompt. TOOL_DISPATCH must forward that selection into
   the corresponding track as a hint_* kwarg - see
   test_tool_dispatch_forwards_metadata_selected_resources_to_each_track
   and test_db_track_forwards_hint_tables_to_bridge_agent.

2. Given the CURRENT metadata a table produces for a question (i.e. the
   `tables` QuerySenseAgent resolves live against the schema, inside the
   DB-track's LangGraph pipeline), _run_db_track() must:
   a. build a `strategy` narration FROM that metadata (naming the tables
      actually used, not a fixed/generic string), and
   b. return the `steps` chain-of-thought produced while resolving it.
   It also locks in the success/failure wording fix: a failed run's
   strategy must say so ("...but the execution failed"), not claim
   success.

run_data_bridge_agent (the actual LangGraph/SQL pipeline) and
finalize_data_source_strategy are mocked so these tests need no live DB,
LLM, or network access - only the routing/aggregation logic in
router_service.py itself is under test.
"""
import os
import sys
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_service


def _fake_bridge_result(tables, steps, sql="SELECT * FROM orders", error=False):
    """Mimics the {chat_ui, cot_logs} shape run_data_bridge_agent returns.
    `tables` stands in for the current table metadata QuerySenseAgent
    resolved from the live DB schema for this question."""
    return {
        "chat_ui": {
            "answer": None if error else "There are 3 orders.",
            "steps": steps,
            "sql": sql,
            "table": [] if error else [{"order_id": 1}, {"order_id": 2}, {"order_id": 3}],
            "chart": {},
            "insights": [],
            "error": error,
        },
        "cot_logs": {
            "query_sense_output": {"tables": tables},
        },
    }


def _ctx():
    return {
        "session_id": "test-session",
        "model_name": "gpt-4o-mini",
        "custom_key": "",
        "system_instructions": "",
        "router_config": {"routing_menu": {"datasources": {"DB": {"tables": {"orders": {}}}}}},
        "feedback_context": "",
        "related_queries": [],
        "self_learning_enabled": False,
        "company_code": None,
        "user_id": 1,
    }


def test_db_track_returns_strategy_and_steps_from_current_table_metadata():
    """Given the tables resolved from current metadata, _run_db_track must
    return a strategy naming exactly those tables, plus the steps produced
    while resolving them."""
    tables = ["orders", "customers"]
    steps = [
        "Query Simplifier Agent - Refined raw query intent: 'orders per customer'.",
        "Query Sense Agent - Mapped database schema entities for tables: ['orders', 'customers'].",
        "SQL Generator Agent - Generated structured query syntax: SELECT * FROM orders JOIN customers ...",
        "Query Formatter Agent - Ran the generated query. Retrieved 3 rows.",
    ]
    fake_result = _fake_bridge_result(tables, steps)

    with patch.object(router_service, "run_data_bridge_agent", return_value=fake_result) as mocked, \
         patch.object(router_service, "finalize_data_source_strategy", return_value=""):
        result = router_service._run_db_track("How many orders per customer?", _ctx())

    mocked.assert_called_once()

    # strategy must be generated FROM the metadata (the resolved tables),
    # not a fixed/generic string - and must name every resolved table.
    assert result["strategy"] == (
        "Generated and executed a SQL query against orders, customers to answer this question."
    )
    for table in tables:
        assert table in result["strategy"]

    # steps must be returned too, and must be exactly the chain-of-thought
    # the pipeline actually produced while resolving that metadata.
    assert result["steps"] == steps
    assert len(result["steps"]) > 0

    assert result["error"] is False
    assert result["sources"] == ["orders<Database>", "customers<Database>"]


def test_db_track_strategy_reports_failure_honestly():
    """A failed run must not claim success in its strategy text."""
    tables = ["orders"]
    steps = ["Query Formatter Agent - Query execution failed: syntax error."]
    fake_result = _fake_bridge_result(tables, steps, error=True)

    with patch.object(router_service, "run_data_bridge_agent", return_value=fake_result), \
         patch.object(router_service, "finalize_data_source_strategy", return_value=""):
        result = router_service._run_db_track("How many orders?", _ctx())

    assert result["error"] is True
    assert result["strategy"] == (
        "Attempted to generate and execute a SQL query against orders but the execution failed."
    )
    assert "orders" in result["strategy"]
    assert result["steps"] == steps


def test_db_track_strategy_falls_back_when_no_tables_resolved():
    """If QuerySenseAgent resolved no tables at all (empty metadata), the
    strategy still returns a valid sentence instead of a dangling
    "against " with nothing named."""
    steps = ["Query Sense Agent - No matching tables found for this question."]
    fake_result = _fake_bridge_result([], steps)

    with patch.object(router_service, "run_data_bridge_agent", return_value=fake_result), \
         patch.object(router_service, "finalize_data_source_strategy", return_value=""):
        result = router_service._run_db_track("Some unanswerable question?", _ctx())

    assert result["strategy"] == "Generated and executed a SQL query to answer this question."
    assert result["sources"] == []
    assert result["steps"] == steps


def test_db_track_forwards_hint_tables_to_bridge_agent():
    """The router's query_database tool call carries a `tables` argument
    populated from the live DB metadata (see the tool's schema in
    router_service.py). _run_db_track must forward it into
    run_data_bridge_agent as hint_tables - this is what lets
    QuerySenseAgent start from the router's metadata-based read of the
    question instead of re-discovering the tables from scratch."""
    fake_result = _fake_bridge_result(["orders", "customers"], ["step"])

    with patch.object(router_service, "run_data_bridge_agent", return_value=fake_result) as mocked, \
         patch.object(router_service, "finalize_data_source_strategy", return_value=""):
        router_service._run_db_track(
            "How many orders per customer?", _ctx(), hint_tables=["orders", "customers"]
        )

    assert mocked.call_args.kwargs["hint_tables"] == ["orders", "customers"]


def test_db_track_defaults_hint_tables_to_empty_list():
    """A missing/None hint must never propagate as None into the bridge
    agent - QuerySenseAgent's schema-validation step expects a list."""
    fake_result = _fake_bridge_result([], ["step"])

    with patch.object(router_service, "run_data_bridge_agent", return_value=fake_result) as mocked, \
         patch.object(router_service, "finalize_data_source_strategy", return_value=""):
        router_service._run_db_track("Some question?", _ctx())

    assert mocked.call_args.kwargs["hint_tables"] == []


def test_tool_dispatch_forwards_metadata_selected_resources_to_each_track():
    """The router's tool-calling schema requires each tool to name the
    SPECIFIC resource - not just the data source type - from metadata:
    query_database/query_spreadsheet_data need `tables`, search_documents
    needs `document_codes`, call_external_api needs `tool_name` (see each
    @tool docstring in router_service.py). This locks in that
    TOOL_DISPATCH actually threads that structured selection into the
    matching track as a hint_* kwarg, not just the free-text `question` -
    i.e. that "which type" and "which specific source" are both decided
    from metadata before the track ever runs."""
    captured = {}

    def _spy(label):
        def _fn(question, ctx, **kwargs):
            captured[label] = {"question": question, **kwargs}
            return {"answer": f"{label} ok"}
        return _fn

    ctx = {"user_query": "fallback question"}

    with patch.object(router_service, "_run_db_track", side_effect=_spy("db")), \
         patch.object(router_service, "_run_files_track", side_effect=_spy("files")), \
         patch.object(router_service, "_run_api_track", side_effect=_spy("api")), \
         patch.object(router_service, "_run_spreadsheet_track", side_effect=_spy("spreadsheet")):

        router_service.TOOL_DISPATCH["query_database"](
            {"question": "orders per customer?", "tables": ["orders", "customers"]}, ctx)
        router_service.TOOL_DISPATCH["search_documents"](
            {"question": "refund policy?", "document_codes": ["DOC-42"]}, ctx)
        router_service.TOOL_DISPATCH["call_external_api"](
            {"question": "current copper price?", "tool_name": "Metal_Price_API"}, ctx)
        router_service.TOOL_DISPATCH["query_spreadsheet_data"](
            {"question": "list metal codes", "tables": ["metal_codes"]}, ctx)

    assert captured["db"] == {"question": "orders per customer?", "hint_tables": ["orders", "customers"]}
    assert captured["files"] == {"question": "refund policy?", "hint_document_codes": ["DOC-42"]}
    assert captured["api"] == {"question": "current copper price?", "hint_tool_name": "Metal_Price_API"}
    assert captured["spreadsheet"] == {"question": "list metal codes", "hint_tables": ["metal_codes"]}


def test_tool_dispatch_defaults_missing_resource_args_safely():
    """A router tool call that omits the resource-selector argument (e.g.
    an older cached prompt, or the model leaving it out) must still
    dispatch - with an empty hint, never a KeyError/None crash."""
    captured = {}

    def _spy(label):
        def _fn(question, ctx, **kwargs):
            captured[label] = kwargs
            return {"answer": "ok"}
        return _fn

    ctx = {"user_query": "fallback question"}
    with patch.object(router_service, "_run_db_track", side_effect=_spy("db")), \
         patch.object(router_service, "_run_api_track", side_effect=_spy("api")):
        router_service.TOOL_DISPATCH["query_database"]({"question": "q"}, ctx)
        router_service.TOOL_DISPATCH["call_external_api"]({"question": "q"}, ctx)

    assert captured["db"] == {"hint_tables": []}
    assert captured["api"] == {"hint_tool_name": ""}
