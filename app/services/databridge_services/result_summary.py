"""
Plain-language summary for a single-row query result (a KPI such as a
total or a count).

One row has nothing to chart and no distribution to analyse: describe()
statistics over it are just the value repeated, with NaN for the standard
deviation, and an LLM asked for "patterns" in it invents some. The value
itself is the answer, so it is stated directly instead.
"""
import math
import re
from typing import Any, Dict, List, Optional

_NUMBER_RE = re.compile(r"\s*-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*")

SINGLE_FIGURE_CHART_NOTE = "The result is a single figure, so it's shown as a number rather than a chart."


def is_single_row(data: Optional[List[Dict[str, Any]]]) -> bool:
    return bool(data) and len(data) == 1


def _label(column: str) -> str:
    return re.sub(r"[_\s]+", " ", str(column or "")).strip().capitalize() or "Value"


def _format_value(value: Any) -> str:
    if value is None:
        return "no value"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        number = float(value)
    elif _NUMBER_RE.fullmatch(str(value)):
        # Decimal from a NUMERIC column, or a number stored as text.
        number = float(str(value).replace(",", ""))
    else:
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return "no value"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def summarize_single_row(row: Dict[str, Any], columns: Optional[List[str]] = None) -> str:
    """e.g. {"count": 1749} -> "Count: 1,749." """
    cols = list(columns or row.keys())
    parts = [f"{_label(c)}: {_format_value(row.get(c))}" for c in cols]
    return ("; ".join(parts) + ".") if parts else ""
