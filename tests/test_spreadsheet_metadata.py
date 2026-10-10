"""
Tests for how an uploaded spreadsheet is turned into table + column
metadata, using a sheet laid out like the agent commission slab card:

    row 1: DSA / Agent Commission Slab Card
    row 2: Commission payable to empanelled agents (DSAs) as a % of ...
    row 4: Product Code | Product Name | Slab: < Rs 10L/qtr | ... | Slab: > Rs 2Cr/qtr
    rows : PL | Personal Loan | 0.64% | 0.84% | 1.04% | 1.19%   (12 products)
    blank rows, then a Notes block.

Previously this became 16 rows (the notes loaded as data), rates stayed
text ("0.64%"), "<"/">" were stripped from the column names (no way to
tell the lowest slab from the highest), the summary LLM saw only those
cleaned-up names plus 5 rows, and the connection's schema_metadata was
never filled in for an Excel upload at all.
"""
import io
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from openpyxl import Workbook

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import spreadsheet_service
from app.services.column_intelligence import (
    enrich_table_semantics, normalize_numeric_text, profile_column,
)
from app.services.spreadsheet_header_detection import read_tabular_upload

PRODUCTS = [
    ("PL", "Personal Loan", 0.64), ("GL", "Gold Loan", 0.74), ("TW", "Two-Wheeler Loan", 0.74),
    ("UCL", "Used Car Loan", 0.74), ("NCL", "New Car Loan", 0.72), ("MSME", "MSME Business Loan", 0.64),
    ("LAP", "Loan Against Property", 0.74), ("CD", "Consumer Durable Loan", 0.7),
    ("MFI", "Microfinance (JLG) Loan", 0.72), ("EDU", "Education Loan", 0.64),
    ("HL", "Home Loan", 0.65), ("HLTU", "Home Loan Top-up", 0.72),
]
HEADER = ["Product Code", "Product Name", "Slab: < Rs 10L/qtr", "Slab: Rs 10L-50L/qtr",
          "Slab: Rs 50L-2Cr/qtr", "Slab: > Rs 2Cr/qtr"]
TITLE = "DSA / Agent Commission Slab Card"
SUBTITLE = ("Commission payable to empanelled agents (DSAs) as a % of disbursed amount, by product "
            "and by the agent's trailing-quarter disbursement volume slab.")
NOTES = [
    "Notes",
    "- Commission is paid on disbursed amount, net of any part-prepayment within the first 90 days.",
    "- Slab is re-evaluated at the start of every quarter based on the agent's trailing 3-month disbursement volume.",
    "- Gold Loan and Loan Against Property commissions are capped at 1.5% per the product policy regardless of slab.",
]


def _slab_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Commission Slabs"
    ws.append([TITLE])
    ws.append([SUBTITLE])
    ws.append([])
    ws.append(HEADER)
    for code, name, low in PRODUCTS:
        ws.append([code, name] + [f"{round(low + 0.2 * i, 2):g}%" for i in range(3)] + [f"{round(low + 0.55, 2):g}%"])
    ws.append([])
    ws.append([])
    for line in NOTES:
        ws.append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def manifest_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(spreadsheet_service, "SPREADSHEET_FOLDER", str(tmp_path))
    monkeypatch.setattr(spreadsheet_service, "MANIFEST_FILE", str(tmp_path / "manifest.json"))
    return tmp_path


def _upload(connection_id=7):
    from app.routes.database_routes import _save_sheet
    sheets, info = read_tabular_upload(_slab_workbook(), "03_agent_commission_slabs.xlsx")
    connection = SimpleNamespace(id=connection_id, schema_metadata=None)
    record = _save_sheet(connection, "agent_commission", "Commission Slabs",
                         sheets["Commission Slabs"], info["Commission Slabs"])
    return connection, record


def test_notes_block_is_split_off_not_loaded_as_rows():
    sheets, info = read_tabular_upload(_slab_workbook(), "f.xlsx")
    df = sheets["Commission Slabs"]
    assert len(df) == 12
    assert info["Commission Slabs"]["notes"].splitlines() == NOTES
    assert info["Commission Slabs"]["title"].startswith(TITLE)


def test_blank_row_inside_real_data_is_not_mistaken_for_notes():
    wb = Workbook()
    ws = wb.active
    ws.append(["Code", "Name", "Amount"])
    ws.append(["A", "Alpha", 1])
    ws.append([])
    ws.append(["B", "Beta", 2])
    buf = io.BytesIO()
    wb.save(buf)
    sheets, info = read_tabular_upload(buf.getvalue(), "f.xlsx")
    assert len(next(iter(sheets.values()))) == 2
    assert "notes" not in next(iter(info.values()))


def test_upload_keeps_headers_units_numbers_and_fills_schema_metadata(manifest_dir):
    connection, record = _upload()
    names = [c["name"] for c in record["columns"]]
    assert names == ["product_code", "product_name", "slab_lt_rs_10l_qtr", "slab_rs_10l_50l_qtr",
                     "slab_rs_50l_2cr_qtr", "slab_gt_rs_2cr_qtr"]
    by_name = {c["name"]: c for c in record["columns"]}
    assert by_name["slab_lt_rs_10l_qtr"]["label"] == "Slab: < Rs 10L/qtr"
    assert by_name["slab_lt_rs_10l_qtr"]["unit"] == "percent"
    assert by_name["slab_lt_rs_10l_qtr"]["type"] == "number"
    assert by_name["slab_lt_rs_10l_qtr"]["role"] == "measure"
    assert by_name["product_code"]["role"] == "identifier"
    assert record["row_count"] == 12
    assert record["notes"].startswith("Notes")

    df = spreadsheet_service.get_table_df("agent_commission")
    assert df.loc[df.product_code == "PL", "slab_lt_rs_10l_qtr"].iloc[0] == 0.64

    meta = connection.schema_metadata["agent_commission"]
    assert meta["row_count"] == 12
    assert meta["title"].startswith(TITLE)
    assert meta["notes"].startswith("Notes")
    assert meta["columns"][2]["label"] == "Slab: < Rs 10L/qtr"
    assert meta["columns"][2]["sample_values"][0] == 0.64


def test_process_summary_sees_title_headers_notes_and_stores_column_meanings(manifest_dir):
    from app.routes.database_routes import _summarize_spreadsheet_table_for_metamind
    _upload()
    seen = {}

    def fake_llm(prompt):
        seen["prompt"] = prompt
        return json.dumps({
            "table_description": "Commission rates payable to DSAs per product across 4 agent quarterly-volume slabs.",
            "columns": {
                "slab_lt_rs_10l_qtr": {"meaning": "Rate for agents under Rs 10L/quarter (lowest slab)",
                                       "role": "measure", "unit": "percent"},
                "product_name": {"meaning": "Loan product name", "role": "identifier"},
                "invented_column": {"meaning": "should be ignored"},
            },
        })

    description = _summarize_spreadsheet_table_for_metamind(
        "agent_commission", "Agent commission slab card", llm_invoke=fake_llm)

    prompt = seen["prompt"]
    assert TITLE in prompt and 'original header "Slab: < Rs 10L/qtr"' in prompt
    assert "trailing 3-month disbursement volume" in prompt  # the notes
    assert "Agent commission slab card" in prompt
    assert description.startswith("Commission rates payable to DSAs")
    record = spreadsheet_service.get_table_record("agent_commission")
    cols = {c["name"]: c for c in record["columns"]}
    assert cols["slab_lt_rs_10l_qtr"]["meaning"].endswith("(lowest slab)")
    assert "invented_column" not in cols
    assert record["description"] == description


def test_numeric_text_normalization():
    import pandas as pd
    df, units = normalize_numeric_text(pd.DataFrame({
        "rate": ["0.64%", "1.2%", None], "amt": ["Rs 1,200", "₹ 3,40,000", "Rs 5"],
        "count": ["12", "7", "3"], "mixed": ["12", "abc", "3"], "code": ["PL", "GL", "HL"],
    }))
    assert list(df["rate"][:2]) == [0.64, 1.2] and units["rate"] == "percent"
    assert list(df["amt"]) == [1200.0, 340000.0, 5.0] and units["amt"] == "currency"
    assert list(df["count"]) == [12.0, 7.0, 3.0] and "count" not in units
    assert list(df["mixed"]) == ["12", "abc", "3"]
    assert list(df["code"]) == ["PL", "GL", "HL"]


def test_profile_column_roles():
    assert profile_column("loan_id", [1, 2, 3], "bigint")["role"] == "identifier"
    assert profile_column("disbursed_amount", [100.5], "numeric") == {"role": "measure", "unit": "currency"}
    assert profile_column("disbursement_date", ["2024-01-01"], "date")["role"] == "date"
    assert profile_column("is_active", [True, False], "boolean")["role"] == "flag"
    assert profile_column("region", ["North", "South"], "character varying")["role"] == "dimension"


def test_enrich_table_semantics_survives_bad_llm_output():
    cols = [{"name": "a", "type": "text"}]
    assert enrich_table_semantics("t", cols, [], llm_invoke=lambda p: "not json") == {
        "table_description": "", "columns": {}}

    def boom(prompt):
        raise RuntimeError("LLM down")
    assert enrich_table_semantics("t", cols, [], llm_invoke=boom) == {}


def test_header_symbols_are_kept_in_column_names_and_text_is_tidied():
    from app.routes.database_routes import _clean_text, _dedupe_identifiers
    assert _dedupe_identifiers(["Slab: < Rs 10L/qtr", "Slab: > Rs 2Cr/qtr", "Rate (%)", "Age >= 18"]) == [
        "slab_lt_rs_10l_qtr", "slab_gt_rs_2cr_qtr", "rate_pct", "age_gte_18"]
    assert _clean_text("  Lending    Database. ") == "Lending Database."
    assert _clean_text("   ") is None


def test_excel_connection_records_are_synced_and_orphans_flagged():
    from app.services import automated_metamind
    ok = SimpleNamespace(id=1, type="Excel", schema_metadata=None, status="connected",
                         error_message=None, metamind_summary="x")
    orphan = SimpleNamespace(id=2, type="Excel", schema_metadata=None, status="connected",
                             error_message=None, metamind_summary=None)
    pg = SimpleNamespace(id=3, type="PostgreSQL", schema_metadata={"t": {}}, status="connected",
                         error_message=None, metamind_summary=None)
    table = {"table": "agent_commission", "row_count": 12, "description": "d", "sheet": "S",
             "title": "T", "notes": "N", "columns": [{"name": "product_code"}]}
    with patch("app.db.session") as session:
        automated_metamind._sync_spreadsheet_connection_records({1: ok, 2: orphan, 3: pg}, {1: [table]})
        session.commit.assert_called_once()
    assert ok.schema_metadata["agent_commission"]["notes"] == "N"
    assert orphan.status == "error" and "re-upload" in orphan.error_message
    assert "missing" in orphan.metamind_summary
    assert pg.schema_metadata == {"t": {}} and pg.status == "connected"


def test_db_column_meanings_are_stored_per_table_and_reapplied():
    from app.services import automated_metamind
    columns = [{"name": "product_id", "data_type": "smallint", "sample_values": [1, 2]},
               {"name": "commission_rate", "data_type": "numeric", "sample_values": [0.64, 0.74]}]
    connection = SimpleNamespace(
        description="Lending DB", config={},
        schema_metadata={"agents": {"description": "DSAs", "row_count": 2, "columns": columns}},
    )
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        return json.dumps({"columns": {"commission_rate": {"meaning": "% of disbursed amount paid to the agent",
                                                           "unit": "percent", "role": "measure"}}})

    with patch("app.db.session"):
        assert automated_metamind.enrich_db_column_semantics(connection, llm_invoke=fake_llm) == 1
        # Already done for this column set -> no second LLM call.
        assert automated_metamind.enrich_db_column_semantics(connection, llm_invoke=fake_llm) == 0
    assert len(calls) == 1
    cols = {c["name"]: c for c in connection.schema_metadata["agents"]["columns"]}
    assert cols["commission_rate"]["meaning"].startswith("% of disbursed")
    assert cols["commission_rate"]["unit"] == "percent"
    assert cols["product_id"]["role"] == "identifier"

    fresh = {"agents": {"row_count": 2, "columns": [dict(c) for c in columns]}}
    automated_metamind._apply_db_column_intelligence(fresh, connection)
    assert {c["name"]: c for c in fresh["agents"]["columns"]}["commission_rate"]["meaning"]


def test_digit_labels_are_not_turned_into_numbers():
    import pandas as pd
    df, _ = normalize_numeric_text(pd.DataFrame({
        "branch_code": ["0012", "0101"], "mobile": ["9876543210", "9123456780"], "ref": ["007", "120"],
    }))
    assert list(df["branch_code"]) == ["0012", "0101"]
    assert list(df["mobile"]) == ["9876543210", "9123456780"]
    assert list(df["ref"]) == ["007", "120"]
    df, _ = normalize_numeric_text(pd.DataFrame({"company_revenue": ["1,200", "3,400"]}))
    assert list(df["company_revenue"]) == [1200.0, 3400.0]
