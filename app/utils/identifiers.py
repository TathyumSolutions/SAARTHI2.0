"""
Shared identifier sanitization for anything that ends up as a literal SQL
table/column name - used by both the Excel-upload path (Parquet-backed
tables, see app/routes/database_routes.py) and the Postgres spreadsheet
warehouse (app/services/spreadsheet_warehouse_service.py), so both agree on
what counts as a "safe" identifier instead of each hand-rolling its own
rules.
"""
import re


def sanitize_identifier(name: str) -> str:
    """Turns a messy file/column name into a safe SQL table/column name."""
    name = re.sub(r'[^a-zA-Z0-9_]', '_', (name or '').strip().lower())
    name = re.sub(r'_+', '_', name).strip('_')
    if not name or name[0].isdigit():
        name = f"col_{name}"
    return name


def dedupe_identifiers(names):
    """Ensures identifiers are unique after sanitization."""
    seen = {}
    out = []
    for raw in names:
        base = sanitize_identifier(str(raw))
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(base if count == 0 else f"{base}_{count + 1}")
    return out
