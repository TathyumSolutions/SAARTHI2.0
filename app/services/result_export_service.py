"""
Result Export Service - keeps the full result set of a chat answer so the
user can download every record as Excel, even though the chat itself only
shows a readable slice (the top 5 bars of a chart, the first rows of a
table).

Results are saved as JSON under <instance>/result_exports/<export_id>.json
when the answer is returned, and turned into an .xlsx only when someone
actually clicks download. Each export records the user it belongs to, and
only that user can fetch it. Files older than EXPORT_TTL_DAYS are pruned
whenever a new export is saved.
"""
import io
import json
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import current_app
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

EXPORT_TTL_DAYS = 7
_EXPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_MAX_COLUMN_WIDTH = 50


def _export_dir() -> str:
    path = os.path.join(current_app.instance_path, "result_exports")
    os.makedirs(path, exist_ok=True)
    return path


def _export_path(export_id: str) -> Optional[str]:
    # The id comes from a URL - only ever accept our own uuid4 hex format so
    # it can never be used to walk out of the export directory.
    if not isinstance(export_id, str) or not _EXPORT_ID_PATTERN.match(export_id):
        return None
    return os.path.join(_export_dir(), f"{export_id}.json")


def _prune_expired(directory: str) -> None:
    cutoff = time.time() - EXPORT_TTL_DAYS * 86400
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        full = os.path.join(directory, name)
        try:
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
        except OSError:
            continue


def _columns_of(rows: List[Dict[str, Any]]) -> List[str]:
    # Union of keys in first-seen order - rows from a merged multi-source
    # answer don't all carry the same columns.
    columns: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def save_result_export(rows: Any, user_id: int, question: str = "") -> Optional[Dict[str, Any]]:
    """Saves a result set for later download. Returns {"id", "row_count"},
    or None when there's nothing worth exporting (fewer than 2 rows - a
    single value is already fully shown in the chat)."""
    if not isinstance(rows, list):
        return None
    dict_rows = [r for r in rows if isinstance(r, dict)]
    if len(dict_rows) < 2:
        return None

    directory = _export_dir()
    _prune_expired(directory)

    export_id = uuid.uuid4().hex
    payload = {
        "user_id": user_id,
        "question": question or "",
        "created_at": datetime.utcnow().isoformat(),
        "columns": _columns_of(dict_rows),
        "rows": dict_rows,
    }
    with open(os.path.join(directory, f"{export_id}.json"), "w", encoding="utf-8") as fh:
        # default=str covers Decimal/date/datetime values straight from the DB.
        json.dump(payload, fh, default=str)
    return {"id": export_id, "row_count": len(dict_rows)}


def load_result_export(export_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    """The saved export, or None if it doesn't exist, expired, or belongs
    to someone else (deliberately indistinguishable to the caller)."""
    path = _export_path(export_id)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if str(payload.get("user_id")) != str(user_id):
        return None
    return payload


def build_result_workbook(export: Dict[str, Any]) -> io.BytesIO:
    """Renders a saved export as an .xlsx: a 'Results' sheet with every row
    (bold, frozen header row; columns sized to their content) and an
    'About' sheet recording the question and when it was answered."""
    columns: List[str] = export.get("columns") or []
    rows: List[Dict[str, Any]] = export.get("rows") or []

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    header_fill = PatternFill("solid", fgColor="7C3AED")
    ws.append([str(c) for c in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
    ws.freeze_panes = "A2"

    widths = [len(str(c)) for c in columns]
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, col in enumerate(columns, start=1):
            value = row.get(col)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            if isinstance(value, str) and value.startswith("="):
                # openpyxl would otherwise write a database value like
                # "=HYPERLINK(...)" as a live formula.
                cell.data_type = "s"
            widths[col_idx - 1] = max(widths[col_idx - 1], len(str(value)) if value is not None else 0)

    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = min(width + 2, _MAX_COLUMN_WIDTH)

    about = wb.create_sheet("About")
    about.append(["Question", export.get("question") or ""])
    about.append(["Answered at (UTC)", export.get("created_at") or ""])
    about.append(["Rows", len(rows)])
    for cell in about["A"]:
        cell.font = Font(bold=True)
    about.column_dimensions["A"].width = 20
    about.column_dimensions["B"].width = 80
    if isinstance(about["B1"].value, str) and about["B1"].value.startswith("="):
        about["B1"].data_type = "s"

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def export_filename(export: Dict[str, Any]) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (export.get("question") or "results")).strip("_")[:40] or "results"
    return f"saarthi_{slug}.xlsx"
