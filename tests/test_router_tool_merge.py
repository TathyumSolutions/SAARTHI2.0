"""Tests for merging router tool calls aimed at the same data source."""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.router_tool_merge import merge_same_source_calls

QUESTION = "On-time delivery % for the 10 lowest suppliers with their home plant"


def _db(question, tables):
    return {"name": "query_database", "args": {"question": question, "tables": tables}, "id": question}


def test_split_db_question_from_failing_run_becomes_one_call():
    calls = [
        _db("on-time delivery percentage per supplier", ["purchase_orders", "suppliers"]),
        _db("home plant for each supplier", ["suppliers", "plants"]),
    ]
    merged, names = merge_same_source_calls(calls, QUESTION)
    assert names == ["query_database"]
    assert len(merged) == 1
    assert merged[0]["name"] == "query_database"
    assert merged[0]["args"]["question"] == QUESTION
    assert merged[0]["args"]["tables"] == ["purchase_orders", "suppliers", "plants"]


def test_single_db_call_is_untouched():
    calls = [_db("count machines by status", ["machines"])]
    merged, names = merge_same_source_calls(calls, "How many machines per status?")
    assert merged == calls
    assert names == []


def test_cross_source_calls_are_not_merged():
    calls = [
        _db("total disbursed amount by product", ["loans"]),
        {"name": "query_spreadsheet_data", "args": {"question": "commission slabs", "tables": ["slabs"]}},
        {"name": "call_external_api", "args": {"question": "USD to INR", "tool_name": "Currency convertor"}},
    ]
    merged, names = merge_same_source_calls(calls, "commission in USD")
    assert merged == calls
    assert names == []


def test_db_calls_merge_but_other_sources_keep_their_place():
    api = {"name": "call_external_api", "args": {"question": "USD to INR", "tool_name": "Currency convertor"}}
    calls = [
        _db("PO value by supplier", ["purchase_orders"]),
        api,
        _db("supplier names", ["suppliers"]),
    ]
    merged, names = merge_same_source_calls(calls, "PO value by supplier in USD")
    assert [c["name"] for c in merged] == ["query_database", "call_external_api"]
    assert merged[0]["args"]["tables"] == ["purchase_orders", "suppliers"]
    assert merged[1] is api


def test_spreadsheet_calls_are_not_merged_by_default():
    calls = [
        {"name": "query_spreadsheet_data", "args": {"question": "a", "tables": ["t1"]}},
        {"name": "query_spreadsheet_data", "args": {"question": "b", "tables": ["t2"]}},
    ]
    merged, names = merge_same_source_calls(calls, "q")
    assert merged == calls and names == []


def test_missing_tables_args_are_handled():
    calls = [
        {"name": "query_database", "args": {"question": "a"}},
        {"name": "query_database", "args": {"question": "b", "tables": None}},
    ]
    merged, _ = merge_same_source_calls(calls, "q")
    assert merged[0]["args"] == {"question": "q", "tables": []}


def test_input_list_is_not_mutated():
    calls = [_db("a", ["t1"]), _db("b", ["t2"])]
    snapshot = [dict(c, args=dict(c["args"])) for c in calls]
    merge_same_source_calls(calls, "q")
    assert calls == snapshot
