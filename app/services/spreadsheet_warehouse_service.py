"""
Spreadsheet Warehouse - pushes Excel/CSV-derived data (already parsed into
a DataFrame by the existing Parquet-backed path, see spreadsheet_service.py)
into real, dynamically-created Postgres tables in the dedicated
'spreadsheet_db' bind (see config/config.py SQLALCHEMY_BINDS), so the data
can be browsed/edited like a normal database table instead of only being
queryable through the pandas-based chat path.

This is additive to, not a replacement for, the Parquet path - Parquet
stays the source of truth for the existing chat/query feature; this module
is only about the separate "push to a real table" workflow (the Process
button, and later the "use existing table" append flow).

Every DDL/DML statement below interpolates table/column names that have
already been through app.utils.identifiers.sanitize_identifier /
dedupe_identifiers - never raw user input - since psycopg2 has no
parameterization for identifiers (only values).
"""
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text
from psycopg2.extras import execute_values

from app import db
from app.models.spreadsheet_warehouse import SpreadsheetTable, SpreadsheetIngestionRun, SpreadsheetIngestionError
from app.services import spreadsheet_service
from app.utils.identifiers import sanitize_identifier, dedupe_identifiers

BIND_KEY = 'spreadsheet_db'

# Maps spreadsheet_service.classify_column's small portable vocabulary onto
# real Postgres column types - mirrors warehouse_generator._normalize_type's
# role for the (unrelated) external-warehouse-script feature.
_PG_TYPE_MAP = {
    "boolean": "BOOLEAN",
    "number": "DOUBLE PRECISION",
    "date": "TIMESTAMP",
    "text": "TEXT",
}


def _prepare_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Returns a copy of df with sanitized, deduped, SQL-safe column names."""
    out = df.copy()
    out.columns = dedupe_identifiers(out.columns)
    return out


def _unique_pg_table_name(base_slug: str) -> str:
    base_slug = base_slug or "table"
    candidate = f"sp_{base_slug}"[:63]
    n = 2
    while SpreadsheetTable.query.filter_by(pg_table_name=candidate).first() is not None:
        suffix = f"_{n}"
        candidate = f"sp_{base_slug}"[:63 - len(suffix)] + suffix
        n += 1
    return candidate


def _to_python_value(value):
    """Normalizes a pandas/numpy cell value into a plain Python value that
    psycopg2 can bind directly - pandas NaN/NaT and numpy scalar types
    (int64, float64, bool_) otherwise reach the driver as opaque objects it
    doesn't know how to adapt."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _json_safe(value):
    """Same normalization as _to_python_value, but also stringifies
    datetimes - for values stored in the JSON `raw_row` column, which can't
    hold a Python datetime object directly."""
    value = _to_python_value(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def create_table_from_dataframe(df: pd.DataFrame, *, display_name: str, sheet_name, connection_id: int,
                                 company_code, created_by_user_id: int):
    """Creates a brand-new Postgres table in the spreadsheet_db bind shaped
    after df's columns, and records it as a SpreadsheetTable. Returns
    (SpreadsheetTable, prepared_df) - prepared_df has the same sanitized
    column names actually used in the CREATE TABLE, so the caller can pass
    it straight to bulk_insert_rows without re-deriving them."""
    prepared = _prepare_columns(df)

    column_schema = [
        {"name": col, "pg_name": col, "type": spreadsheet_service.classify_column(prepared[col])}
        for col in prepared.columns
    ]

    base_slug = sanitize_identifier(display_name) or f"table_{connection_id}"
    pg_table_name = _unique_pg_table_name(base_slug)

    column_defs = ", ".join(
        f'"{c["pg_name"]}" {_PG_TYPE_MAP.get(c["type"], "TEXT")}' for c in column_schema
    )
    ddl = f'CREATE TABLE "{pg_table_name}" (id SERIAL PRIMARY KEY, {column_defs})'

    engine = db.engines[BIND_KEY]
    with engine.begin() as conn:
        conn.execute(text(ddl))

    table = SpreadsheetTable(
        connection_id=connection_id,
        pg_table_name=pg_table_name,
        display_name=display_name,
        sheet_name=sheet_name,
        column_schema=column_schema,
        row_count=0,
        company_code=company_code,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(table)
    db.session.commit()
    return table, prepared


def bulk_insert_rows(table: SpreadsheetTable, df: pd.DataFrame, *, connection_id: int, mode: str) -> SpreadsheetIngestionRun:
    """Inserts every row of df into table's Postgres table. Tries one fast
    batch insert first; if that fails (a single bad row anywhere poisons
    the whole batch), falls back to inserting row-by-row so exactly the
    failing rows - and only those - are recorded as SpreadsheetIngestionError
    rows instead of the entire upload being rejected."""
    run = SpreadsheetIngestionRun(
        spreadsheet_table_id=table.id,
        connection_id=connection_id,
        mode=mode,
        status='running',
        total_rows=len(df),
    )
    db.session.add(run)
    db.session.commit()

    pg_columns = {c['pg_name'] for c in (table.column_schema or [])}
    # Only columns that exist on the target table are inserted - a column
    # present in df but not on the table (e.g. re-processing a sheet whose
    # header changed) is silently dropped rather than failing the run;
    # narrowing the target table's own shape is out of scope here.
    insert_columns = [c for c in df.columns if c in pg_columns]

    if not insert_columns:
        run.status = 'failed'
        run.error_rows = len(df)
        run.finished_at = datetime.utcnow()
        db.session.commit()
        return run

    records = df[insert_columns].to_dict(orient='records')
    values_rows = [tuple(_to_python_value(rec[col]) for col in insert_columns) for rec in records]

    col_list_sql = ", ".join(f'"{c}"' for c in insert_columns)
    engine = db.engines[BIND_KEY]
    raw_conn = engine.raw_connection()
    success_count = 0
    failures = []  # list of (0-based index, error message)
    try:
        cur = raw_conn.cursor()
        insert_sql = f'INSERT INTO "{table.pg_table_name}" ({col_list_sql}) VALUES %s'
        try:
            execute_values(cur, insert_sql, values_rows)
            raw_conn.commit()
            success_count = len(values_rows)
        except Exception:
            raw_conn.rollback()
            single_insert_sql = (
                f'INSERT INTO "{table.pg_table_name}" ({col_list_sql}) '
                f'VALUES ({", ".join(["%s"] * len(insert_columns))})'
            )
            for i, row_values in enumerate(values_rows):
                try:
                    cur.execute(single_insert_sql, row_values)
                    raw_conn.commit()
                    success_count += 1
                except Exception as row_err:
                    raw_conn.rollback()
                    failures.append((i, str(row_err)))
        cur.close()
    finally:
        raw_conn.close()

    for index, message in failures:
        raw_row = {col: _json_safe(records[index][col]) for col in insert_columns}
        db.session.add(SpreadsheetIngestionError(
            run_id=run.id,
            row_number=index + 1,
            error_message=message,
            raw_row=raw_row,
        ))

    run.success_rows = success_count
    run.error_rows = len(failures)
    run.status = 'success' if not failures else ('failed' if success_count == 0 else 'partial_error')
    run.finished_at = datetime.utcnow()
    table.row_count = (table.row_count or 0) + success_count
    db.session.commit()
    return run


def push_table_to_warehouse(*, connection_id: int, table_name: str, sheet_name, display_name: str,
                             df: pd.DataFrame, company_code, created_by_user_id: int) -> SpreadsheetIngestionRun:
    """Entry point used by the Process button: pushes one spreadsheet-
    service table's current data into its Postgres warehouse table,
    creating that table the first time this connection is processed and
    appending into the same one on every re-process after that (e.g. after
    the underlying file is replaced via the Edit flow) - so clicking
    Process repeatedly never errors on "table already exists"."""
    existing = (
        SpreadsheetTable.query
        .filter_by(connection_id=connection_id, sheet_name=sheet_name)
        .order_by(SpreadsheetTable.id.desc())
        .first()
    )
    if existing:
        prepared = _prepare_columns(df)
        return bulk_insert_rows(existing, prepared, connection_id=connection_id, mode='append_existing')

    table, prepared = create_table_from_dataframe(
        df,
        display_name=display_name,
        sheet_name=sheet_name,
        connection_id=connection_id,
        company_code=company_code,
        created_by_user_id=created_by_user_id,
    )
    return bulk_insert_rows(table, prepared, connection_id=connection_id, mode='new_table')


def get_run_errors(run_id: int):
    return SpreadsheetIngestionError.query.filter_by(run_id=run_id).order_by(SpreadsheetIngestionError.row_number).all()
