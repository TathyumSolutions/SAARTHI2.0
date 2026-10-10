"""
Reads an uploaded Excel/CSV file into one DataFrame per sheet, finding the
real column-header row instead of assuming it's row 1.

Business spreadsheets often start with a title and a description before the
table itself:

    row 1: branch_network_master
    row 2: Branch master with staffing summary, maintained outside the ...
    row 3: Branch Code | Branch Name | City | State | Region | ...
    row 4: BR0001      | Bhubaneswar Branch 1 | Bhubaneswar | ...

Reading that with pandas' default header=0 makes "branch_network_master"
the first column name, every other column "Unnamed: N", and the real
header a data row. Here the header is detected per sheet, the sheet is
re-read from that row (so numbers/dates keep their proper dtypes), and the
skipped title text is returned so it can describe the table.

The same goes for the bottom of a sheet: a "Notes" block written under the
table, after a blank row, is policy text about the table, not more rows of
it. It's split off and returned as the table's notes instead of being
loaded as half-empty data rows.
"""
import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# How far down a sheet a header row is looked for.
HEADER_SCAN_ROWS = 25

_NUMERIC_TEXT = re.compile(r"^[-+]?[\d,]*\.?\d+%?$")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _is_label(value: Any) -> bool:
    """A cell that could be a column name: text that isn't just a number."""
    return isinstance(value, str) and bool(value.strip()) and not _NUMERIC_TEXT.match(value.strip())


def detect_header_row(rows: List[List[Any]]) -> int:
    """Index of the column-header row within `rows` (the top of a sheet,
    one list of cell values per row). The header is the first row that:
      - fills at least half of the table's width, and nearly as many cells
        as the first row below it (title/description rows fill one or two),
      - is at least 80% text labels rather than numbers/dates,
      - has no repeated labels, and
      - is followed by a row with data in it.
    Falls back to 0 (pandas' default) when no row qualifies."""
    filled = [[v for v in row if not _is_blank(v)] for row in rows]
    width = max((len(f) for f in filled), default=0)
    if width < 2:
        return 0

    for i, cells in enumerate(filled):
        n = len(cells)
        if n < 2 or n < 0.5 * width:
            continue
        if sum(_is_label(v) for v in cells) < 0.8 * n:
            continue
        labels = [str(v).strip().lower() for v in cells]
        if len(set(labels)) != n:
            continue
        next_row = next((filled[j] for j in range(i + 1, len(filled)) if filled[j]), None)
        if next_row is None or n < 0.8 * len(next_row):
            continue
        return i
    return 0


def _title_text(rows: List[List[Any]], header_row: int) -> str:
    """The text in the rows above the header (title, description), joined."""
    parts = []
    for row in rows[:header_row]:
        for v in row:
            if not _is_blank(v):
                parts.append(str(v).strip())
    return " - ".join(parts)


def _split_footer_notes(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """Splits a notes/footnote block off the bottom of a table: everything
    after the first fully blank row, provided every non-blank row after it
    is sparse (at most 2 cells, and under half the table's width) - i.e.
    sentences, not more data. A table with a blank row in the middle of
    real data is left alone, since the rows after its gap are full width.
    Returns (table, notes text)."""
    width = len(df.columns)
    filled = df.notna().sum(axis=1).tolist()
    for i, count in enumerate(filled):
        if count or not any(filled[:i]):
            continue
        rest = [(j, c) for j, c in enumerate(filled[i + 1:], start=i + 1) if c]
        if rest and all(c <= 2 and c < 0.5 * width for _, c in rest):
            lines = []
            for j, _ in rest:
                lines.extend(str(v).strip() for v in df.iloc[j].tolist() if not _is_blank(v))
            return df.iloc[:i], "\n".join(lines)
    return df, ""


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Drops fully empty rows, and columns that are entirely empty and have
    no real header (e.g. a blank column A before a table starting in B)."""
    df = df.dropna(how="all")
    keep = [
        c for c in df.columns
        if df[c].notna().any() or not str(c).lower().startswith("unnamed")
    ]
    return df[keep].reset_index(drop=True)


def read_tabular_upload(data: bytes, filename: str) -> Tuple[Dict[Optional[str], pd.DataFrame], Dict[Optional[str], Dict[str, Any]]]:
    """Reads an uploaded .csv/.xlsx/.xls file's bytes. Returns
    ({sheet_name: DataFrame}, {sheet_name: {"header_row": 1-based row,
    "title": text above the header, "notes": text below the table (only
    when there is some)}}). A CSV has a single sheet named None.
    Raises ValueError for an unsupported extension."""
    name = (filename or "").lower()
    sheets: Dict[Optional[str], pd.DataFrame] = {}
    info: Dict[Optional[str], Dict[str, Any]] = {}

    if name.endswith(".csv"):
        # csv.reader rather than pandas for the scan: pandas refuses a CSV
        # whose title line has fewer fields than the table below it.
        text = data.decode("utf-8-sig", errors="replace")
        top = [row for _, row in zip(range(HEADER_SCAN_ROWS), csv.reader(io.StringIO(text)))]
        header_row = detect_header_row(top)
        df, notes = _split_footer_notes(pd.read_csv(io.BytesIO(data), skiprows=header_row))
        sheets[None] = _tidy(df)
        info[None] = {"header_row": header_row + 1, "title": _title_text(top, header_row)}
        if notes:
            info[None]["notes"] = notes
        return sheets, info

    if name.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, nrows=HEADER_SCAN_ROWS)
        for sheet_name, top_df in raw.items():
            top = top_df.values.tolist()
            header_row = detect_header_row(top)
            df, notes = _split_footer_notes(pd.read_excel(io.BytesIO(data), sheet_name=sheet_name, header=header_row))
            sheets[sheet_name] = _tidy(df)
            info[sheet_name] = {"header_row": header_row + 1, "title": _title_text(top, header_row)}
            if notes:
                info[sheet_name]["notes"] = notes
        return sheets, info

    raise ValueError("Only .xlsx, .xls, or .csv files are supported")
