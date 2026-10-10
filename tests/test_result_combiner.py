"""
Tests for the Result Combiner (app/services/result_combiner.py): one
DataFrame per data source, joined on the column whose VALUES they share,
with cross-source figures computed by code from a validated JSON plan.

The motivating case: "What was the total disbursed amount, and what
commission would be payable if every loan were paid at the lowest slab
rate?" - disbursed amounts come from the database, slab rates ("0.64%"
text) from an uploaded spreadsheet, and the commission only exists once the
two are joined and multiplied. Previously the tables were only glued
together (sometimes by row position) and the arithmetic was left to the
answer-writing LLM, which skipped it.

Also carries over the earlier merge guarantees: a same-named column whose
values never match (DB "M00123" vs spreadsheet "MAT-00123") must not count
as a join, and must be reported so synthesis doesn't present an unrelated
field as the missing data.
"""
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pandas as pd

from app.services.result_combiner import (
    CombinePlanError, combine_results, find_key_candidates, validate_plan,
)

DB = ("query_database", {
    "child_query": "total disbursed amount by product",
    "table": [  # sorted by amount, like the real SQL result
        {"product_name": "Loan Against Property", "total_disbursed": 8085000000.0},
        {"product_name": "Home Loan", "total_disbursed": 8080000000.0},
        {"product_name": "New Car Loan", "total_disbursed": 6650000000.0},
        {"product_name": "Consumer Durable Loan", "total_disbursed": 919000000.0},
    ],
})
SHEET = ("query_spreadsheet_data", {
    "child_query": "commission slab rates by product",
    "table": [  # sheet order, rates as text, a stray notes row at the end
        {"product_code": "HL", "product_name": "Home Loan", "slab_lt_rs_10l_qtr": "0.65%", "slab_gt_rs_2cr_qtr": "1.2%"},
        {"product_code": "LAP", "product_name": "Loan Against Property", "slab_lt_rs_10l_qtr": "0.74%", "slab_gt_rs_2cr_qtr": "1.29%"},
        {"product_code": "NCL", "product_name": "New Car Loan", "slab_lt_rs_10l_qtr": "0.72%", "slab_gt_rs_2cr_qtr": "1.27%"},
        {"product_code": "CD", "product_name": "Consumer Durable Loan", "slab_lt_rs_10l_qtr": "0.7%", "slab_gt_rs_2cr_qtr": "1.25%"},
        {"product_code": "Notes", "product_name": None, "slab_lt_rs_10l_qtr": None, "slab_gt_rs_2cr_qtr": None},
    ],
})

COMMISSION_PLAN = {
    "joins": [{"left": "db", "right": "sheet", "left_on": "product_name", "right_on": "product_name", "how": "left"}],
    "row_ops": [{"as": "lowest_slab_rate", "func": "min",
                 "columns": ["slab_lt_rs_10l_qtr", "slab_gt_rs_2cr_qtr"]}],
    "derived": [{"as": "commission_at_lowest_slab", "op": "percent_of",
                 "args": ["total_disbursed", "lowest_slab_rate"]}],
    "totals": ["total_disbursed", "commission_at_lowest_slab"],
}


def test_commission_at_lowest_slab_is_computed_by_code_and_totalled():
    prompts = []

    def fake_llm(prompt):
        prompts.append(prompt)
        return json.dumps(COMMISSION_PLAN)

    out = combine_results([DB, SHEET], "commission at lowest slab", llm_invoke=fake_llm)

    assert out["planned_by"] == "llm"
    assert out["base"] == "query_database"
    rows = {r["product_name"]: r for r in out["table"]}
    assert len(out["table"]) == 4  # the "Notes" row never became data
    assert rows["Home Loan"]["lowest_slab_rate"] == 0.65  # "0.65%" -> 0.65
    assert rows["Home Loan"]["commission_at_lowest_slab"] == 8080000000.0 * 0.65 / 100
    assert rows["Loan Against Property"]["commission_at_lowest_slab"] == 8085000000.0 * 0.74 / 100
    # Rows keep the DB's order (not glued by position to the sheet's order).
    assert [r["product_name"] for r in out["table"]][0] == "Loan Against Property"
    # The sheet's duplicate copy of the join column is dropped.
    assert "product_name_sheet" not in out["table"][0]
    assert out["totals"]["commission_at_lowest_slab"] == round(
        (8085000000 * 0.74 + 8080000000 * 0.65 + 6650000000 * 0.72 + 919000000 * 0.7) / 100, 2)
    stats = out["join_stats"][0]
    assert (stats["left_on"], stats["right_on"], stats["matched"], stats["left_rows"]) == (
        "product_name", "product_name", 4, 4)
    # The strategy records the join, the formula and the totals.
    assert "product_name" in out["strategy"]
    assert "commission_at_lowest_slab = total_disbursed × lowest_slab_rate ÷ 100" in out["strategy"]
    assert "Totals:" in out["strategy"]
    # The planner only ever sees value-verified key candidates.
    assert "product_name = product_name" in prompts[0]


def test_join_key_is_found_from_values_when_column_names_differ():
    left = pd.DataFrame({"loan_type": ["Home Loan", "Gold Loan"], "amount": [10.5, 20.25]})
    right = pd.DataFrame({"product_name": ["gold loan", "HOME LOAN ", "Personal Loan"], "rate": [0.74, 0.65, 0.64]})
    cands = find_key_candidates(left, right)
    assert cands[0]["left_on"] == "loan_type" and cands[0]["right_on"] == "product_name"
    assert cands[0]["matched_values"] == 2
    # Measures (fractional floats) are never offered as keys.
    assert all(c["left_on"] != "amount" for c in cands)


def test_plan_with_an_unverified_join_key_is_rejected_and_fallback_join_runs():
    bad = dict(COMMISSION_PLAN, joins=[{"left": "db", "right": "sheet", "left_on": "total_disbursed",
                                        "right_on": "product_code", "how": "left"}])
    out = combine_results([DB, SHEET], "q", llm_invoke=lambda p: json.dumps(bad))
    assert out["planned_by"] == "fallback"
    row = out["table"][0]
    assert row["product_name"] == "Loan Against Property" and row["slab_lt_rs_10l_qtr"] == 0.74
    assert "commission_at_lowest_slab" not in row


def test_plan_referencing_a_missing_column_is_rejected():
    frames = {"db": {"df": pd.DataFrame({"k": ["a"], "v": [1]})},
              "sheet": {"df": pd.DataFrame({"k": ["a"], "r": [2]})}}
    cands = {"db->sheet": [{"left_on": "k", "right_on": "k"}]}
    plan = {"joins": [{"left": "db", "right": "sheet", "left_on": "k", "right_on": "k"}],
            "derived": [{"as": "x", "op": "multiply", "args": ["v", "does_not_exist"]}]}
    try:
        validate_plan(plan, frames, cands)
    except CombinePlanError:
        return
    raise AssertionError("a plan using an unknown column must be rejected")


def test_no_llm_still_joins_on_best_value_verified_key():
    out = combine_results([DB, SHEET], "q", llm_invoke=None)
    assert out["planned_by"] == "fallback"
    assert out["join_stats"][0]["matched"] == 4


def test_same_named_column_with_zero_matching_values_is_not_merged_and_is_reported():
    db_result = ("query_database", {"table": [
        {"material_id": "M00955", "description": "Recently", "total_quantity": 1732.91},
        {"material_id": "M00247", "description": "Two", "total_quantity": 1516.35},
    ]})
    sheet_result = ("query_spreadsheet_data", {"table": [
        {"material_id": "MAT-00001", "material_name": "Steel Sheet 2mm"},
        {"material_id": "MAT-00002", "material_name": "Steel Rod 12mm"},
    ]})
    out = combine_results([db_result, sheet_result], "q", llm_invoke=lambda p: "{}")
    assert out["base"] == "query_database"
    assert out["join_stats"] == []
    assert all("material_name" not in row for row in out["table"])
    assert len(out["notes"]) == 1 and "could NOT be cross-referenced" in out["notes"][0]


def test_same_named_column_with_real_matches_merges():
    db_result = ("query_database", {"table": [
        {"material_id": "M00001", "total_quantity": 100},
        {"material_id": "M00002", "total_quantity": 200},
    ]})
    sheet_result = ("query_spreadsheet_data", {"table": [
        {"material_id": "M00002", "material_name": "Steel Rod 12mm"},
        {"material_id": "M00001", "material_name": "Steel Sheet 2mm"},
    ]})
    out = combine_results([db_result, sheet_result], "q", llm_invoke=None)
    assert out["table"][0]["material_name"] == "Steel Sheet 2mm"
    assert out["table"][1]["material_name"] == "Steel Rod 12mm"
    assert out["notes"] == []


def test_unmatched_base_rows_are_reported():
    db_result = ("query_database", {"table": [
        {"product_name": "Home Loan", "amt": 10}, {"product_name": "Gold Loan", "amt": 5},
        {"product_name": "Crypto Loan", "amt": 1},
    ]})
    sheet_result = ("query_spreadsheet_data", {"table": [
        {"product_name": "Home Loan", "rate": "0.65%"}, {"product_name": "Gold Loan", "rate": "0.74%"},
    ]})
    out = combine_results([db_result, sheet_result], "q", llm_invoke=None)
    assert out["join_stats"][0]["matched"] == 2
    assert any("crypto loan" in n for n in out["notes"])


def test_fewer_than_two_tables_returns_none():
    assert combine_results([DB, ("search_documents", {"table": []})], "q") is None


def test_coincidental_integer_overlap_is_not_a_join_key():
    left = pd.DataFrame({"branch": ["North", "South"], "loan_count": [3, 4]})
    right = pd.DataFrame({"product_id": [3, 4, 5], "product_name": ["A", "B", "C"]})
    assert find_key_candidates(left, right) == []
    # ...but a numeric pair whose names agree is fine.
    right2 = pd.DataFrame({"branch_id": [1, 2], "manager": ["X", "Y"]})
    left2 = pd.DataFrame({"branch_id": [2, 1], "loans": [10.5, 20.5]})
    assert find_key_candidates(left2, right2)[0]["left_on"] == "branch_id"
