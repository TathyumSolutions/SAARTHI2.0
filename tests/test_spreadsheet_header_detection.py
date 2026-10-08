"""
Tests for detecting the real column-header row of an uploaded Excel/CSV
file, instead of assuming row 1 - e.g. a branch master sheet that starts
with a title row and a description row (the "unnamed: 1..9" bug).
"""
import io
import os
import sys
from datetime import datetime

import pandas as pd
from openpyxl import Workbook

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.spreadsheet_header_detection import detect_header_row, read_tabular_upload

HEADER = ["Branch Code", "Branch Name", "City", "State", "Region", "Pincode",
          "Opened Date", "Active", "Employee Count", "Agent Count"]


def _branch_rows(n=5):
    return [[f"BR{i:04d}", f"Branch {i}", "Bhubaneswar", "Odisha", "East", 751000 + i,
             datetime(2020, 1, i), "Yes", 9, 10 + i] for i in range(1, n + 1)]


def _xlsx(sheets):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_title_and_description_rows_are_skipped():
    """The screenshot case: header on row 3, below a title and a description."""
    data = _xlsx({"Branch Master": [
        ["branch_network_master"],
        ["Branch master with staffing summary, maintained outside the core system"],
        HEADER,
        *_branch_rows(),
    ]})
    sheets, info = read_tabular_upload(data, "branch_master.xlsx")
    df = sheets["Branch Master"]

    assert list(df.columns) == HEADER
    assert len(df) == 5
    assert df.iloc[0]["Branch Code"] == "BR0001"
    assert not any(str(c).lower().startswith("unnamed") for c in df.columns)
    # Re-read from the header row, so numbers and dates keep real dtypes.
    assert pd.api.types.is_numeric_dtype(df["Employee Count"])
    assert pd.api.types.is_datetime64_any_dtype(df["Opened Date"])
    assert info["Branch Master"]["header_row"] == 3
    assert info["Branch Master"]["title"].startswith("branch_network_master - Branch master with staffing")


def test_normal_sheet_keeps_row_1_header():
    sheets, info = read_tabular_upload(_xlsx({"S": [HEADER, *_branch_rows()]}), "f.xlsx")
    assert list(sheets["S"].columns) == HEADER
    assert info["S"] == {"header_row": 1, "title": ""}


def test_blank_rows_and_leading_blank_column():
    data = _xlsx({"S": [
        [None, "Quarterly branch report"],
        [],
        [None, *HEADER],
        *[[None, *r] for r in _branch_rows(3)],
    ]})
    sheets, info = read_tabular_upload(data, "f.xlsx")
    assert list(sheets["S"].columns) == HEADER
    assert len(sheets["S"]) == 3
    assert info["S"]["header_row"] == 3


def test_each_sheet_detected_independently():
    data = _xlsx({
        "WithTitle": [["Title only"], HEADER, *_branch_rows(2)],
        "Plain": [["Code", "Amount"], ["A", 10], ["B", 20]],
    })
    sheets, info = read_tabular_upload(data, "f.xlsx")
    assert list(sheets["WithTitle"].columns) == HEADER
    assert list(sheets["Plain"].columns) == ["Code", "Amount"]
    assert info["WithTitle"]["header_row"] == 2 and info["Plain"]["header_row"] == 1


def test_csv_with_title_lines():
    """pandas alone can't even parse this - the title line has 1 field and
    the table below has 3."""
    csv_text = "Loan book export\nGenerated 2026-10-01\nLoan ID,Customer,Amount\nL1,Asha,1000.5\nL2,Ravi,2500\n"
    sheets, info = read_tabular_upload(csv_text.encode(), "loans.csv")
    df = sheets[None]
    assert list(df.columns) == ["Loan ID", "Customer", "Amount"]
    assert df["Amount"].tolist() == [1000.5, 2500]
    assert info[None]["header_row"] == 3


def test_plain_csv_unchanged():
    sheets, info = read_tabular_upload(b"a,b\n1,2\n3,4\n", "x.csv")
    assert list(sheets[None].columns) == ["a", "b"] and info[None]["header_row"] == 1


def test_unsupported_extension():
    try:
        read_tabular_upload(b"", "notes.txt")
    except ValueError as e:
        assert "supported" in str(e)
    else:
        raise AssertionError("expected ValueError")


# ---------------- detect_header_row edge cases ----------------

def test_numeric_first_row_is_not_a_header():
    """No header at all (data from row 1) - fall back to pandas' default
    rather than skipping real data."""
    assert detect_header_row([[1, 2, 3], [4, 5, 6]]) == 0


def test_duplicate_labels_row_is_not_a_header():
    rows = [["Total", "Total", "Total"], ["Code", "Name", "Amount"], ["A", "x", 1]]
    assert detect_header_row(rows) == 1


def test_header_must_have_data_below():
    rows = [["Title"], ["Code", "Name", "Amount"]]
    assert detect_header_row(rows) == 0


def test_short_title_above_narrow_table_is_not_a_header():
    rows = [["Report", "Q3"], ["Code", "Name", "Amount"], ["A", "x", 1], ["B", "y", 2]]
    assert detect_header_row(rows) == 1


def test_header_with_a_blank_cell_still_detected():
    rows = [["Title"], ["Code", "Name", None, "Amount", "Region"], ["A", "x", "n", 1, "E"]]
    assert detect_header_row(rows) == 1
