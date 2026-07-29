"""
Warehouse ETL script generator.
Builds a runnable Python script using Metamind-discovered table metadata.
"""

from __future__ import annotations

import json
import os
import py_compile
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.models.database_connection import DatabaseConnection
from app.services.automated_metamind import DB_CONFIG as SOURCE_DB_CONFIG


class WarehouseGenerationError(Exception):
    """Raised when script generation inputs are invalid."""


def _metamind_config_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "metamind_router_config.json")


def _load_metamind_tables() -> Dict[str, Dict[str, Any]]:
    config_path = _metamind_config_path()
    if not os.path.exists(config_path):
        raise WarehouseGenerationError("Metamind table metadata file not found")

    with open(config_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    tables = (
        payload.get("routing_menu", {})
        .get("datasources", {})
        .get("DB", {})
        .get("tables", {})
    )

    if not isinstance(tables, dict) or not tables:
        raise WarehouseGenerationError("No discovered tables found in Metamind metadata")

    return tables


def get_discovered_tables() -> List[Dict[str, Any]]:
    """Return a lightweight list of discovered tables and columns for UI use."""
    tables = _load_metamind_tables()
    out: List[Dict[str, Any]] = []

    for table_name, table_info in tables.items():
        columns = table_info.get("columns", []) if isinstance(table_info, dict) else []
        out.append(
            {
                "name": table_name,
                "description": (table_info or {}).get("description", "") if isinstance(table_info, dict) else "",
                "row_count": (table_info or {}).get("row_count") if isinstance(table_info, dict) else None,
                "columns": [
                    {
                        "name": col.get("name"),
                        "data_type": col.get("data_type"),
                        "nullable": col.get("nullable", True),
                    }
                    for col in columns
                    if isinstance(col, dict) and col.get("name")
                ],
            }
        )

    return sorted(out, key=lambda x: x["name"])


def _validate_modes(schema_generator: bool, incremental_load: bool, full_load: bool) -> None:
    if not any([schema_generator, incremental_load, full_load]):
        raise WarehouseGenerationError("Select at least one mode")
    if incremental_load and full_load:
        raise WarehouseGenerationError("Incremental Load and Full Load cannot both be selected")


def _normalize_type(data_type: str) -> str:
    t = (data_type or "").lower()
    if any(x in t for x in ["varchar", "character varying", "char", "text"]):
        return "TEXT"
    if "bigint" in t:
        return "BIGINT"
    if "smallint" in t:
        return "SMALLINT"
    if "int" in t:
        return "INTEGER"
    if any(x in t for x in ["numeric", "decimal"]):
        return "NUMERIC"
    if any(x in t for x in ["double", "real", "float"]):
        return "DOUBLE PRECISION"
    if "boolean" in t:
        return "BOOLEAN"
    if "timestamp" in t:
        return "TIMESTAMP"
    if t == "date" or " date" in t:
        return "DATE"
    if "time" in t:
        return "TIME"
    if "json" in t:
        return "JSONB"
    if "uuid" in t:
        return "UUID"
    return "TEXT"


def _choose_watermark(columns: List[Dict[str, Any]]) -> Tuple[str | None, str | None]:
    if not columns:
        return None, None

    timestamp_priority = [
        "updated_at",
        "modified_at",
        "last_updated",
        "last_modified",
        "created_at",
        "created_on",
    ]
    id_priority = ["id", "row_id", "record_id"]

    def _find_by_name_and_type(names: List[str], type_keywords: List[str]) -> str | None:
        for wanted in names:
            for col in columns:
                name = str(col.get("name", "")).lower()
                data_type = str(col.get("data_type", "")).lower()
                if name == wanted and any(keyword in data_type for keyword in type_keywords):
                    return str(col.get("name"))
        return None

    ts_col = _find_by_name_and_type(timestamp_priority, ["timestamp", "date"])
    if ts_col:
        return ts_col, "timestamp"

    id_col = _find_by_name_and_type(id_priority, ["int", "serial", "bigint", "numeric"])
    if id_col:
        return id_col, "id"

    for col in columns:
        name = str(col.get("name", ""))
        data_type = str(col.get("data_type", "")).lower()
        if "timestamp" in data_type or data_type == "date":
            return name, "timestamp"

    for col in columns:
        name = str(col.get("name", ""))
        data_type = str(col.get("data_type", "")).lower()
        if any(x in data_type for x in ["int", "serial", "bigint", "numeric"]):
            return name, "id"

    return None, None


def _build_table_metadata(raw_tables: Dict[str, Dict[str, Any]], selected_tables: List[str]) -> Dict[str, Any]:
    selected_set = set(selected_tables)
    metadata: Dict[str, Any] = {}

    for table_name, table_info in raw_tables.items():
        if table_name not in selected_set:
            continue
        columns = table_info.get("columns", []) if isinstance(table_info, dict) else []
        sanitized_columns: List[Dict[str, Any]] = []

        for col in columns:
            if not isinstance(col, dict) or not col.get("name"):
                continue
            sanitized_columns.append(
                {
                    "name": col.get("name"),
                    "data_type": col.get("data_type", "text"),
                    "nullable": bool(col.get("nullable", True)),
                    "target_type": _normalize_type(col.get("data_type", "text")),
                }
            )

        watermark_column, watermark_kind = _choose_watermark(sanitized_columns)

        metadata[table_name] = {
            "columns": sanitized_columns,
            "watermark_column": watermark_column,
            "watermark_kind": watermark_kind,
        }

    if not metadata:
        raise WarehouseGenerationError("No valid selected tables found in Metamind metadata")

    return metadata


def _target_connection_payload(target_connection: DatabaseConnection) -> Dict[str, Any]:
    if not target_connection:
        raise WarehouseGenerationError("Target connection not found")

    return {
        "host": target_connection.host,
        "port": target_connection.port or 5432,
        "dbname": target_connection.database,
        "user": target_connection.username,
        "password": target_connection.password,
    }


def _render_script(
    *,
    table_metadata: Dict[str, Any],
    selected_tables: List[str],
    schema_generator: bool,
    incremental_load: bool,
    full_load: bool,
    target_config: Dict[str, Any],
) -> str:
    generated_at = datetime.utcnow().isoformat() + "Z"
    script = f'''#!/usr/bin/env python3
"""
Auto-generated by Saarthi Warehouse Generator.
Generated at: {generated_at}
"""

import traceback
from datetime import datetime

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

SOURCE_DB_CONFIG = {json.dumps(SOURCE_DB_CONFIG, indent=4)}
TARGET_DB_CONFIG = {json.dumps(target_config, indent=4)}
TABLE_METADATA = {json.dumps(table_metadata, indent=4)}
SELECTED_TABLES = {json.dumps(selected_tables, indent=4)}

RUN_SCHEMA_GENERATOR = {str(schema_generator)}
RUN_INCREMENTAL_LOAD = {str(incremental_load)}
RUN_FULL_LOAD = {str(full_load)}


def ensure_metadata_table(target_conn):
    with target_conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS warehouse_sync_log (
                id BIGSERIAL PRIMARY KEY,
                table_name TEXT NOT NULL,
                load_type TEXT NOT NULL,
                rows_loaded INTEGER DEFAULT 0,
                run_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                status TEXT NOT NULL,
                error_message TEXT
            );
            """
        )
    target_conn.commit()


def log_sync(target_conn, table_name, load_type, rows_loaded, status, error_message=None):
    with target_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO warehouse_sync_log (
                table_name, load_type, rows_loaded, run_timestamp, status, error_message
            ) VALUES (%s, %s, %s, NOW(), %s, %s)
            """,
            (table_name, load_type, rows_loaded, status, error_message),
        )
    target_conn.commit()


def create_table_if_needed(target_conn, table_name, columns):
    column_defs = []
    for col in columns:
        nullable = "" if col.get("nullable", True) else " NOT NULL"
        column_defs.append(f'"{{col["name"]}}" {{col.get("target_type", "TEXT")}}{{nullable}}')

    ddl = f'CREATE TABLE IF NOT EXISTS "{{table_name}}" ({{", ".join(column_defs)}});'

    with target_conn.cursor() as cur:
        cur.execute(ddl)
    target_conn.commit()


def fetch_source_rows(source_conn, table_name, column_names, where_clause=None, params=None):
    query = sql.SQL("SELECT {{fields}} FROM {{table}}").format(
        fields=sql.SQL(", ").join([sql.Identifier(col) for col in column_names]),
        table=sql.Identifier(table_name),
    )

    if where_clause:
        query = sql.SQL("{{base}} WHERE {{where}} ").format(
            base=query,
            where=where_clause,
        )

    with source_conn.cursor() as cur:
        cur.execute(query, params or [])
        return cur.fetchall()


def replace_table_data(target_conn, table_name, column_names, rows):
    with target_conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE TABLE {{table}};").format(table=sql.Identifier(table_name)))

        if rows:
            insert_query = sql.SQL("INSERT INTO {{table}} ({{fields}}) VALUES %s").format(
                table=sql.Identifier(table_name),
                fields=sql.SQL(", ").join([sql.Identifier(col) for col in column_names]),
            )
            execute_values(cur, insert_query, rows)

    target_conn.commit()


def append_table_data(target_conn, table_name, column_names, rows):
    if not rows:
        return

    with target_conn.cursor() as cur:
        insert_query = sql.SQL("INSERT INTO {{table}} ({{fields}}) VALUES %s").format(
            table=sql.Identifier(table_name),
            fields=sql.SQL(", ").join([sql.Identifier(col) for col in column_names]),
        )
        execute_values(cur, insert_query, rows)

    target_conn.commit()


def get_last_successful_run(target_conn, table_name, load_type):
    with target_conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_timestamp
            FROM warehouse_sync_log
            WHERE table_name = %s
              AND load_type = %s
              AND status = 'success'
            ORDER BY run_timestamp DESC
            LIMIT 1
            """,
            (table_name, load_type),
        )
        row = cur.fetchone()
        return row[0] if row else None


def load_schema(target_conn):
    for table_name in SELECTED_TABLES:
        table_info = TABLE_METADATA.get(table_name, {{}})
        columns = table_info.get("columns", [])

        try:
            create_table_if_needed(target_conn, table_name, columns)
            log_sync(target_conn, table_name, "schema", 0, "success", None)
        except Exception as err:
            target_conn.rollback()
            log_sync(target_conn, table_name, "schema", 0, "failed", str(err))


def run_full_load(source_conn, target_conn):
    for table_name in SELECTED_TABLES:
        table_info = TABLE_METADATA.get(table_name, {{}})
        columns = table_info.get("columns", [])
        column_names = [col["name"] for col in columns]

        try:
            if not column_names:
                log_sync(target_conn, table_name, "full", 0, "success", None)
                continue

            rows = fetch_source_rows(source_conn, table_name, column_names)
            replace_table_data(target_conn, table_name, column_names, rows)
            log_sync(target_conn, table_name, "full", len(rows), "success", None)
        except Exception as err:
            target_conn.rollback()
            log_sync(target_conn, table_name, "full", 0, "failed", str(err))


def run_incremental_load(source_conn, target_conn):
    for table_name in SELECTED_TABLES:
        table_info = TABLE_METADATA.get(table_name, {{}})
        columns = table_info.get("columns", [])
        column_names = [col["name"] for col in columns]
        watermark_column = table_info.get("watermark_column")
        watermark_kind = table_info.get("watermark_kind")

        try:
            if not column_names:
                log_sync(target_conn, table_name, "incremental", 0, "success", None)
                continue

            if not watermark_column:
                # No known watermark; fail this table and continue others.
                log_sync(target_conn, table_name, "incremental", 0, "failed", "No watermark column found")
                continue

            rows = []
            if watermark_kind == "timestamp":
                last_run_ts = get_last_successful_run(target_conn, table_name, "incremental")
                where_clause = sql.SQL("{{col}} > %s").format(col=sql.Identifier(watermark_column))
                if last_run_ts:
                    rows = fetch_source_rows(source_conn, table_name, column_names, where_clause, [last_run_ts])
                else:
                    rows = fetch_source_rows(source_conn, table_name, column_names)
            else:
                with target_conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SELECT COALESCE(MAX({{col}}), 0) FROM {{table}}").format(
                            col=sql.Identifier(watermark_column),
                            table=sql.Identifier(table_name),
                        )
                    )
                    max_target_id = cur.fetchone()[0] or 0
                where_clause = sql.SQL("{{col}} > %s").format(col=sql.Identifier(watermark_column))
                rows = fetch_source_rows(source_conn, table_name, column_names, where_clause, [max_target_id])

            append_table_data(target_conn, table_name, column_names, rows)
            log_sync(target_conn, table_name, "incremental", len(rows), "success", None)
        except Exception as err:
            target_conn.rollback()
            log_sync(target_conn, table_name, "incremental", 0, "failed", str(err))


def main():
    source_conn = None
    target_conn = None

    try:
        source_conn = psycopg2.connect(**SOURCE_DB_CONFIG)
        target_conn = psycopg2.connect(**TARGET_DB_CONFIG)
        ensure_metadata_table(target_conn)

        if RUN_SCHEMA_GENERATOR:
            load_schema(target_conn)

        if RUN_FULL_LOAD:
            run_full_load(source_conn, target_conn)

        if RUN_INCREMENTAL_LOAD:
            run_incremental_load(source_conn, target_conn)

        print("Warehouse ETL run completed")
    except Exception:
        print("Warehouse ETL run failed")
        print(traceback.format_exc())
    finally:
        if source_conn:
            source_conn.close()
        if target_conn:
            target_conn.close()


if __name__ == "__main__":
    main()
'''
    return script


def _validate_python_script(script: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp_file:
        tmp_file.write(script)
        temp_path = tmp_file.name

    try:
        py_compile.compile(temp_path, doraise=True)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def generate_script(
    *,
    target_connection: DatabaseConnection,
    selected_tables: List[str],
    schema_generator: bool,
    incremental_load: bool,
    full_load: bool,
) -> Tuple[str, str]:
    """Build and validate a warehouse ETL script."""
    _validate_modes(schema_generator, incremental_load, full_load)

    if not selected_tables:
        raise WarehouseGenerationError("Select at least one table")

    raw_tables = _load_metamind_tables()
    table_metadata = _build_table_metadata(raw_tables, selected_tables)
    target_config = _target_connection_payload(target_connection)

    script = _render_script(
        table_metadata=table_metadata,
        selected_tables=selected_tables,
        schema_generator=schema_generator,
        incremental_load=incremental_load,
        full_load=full_load,
        target_config=target_config,
    )

    try:
        _validate_python_script(script)
    except Exception:
        # Regenerate once with the same deterministic inputs if compile fails.
        script = _render_script(
            table_metadata=table_metadata,
            selected_tables=selected_tables,
            schema_generator=schema_generator,
            incremental_load=incremental_load,
            full_load=full_load,
            target_config=target_config,
        )
        _validate_python_script(script)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"warehouse_etl_{timestamp}.py"
    return script, filename
