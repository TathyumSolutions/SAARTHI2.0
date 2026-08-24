"""
Tests for _merge_tabular_results' shared-key join, specifically the case
that produced the "smart router hallucination" bug: two tracks whose
tables both have a same-named column (e.g. material_id) that never
actually shares a value between them - a DB table using "M00123" and a
Spreadsheet lookup using "MAT-00123" are a real example from this app's own
demo data. Matching on the column name alone and getting zero real matches
must NOT be treated as a successful merge: the other track's columns must
not be silently folded in with no rows populated, and the merge failure
must be reported via merge_notes so the MULTI synthesis step can be told
about it instead of presenting an unrelated base-table field (e.g. a
placeholder "description") as if it were the missing information.
"""
import os
import sys
from unittest.mock import MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# app.services.llm_service instantiates a real HuggingFaceEmbeddings client
# at import time (module-level singleton), which reaches out to the HF hub -
# not available in this sandbox's network policy. Stub it out before
# router_service (which imports llm_service) is ever imported, purely so
# this test file can exercise _merge_tabular_results without a live network
# call for something this test has nothing to do with.
_fake_hf = MagicMock()
_fake_hf.HuggingFaceEmbeddings = MagicMock(return_value=MagicMock())
sys.modules.setdefault("langchain_huggingface", _fake_hf)

from app.services.router_service import _merge_tabular_results


def test_shared_key_join_with_zero_matches_does_not_merge_and_reports_note():
    db_result = {
        "table": [
            {"material_id": "M00955", "description": "Recently", "total_quantity": 1732.91},
            {"material_id": "M00247", "description": "Two", "total_quantity": 1516.35},
        ],
    }
    spreadsheet_result = {
        "table": [
            {"material_id": "MAT-00001", "material_name": "Steel Sheet 2mm"},
            {"material_id": "MAT-00002", "material_name": "Steel Rod 12mm"},
        ],
    }
    ok_results = [
        ("query_database", db_result),
        ("query_spreadsheet_data", spreadsheet_result),
    ]

    name, merged = _merge_tabular_results(ok_results)

    assert name == "query_database"
    # No row should have picked up material_name - the IDs never matched.
    for row in merged["table"]:
        assert "material_name" not in row
    assert merged["table"] == db_result["table"]
    assert "merge_notes" in merged
    assert len(merged["merge_notes"]) == 1
    note = merged["merge_notes"][0]
    assert "material_id" in note
    assert "material_name" in note


def test_shared_key_join_with_real_matches_merges_normally_and_reports_no_notes():
    db_result = {
        "table": [
            {"material_id": "M00001", "total_quantity": 100},
            {"material_id": "M00002", "total_quantity": 200},
        ],
    }
    spreadsheet_result = {
        "table": [
            {"material_id": "M00001", "material_name": "Steel Sheet 2mm"},
            {"material_id": "M00002", "material_name": "Steel Rod 12mm"},
        ],
    }
    ok_results = [
        ("query_database", db_result),
        ("query_spreadsheet_data", spreadsheet_result),
    ]

    name, merged = _merge_tabular_results(ok_results)

    assert name == "query_database"
    assert merged["table"][0]["material_name"] == "Steel Sheet 2mm"
    assert merged["table"][1]["material_name"] == "Steel Rod 12mm"
    assert "merge_notes" not in merged
