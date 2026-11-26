"""
Honesty rules for answers given without querying any data source.

When a question reaches the general-knowledge track while the user has
data connected, the model used to write a calculation plan and finish with
"you would need access to the loan data, the norms document and the Excel"
- although all of them were connected. These helpers tell it which sources
exist so it says plainly that it did not check them, instead.
"""
from __future__ import annotations

from typing import List

_LABELS = (
    ("DB", "a database"),
    ("FILES", "uploaded documents"),
    ("SPREADSHEET", "uploaded spreadsheets"),
    ("API", "external APIs"),
)


def connected_source_labels(router_config: dict) -> List[str]:
    """Human labels for the data sources that actually hold something."""
    menu = ((router_config or {}).get("routing_menu", {}) or {}).get("datasources", {}) or {}
    available = {
        "DB": bool((menu.get("DB", {}) or {}).get("tables")),
        "FILES": ((menu.get("FILES", {}) or {}).get("vector_store_info", {}) or {}).get("points_count", 0) > 0,
        "SPREADSHEET": bool((menu.get("SPREADSHEET", {}) or {}).get("tables")),
        "API": bool((menu.get("API", {}) or {}).get("registered_tools")),
    }
    return [label for key, label in _LABELS if available[key]]


def not_checked_instruction(source_labels: List[str]) -> str:
    """System-prompt rule for a general answer while sources are connected."""
    if not source_labels:
        return ""
    listed = ", ".join(source_labels)
    return (
        "\n\nDATA SOURCE HONESTY: this user has connected data sources "
        f"({listed}), but this answer was produced WITHOUT querying any of them. "
        "If the question asks about the user's own data, figures, documents or files, "
        "begin by saying plainly that you did not check their connected data for this "
        "answer, and offer to run it against their data (e.g. 'Want me to run this on "
        "your data?'). Never say they would need to provide or give access to data, "
        "and never present figures as if they came from their data."
    )
