"""
End-to-end test of the router's multi-source path with the Result
Combiner wired in: the router picks the database AND the spreadsheet, each
track returns its own table, and the final response must carry the
combined table (with the computed commission), the grand totals, a chart
of the computed figure, and a stored strategy saying how the sources were
joined and what was computed.

Every LLM call (router decision, combine plan, answer synthesis) and both
tracks are mocked - only router_service's own orchestration is under test.
"""
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_service

QUESTION = ("What was the total disbursed amount, and what commission would be payable "
            "if every loan were paid at the lowest slab rate?")

DB_RESULT = {
    "answer": "Home Loan leads disbursements.", "steps": ["db step"], "sql": "SELECT ...",
    "table": [{"product_name": "Home Loan", "total_disbursed": 8080000000.0},
              {"product_name": "Gold Loan", "total_disbursed": 1000000000.0}],
    "chart": {"bar": {"only": "db rows"}}, "insights": [], "error": False,
    "strategy": "Generated and executed a SQL query against loans, loan_products to answer this question.",
    "sources": ["loans<Database>"], "main_query": "SELECT ...",
    "child_query": "total disbursed amount by product", "related_queries": [],
}
SHEET_RESULT = {
    "answer": "Lowest slab rates range from 0.64% to 0.74%.", "steps": ["sheet step"], "sql": None,
    "table": [{"product_code": "GL", "product_name": "Gold Loan", "slab_lt_rs_10l_qtr": 0.74, "slab_gt_rs_2cr_qtr": 1.29},
              {"product_code": "HL", "product_name": "Home Loan", "slab_lt_rs_10l_qtr": 0.65, "slab_gt_rs_2cr_qtr": 1.2}],
    "chart": {}, "insights": [],
    "strategy": "Queried your uploaded spreadsheet data (agent_commission) to answer this question.",
    "sources": ["agent_commission<Spreadsheet>"], "main_query": "{\"tables\": [\"agent_commission\"]}",
    "child_query": "commission slab rates by product", "related_queries": [],
}
PLAN = {
    "joins": [{"left": "db", "right": "sheet", "left_on": "product_name", "right_on": "product_name", "how": "left"}],
    "row_ops": [{"as": "lowest_slab_rate", "func": "min", "columns": ["slab_lt_rs_10l_qtr", "slab_gt_rs_2cr_qtr"]}],
    "derived": [{"as": "commission_at_lowest_slab", "op": "percent_of", "args": ["total_disbursed", "lowest_slab_rate"]}],
    "totals": ["total_disbursed", "commission_at_lowest_slab"],
}


def _fake_tracked_invoke(llm, messages, *, purpose, **kwargs):
    if purpose == "router.decision":
        return SimpleNamespace(content="", tool_calls=[
            {"name": "query_database", "args": {"question": DB_RESULT["child_query"], "tables": ["loans"]}},
            {"name": "query_spreadsheet_data", "args": {"question": SHEET_RESULT["child_query"],
                                                        "tables": ["agent_commission"]}},
        ])
    if purpose == "router.result_combiner":
        return SimpleNamespace(content=json.dumps(PLAN))
    if purpose == "router.multi_source_synthesis":
        _fake_tracked_invoke.synthesis_prompt = messages[0].content
        return SimpleNamespace(content="Total disbursed is 9.08 billion; commission at the lowest slab is 59.92 million.")
    raise AssertionError(f"unexpected LLM call {purpose}")


def test_db_plus_spreadsheet_answer_is_combined_computed_and_logged():
    logged = {}

    def fake_log_query(user_id, company_code, question, router_decision, answer, strategy, sources,
                       main_query, **kwargs):
        logged.update(router_decision=router_decision, strategy=strategy, main_query=main_query, sources=sources)
        return "Q0001"

    dispatch = dict(router_service.TOOL_DISPATCH)
    dispatch["query_database"] = lambda args, ctx: dict(DB_RESULT)
    dispatch["query_spreadsheet_data"] = lambda args, ctx: dict(SHEET_RESULT)

    with patch.object(router_service, "tracked_invoke", side_effect=_fake_tracked_invoke), \
         patch.object(router_service, "TOOL_DISPATCH", dispatch), \
         patch.object(router_service, "_load_router_config", return_value={"routing_menu": {"datasources": {}}}), \
         patch.object(router_service, "fetch_and_translate_tools", return_value=[]), \
         patch.object(router_service, "load_rag_config", return_value={"self_learning": {"enabled": False}}), \
         patch.object(router_service, "_build_router_messages", return_value=[]), \
         patch.object(router_service, "_log_query", side_effect=fake_log_query), \
         patch.object(router_service, "_generate_chart_for_merged_table",
                      return_value={"bar": {"combined": True}}) as chart_gen, \
         patch.object(router_service, "ChatOpenAI"):
        response = router_service.RouterService().get_smart_response(QUESTION, session_id="s1")

    assert response["router_decision"] == "MULTI"
    rows = {r["product_name"]: r for r in response["table"]}
    assert rows["Home Loan"]["commission_at_lowest_slab"] == 8080000000.0 * 0.65 / 100
    assert rows["Gold Loan"]["commission_at_lowest_slab"] == 1000000000.0 * 0.74 / 100
    assert response["totals"]["commission_at_lowest_slab"] == round(52520000.0 + 7400000.0, 2)

    # The chart is rebuilt from the combined rows, plotting the computed figure -
    # not the DB track's own chart of disbursed amount only.
    assert response["chart"] == {"bar": {"combined": True}}
    assert chart_gen.call_args.kwargs["preferred_measure"] == "commission_at_lowest_slab"

    # The synthesis model is handed the code-computed figures to report.
    assert "[Combined result - computed exactly by code" in _fake_tracked_invoke.synthesis_prompt
    assert "commission_at_lowest_slab" in _fake_tracked_invoke.synthesis_prompt

    # The stored strategy says how the sources were combined.
    assert logged["router_decision"] == "MULTI"
    assert "Result Combiner" in logged["strategy"]
    assert "Joined database.product_name to spreadsheet.product_name" in logged["strategy"]
    assert "commission_at_lowest_slab = total_disbursed × lowest_slab_rate ÷ 100" in logged["strategy"]
    assert "Result Combiner plan:" in logged["main_query"]
    assert any("Combining Results" in s for s in response["steps"])


def test_spreadsheet_only_answer_is_logged_as_spreadsheet():
    logged = {}

    def fake_invoke(llm, messages, *, purpose, **kwargs):
        return SimpleNamespace(content="", tool_calls=[
            {"name": "query_spreadsheet_data", "args": {"question": "rates", "tables": ["agent_commission"]}}])

    dispatch = dict(router_service.TOOL_DISPATCH)
    dispatch["query_spreadsheet_data"] = lambda args, ctx: dict(SHEET_RESULT)
    with patch.object(router_service, "tracked_invoke", side_effect=fake_invoke), \
         patch.object(router_service, "TOOL_DISPATCH", dispatch), \
         patch.object(router_service, "_load_router_config", return_value={"routing_menu": {"datasources": {}}}), \
         patch.object(router_service, "fetch_and_translate_tools", return_value=[]), \
         patch.object(router_service, "load_rag_config", return_value={"self_learning": {"enabled": False}}), \
         patch.object(router_service, "_build_router_messages", return_value=[]), \
         patch.object(router_service, "_log_query",
                      side_effect=lambda *a, **k: logged.setdefault("decision", a[3]) and "Q2"), \
         patch.object(router_service, "ChatOpenAI"):
        response = router_service.RouterService().get_smart_response("slab rates", session_id="s2")

    # Previously fell through to "GENERAL", so spreadsheet answers could
    # never be found again for self-learning reuse (which looks for SPREADSHEET).
    assert response["router_decision"] == "SPREADSHEET"
    assert logged["decision"] == "SPREADSHEET"
