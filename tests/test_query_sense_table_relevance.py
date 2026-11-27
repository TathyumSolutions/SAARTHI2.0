"""
Tests for QuerySense._relevant_tables - the tables a local model is shown.

Run against the Lending and Manufacturing question banks (regression/),
the old one-point-per-matching-column scoring dropped a table the answer
needed from 10 of 45 prompts: "rejection rate" never reached
production_log.rejected_qty, "POs" (two letters) never reached
purchase_orders, tables with many generic column hits (status, amount,
branch_id) pushed out the one table holding "region", and the bridge
table between two chosen tables was only added if slots were left over.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.databridge_services.agents.query_sense_agent import (
    QuerySenseAgent, _question_acronyms, _stem,
)


def _t(columns, fks=()):
    return {
        "description": "",
        "columns": {c: {"type": "text"} for c in columns},
        "foreign_keys": [{"column": c, "references": r} for c, r in fks],
    }


def _schema():
    return {"tables": {
        "plants": _t(["plant_id", "plant_name", "region", "status"]),
        "products": _t(["product_id", "category", "status"]),
        "production_orders": _t(["production_order_id", "plant_id", "product_id", "order_status", "amount"],
                                [("plant_id", "plants.plant_id"), ("product_id", "products.product_id")]),
        "production_log": _t(["log_id", "production_order_id", "produced_qty", "rejected_qty"],
                             [("production_order_id", "production_orders.production_order_id")]),
        "suppliers": _t(["supplier_id", "plant_id", "status"], [("plant_id", "plants.plant_id")]),
        "employees": _t(["employee_id", "plant_id", "full_name", "status"], [("plant_id", "plants.plant_id")]),
        "purchase_orders": _t(["po_id", "po_number", "supplier_id", "requested_by_employee_id", "status", "amount"],
                              [("supplier_id", "suppliers.supplier_id"),
                               ("requested_by_employee_id", "employees.employee_id")]),
        "payables": _t(["payable_id", "status", "amount", "due_date"]),
        "machines": _t(["machine_id", "plant_id", "status"], [("plant_id", "plants.plant_id")]),
    }}


def _relevant(question, limit=4):
    return QuerySenseAgent(_schema()).query_sense._relevant_tables(question, limit=limit)


def test_stem_meets_inflections():
    assert _stem("rejection") == _stem("rejected") == "reject"
    assert _stem("logged") == "log"
    assert _stem("collected") == _stem("collection")
    assert _stem("region") == "region"


def test_only_capitalised_short_words_are_acronyms():
    assert _question_acronyms("Which POs were late, and the BOM?") == {"po", "bom"}
    assert _question_acronyms("percentage of loans to date") == set()


def test_inflected_word_finds_the_table_holding_the_measure():
    chosen = _relevant("Monthly rejection rate by plant region and product category")
    assert "production_log" in chosen


def test_bridge_table_is_taken_with_the_table_it_connects():
    # production_log reaches plants and products only through production_orders.
    chosen = _relevant("Monthly rejection rate by plant region and product category")
    assert "production_orders" in chosen


def test_acronym_finds_the_table():
    # "PO" abbreviates both order tables; neither is dropped for the other.
    chosen = _relevant("How many POs were raised last month?")
    assert {"purchase_orders", "production_orders"} <= set(chosen)


def test_fk_role_word_finds_the_referenced_table():
    chosen = _relevant("Show each purchase order's supplier and requester", limit=4)
    assert "employees" in chosen


def test_generic_column_words_do_not_outrank_a_specific_one():
    # "status" and "amount" are on most tables; "region" only on plants.
    chosen = _relevant("status and amount totals by region", limit=2)
    assert "plants" in chosen
