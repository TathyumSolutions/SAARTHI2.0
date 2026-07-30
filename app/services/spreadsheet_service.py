"""
Storage and lookup for Excel/CSV-derived tables that deliberately do NOT
live in Postgres - there's no spare warehouse to hold them, and no SQL
engine runs against them. Each sheet (or CSV) is saved as a Parquet file
on disk; a JSON manifest tracks table -> file plus the schema and the
LLM-generated content description that feeds metamind.

Table names are unique across the whole manifest (enforced at creation
time in database_routes.py via the same identifier-dedup logic used for
real DB tables), so lookups by table name alone are unambiguous.
"""
import os
import json
import pandas as pd

SPREADSHEET_FOLDER = os.path.join(os.getcwd(), 'uploads', 'spreadsheets')
MANIFEST_FILE = os.path.join(SPREADSHEET_FOLDER, 'spreadsheet_metadata.json')


def _ensure_folder():
    os.makedirs(SPREADSHEET_FOLDER, exist_ok=True)


def _load_manifest() -> dict:
    _ensure_folder()
    if not os.path.exists(MANIFEST_FILE):
        return {"connections": {}}
    try:
        with open(MANIFEST_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"connections": {}}


def _save_manifest(manifest: dict):
    _ensure_folder()
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2)


def classify_column(series: pd.Series) -> str:
    """A small, portable type vocabulary (not a Postgres type) used both
    to tell the router/LLM what operators make sense on a column, and to
    validate query plans before they run - never trust the plan's own
    claim about a column's type."""
    non_null = series.dropna()
    if non_null.empty:
        return "text"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    return "text"


def save_table(connection_id: int, table_name: str, sheet_name, df: pd.DataFrame) -> dict:
    """Writes one sheet/CSV as a Parquet file and records it in the
    manifest under the given connection. Returns the table's manifest
    record (without a description yet - that's added by summarization)."""
    _ensure_folder()
    conn_dir = os.path.join(SPREADSHEET_FOLDER, str(connection_id))
    os.makedirs(conn_dir, exist_ok=True)
    parquet_path = os.path.join(conn_dir, f"{table_name}.parquet")
    df.to_parquet(parquet_path, index=False)

    columns = [{"name": col, "type": classify_column(df[col])} for col in df.columns]
    record = {
        "table": table_name,
        "sheet": sheet_name,
        "parquet_path": parquet_path,
        "columns": columns,
        "row_count": len(df),
        "description": None,
    }

    manifest = _load_manifest()
    conn_key = str(connection_id)
    manifest["connections"].setdefault(conn_key, {"tables": []})
    manifest["connections"][conn_key]["tables"] = [
        t for t in manifest["connections"][conn_key]["tables"] if t["table"] != table_name
    ]
    manifest["connections"][conn_key]["tables"].append(record)
    _save_manifest(manifest)
    return record


def set_original_filename(connection_id: int, filename: str):
    manifest = _load_manifest()
    conn_key = str(connection_id)
    manifest["connections"].setdefault(conn_key, {"tables": []})
    manifest["connections"][conn_key]["original_filename"] = filename
    _save_manifest(manifest)


def get_tables_for_connection(connection_id: int) -> list:
    manifest = _load_manifest()
    return manifest["connections"].get(str(connection_id), {}).get("tables", [])


def list_all_tables() -> list:
    """Every spreadsheet-backed table across every connection - used by
    automated_metamind.py to build the SPREADSHEET routing menu entry."""
    manifest = _load_manifest()
    out = []
    for conn_key, conn_data in manifest["connections"].items():
        for table in conn_data.get("tables", []):
            out.append({**table, "connection_id": int(conn_key)})
    return out


def get_table_record(table_name: str):
    for table in list_all_tables():
        if table["table"] == table_name:
            return table
    return None


def get_table_df(table_name: str) -> pd.DataFrame:
    record = get_table_record(table_name)
    if not record:
        raise ValueError(f"No spreadsheet table named '{table_name}' is registered.")
    return pd.read_parquet(record["parquet_path"])


def set_table_description(table_name: str, description: str):
    manifest = _load_manifest()
    for conn_data in manifest["connections"].values():
        for table in conn_data.get("tables", []):
            if table["table"] == table_name:
                table["description"] = description
    _save_manifest(manifest)


def delete_connection_tables(connection_id: int):
    """Removes a connection's Parquet files and manifest entry entirely -
    called when the DatabaseConnection row itself is deleted, so nothing
    is left orphaned on disk or still visible to the router."""
    manifest = _load_manifest()
    conn_key = str(connection_id)
    conn_data = manifest["connections"].pop(conn_key, None)
    _save_manifest(manifest)

    if not conn_data:
        return
    for table in conn_data.get("tables", []):
        try:
            if os.path.exists(table["parquet_path"]):
                os.remove(table["parquet_path"])
        except Exception as e:
            print(f"⚠️  Could not remove parquet file for table '{table['table']}': {e}")

    conn_dir = os.path.join(SPREADSHEET_FOLDER, conn_key)
    try:
        if os.path.isdir(conn_dir) and not os.listdir(conn_dir):
            os.rmdir(conn_dir)
    except Exception:
        pass
