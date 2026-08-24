"""
Tests for RouterService's DB-track strategy/steps generation.

These cover the question raised while reviewing router_service.py: given
the CURRENT metadata a table produces for a question (i.e. the `tables`
QuerySenseAgent resolves live against the schema, inside the DB-track's
LangGraph pipeline), _run_db_track() must:

  1. build a `strategy` narration FROM that metadata (naming the tables
     actually used, not a fixed/generic string), and
  2. return the `steps` chain-of-thought produced while resolving it.

It also locks in the success/failure wording fix: a failed run's strategy
must say so ("...but the execution failed"), not claim success.

run_data_bridge_agent (the actual LangGraph/SQL pipeline) and
finalize_data_source_strategy are mocked so this test needs no live DB,
LLM, or network access - only the routing/aggregation logic in
_run_db_track itself is under test.
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
