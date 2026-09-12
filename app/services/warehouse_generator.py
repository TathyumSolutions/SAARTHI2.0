"""
Warehouse ETL script generator plus in-process execution, health checks,
table-level mapping (including joins across multiple source tables), and
per-column mapping/transformation support.

Sources: DB-track tables (live Postgres, via Metamind) and SPREADSHEET-track
tables (Excel/CSV uploads stored as Parquet, via spreadsheet_service). Target
is always a Postgres connection marked with config.role == "warehouse_target"
on a DatabaseConnection row.

Table-level mapping (per target connection, stored at
connection.config["warehouse_table_groups"]) groups one or more source
tables into a single target table. A group with exactly one source table is
a straight 1:1 mapping (the default for every discovered table that hasn't
been grouped otherwise); a group with more than one source table is joined
together (INNER or LEFT, on explicit join keys) before column mapping is
applied. Joining a database-sourced table with a spreadsheet-sourced table
in the same group isn't supported.

Column mapping overlay (per target connection, per target table, stored at
connection.config["warehouse_mapping"][target_table_name]) lets a column be
renamed, retyped, excluded, or computed via a transform expression instead
of the default 1:1 copy. transform_expr is a raw SQL expression (DB
sources) or a pandas .eval() expression (single-source spreadsheet tables
only), evaluated with the same trust boundary as the app's existing raw-SQL
query endpoint: it runs only against connections the requesting user
already configured.
"""

from __future__ import annotations

import json
import os
import py_compile
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

from app.models.database_connection import DatabaseConnection
from app.services.automated_metamind import DB_CONFIG as SOURCE_DB_CONFIG
from app.utils.crypto import decrypt


class WarehouseGenerationError(Exception):
    """Raised when script generation/execution inputs are invalid."""


ALLOWED_TARGET_TYPES = {
    "TEXT", "BIGINT", "SMALLINT", "INTEGER", "NUMERIC", "DOUBLE PRECISION",
    "BOOLEAN", "TIMESTAMP", "DATE", "TIME", "JSONB", "UUID",
}

ALLOWED_JOIN_TYPES = {"INNER", "LEFT"}


# ============================================================
# Discovery: merge DB-track and SPREADSHEET-track tables
# ============================================================

def _load_metamind_tables(user_id: int) -> Dict[str, Dict[str, Any]]:
    """Computes this user's own router config live (see
    automated_metamind.generate_router_config) and merges both the DB and
    SPREADSHEET tracks into one flat table map, each entry tagged with
    source_type so downstream code knows how to read rows from it."""
    from app.services.automated_metamind import generate_router_config

    menu = generate_router_config(user_id)
    if not menu:
        raise WarehouseGenerationError("Metamind table metadata not found for this user")

    datasources = menu.get("routing_menu", {}).get("datasources", {})
    tables: Dict[str, Dict[str, Any]] = {}

    db_tables = datasources.get("DB", {}).get("tables", {})
    if isinstance(db_tables, dict):
        for name, info in db_tables.items():
            if isinstance(info, dict):
                tables[name] = {**info, "source_type": "DB"}

    spreadsheet_tables = datasources.get("SPREADSHEET", {}).get("tables", {})
    if isinstance(spreadsheet_tables, dict):
        for name, info in spreadsheet_tables.items():
            if not isinstance(info, dict) or name in tables:
                continue
            columns = [
                {"name": c.get("name"), "data_type": c.get("type", "text"), "nullable": True}
                for c in info.get("columns", []) if isinstance(c, dict) and c.get("name")
            ]
            tables[name] = {
                "description": info.get("description", ""),
                "row_count": info.get("row_count"),
                "columns": columns,
                "source_type": "SPREADSHEET",
            }

    if not tables:
        raise WarehouseGenerationError("No discovered tables found in Metamind metadata")

    return tables


def _discovered_list(tables: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for table_name, table_info in tables.items():
        columns = table_info.get("columns", []) if isinstance(table_info, dict) else []
        out.append(
            {
                "name": table_name,
                "description": (table_info or {}).get("description", "") if isinstance(table_info, dict) else "",
                "row_count": (table_info or {}).get("row_count") if isinstance(table_info, dict) else None,
                "source_type": (table_info or {}).get("source_type", "DB") if isinstance(table_info, dict) else "DB",
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


def get_discovered_tables(user_id: int) -> List[Dict[str, Any]]:
    """Return a lightweight list of discovered tables and columns for UI use."""
    return _discovered_list(_load_metamind_tables(user_id))


def get_raw_table_columns(user_id: int, table_name: str) -> List[Dict[str, Any]]:
    """Raw (pre-mapping) columns for one discovered table."""
    tables = _load_metamind_tables(user_id)
    table_info = tables.get(table_name)
    if not table_info:
        raise WarehouseGenerationError(f"Table '{table_name}' not found in discovered metadata")
    return [c for c in table_info.get("columns", []) if isinstance(c, dict) and c.get("name")]


def get_group_source_columns(user_id: int, source_tables: List[str]) -> Tuple[List[Dict[str, Any]], str]:
    """Raw columns for every source table in a mapping group, each tagged
    with its own source_table. Also returns the group's uniform
    source_type (DB or SPREADSHEET) - mixing the two in one group is
    rejected here, before any mapping/execution work happens."""
    tables = _load_metamind_tables(user_id)
    tagged: List[Dict[str, Any]] = []
    source_type: Optional[str] = None

    for table_name in source_tables:
        info = tables.get(table_name)
        if not info:
            raise WarehouseGenerationError(f"Table '{table_name}' not found in discovered metadata")
        this_type = info.get("source_type", "DB")
        if source_type is None:
            source_type = this_type
        elif this_type != source_type and len(source_tables) > 1:
            raise WarehouseGenerationError(
                "Cannot join a database-sourced table with a spreadsheet-sourced table in the same mapping"
            )
        for col in info.get("columns", []):
            if isinstance(col, dict) and col.get("name"):
                tagged.append({**col, "source_table": table_name})

    return tagged, (source_type or "DB")


# ============================================================
# Table-level mapping (source tables -> target table, with joins)
# ============================================================

def _get_target_groups(target_connection: Optional[DatabaseConnection]) -> Dict[str, Any]:
    if not target_connection:
        return {}
    config = target_connection.config or {}
    groups = config.get("warehouse_table_groups") if isinstance(config, dict) else None
    return groups if isinstance(groups, dict) else {}


def get_table_groups(target_connection: Optional[DatabaseConnection], user_id: int) -> Dict[str, Any]:
    """Effective table-level mapping: every saved group, plus a default 1:1
    group (target table name == source table name) for any discovered
    table not already covered by a saved group. Always fully populated so
    the UI never has to special-case "no mapping saved yet"."""
    raw_tables = _load_metamind_tables(user_id)
    discovered = _discovered_list(raw_tables)
    discovered_names = {t["name"] for t in discovered}

    saved = _get_target_groups(target_connection)
    groups: Dict[str, Any] = {}
    covered_sources = set()

    for target_name, g in saved.items():
        if not isinstance(g, dict):
            continue
        source_tables = [t for t in (g.get("source_tables") or []) if t in discovered_names]
        if not source_tables:
            continue
        groups[target_name] = {
            "source_tables": source_tables,
            "join_type": g.get("join_type") if g.get("join_type") in ALLOWED_JOIN_TYPES else "INNER",
            "join_keys": g.get("join_keys") or [],
        }
        covered_sources.update(source_tables)

    for table in discovered:
        name = table["name"]
        if name in covered_sources or name in groups:
            continue
        groups[name] = {"source_tables": [name], "join_type": "INNER", "join_keys": []}

    return {"tables": discovered, "groups": groups}


def save_table_groups(target_connection: DatabaseConnection, groups: Dict[str, Any]) -> None:
    """groups: {target_table_name: {source_tables: [...], join_type, join_keys: [
    {left_table, left_column, right_table, right_column}, ...]}}"""
    from app import db as _db

    sanitized: Dict[str, Any] = {}
    for target_name, g in (groups or {}).items():
        target_name = (target_name or "").strip()
        if not target_name or not isinstance(g, dict):
            continue

        source_tables = [s.strip() for s in (g.get("source_tables") or []) if isinstance(s, str) and s.strip()]
        if not source_tables:
            continue

        is_joined = len(source_tables) > 1
        join_type = (g.get("join_type") or "INNER").strip().upper()
        if join_type not in ALLOWED_JOIN_TYPES:
            join_type = "INNER"

        join_keys = []
        if is_joined:
            for jk in (g.get("join_keys") or []):
                if not isinstance(jk, dict):
                    continue
                lt, lc = jk.get("left_table"), jk.get("left_column")
                rt, rc = jk.get("right_table"), jk.get("right_column")
                if lt in source_tables and rt in source_tables and lc and rc:
                    join_keys.append({
                        "left_table": lt, "left_column": lc,
                        "right_table": rt, "right_column": rc,
                    })

        sanitized[target_name] = {
            "source_tables": source_tables,
            "join_type": join_type if is_joined else "INNER",
            "join_keys": join_keys,
        }

    config = dict(target_connection.config or {})
    config["warehouse_table_groups"] = sanitized
    target_connection.config = config
    _db.session.commit()


# ============================================================
# Column mapping / transformation overlay (stored on the target connection)
# ============================================================

def _get_target_mappings(target_connection: Optional[DatabaseConnection]) -> Dict[str, Any]:
    if not target_connection:
        return {}
    config = target_connection.config or {}
    mapping = config.get("warehouse_mapping") if isinstance(config, dict) else None
    return mapping if isinstance(mapping, dict) else {}


def get_table_mapping(target_connection: Optional[DatabaseConnection], target_table_name: str) -> Dict[str, Any]:
    """Saved per-column overrides for one target table, keyed by
    "source_table::source_column" (or, for mappings saved before table
    groups existed, plain source_column)."""
    mappings = _get_target_mappings(target_connection)
    table_mapping = mappings.get(target_table_name, {})
    columns = table_mapping.get("columns", {}) if isinstance(table_mapping, dict) else {}
    return columns if isinstance(columns, dict) else {}


def _sanitize_target_type(target_type: Optional[str], fallback: str) -> str:
    candidate = (target_type or "").strip().upper()
    return candidate if candidate in ALLOWED_TARGET_TYPES else fallback


def save_table_mapping(target_connection: DatabaseConnection, target_table_name: str, columns: List[Dict[str, Any]]) -> None:
    """columns: [{source_table, source_name, target_name, target_type, include, transform_expr}, ...]"""
    from app import db as _db

    sanitized: Dict[str, Any] = {}
    for col in columns or []:
        source_name = (col or {}).get("source_name")
        if not source_name:
            continue
        source_table = (col or {}).get("source_table")
        key = f"{source_table}::{source_name}" if source_table else source_name
        target_name = (col.get("target_name") or source_name).strip() or source_name
        sanitized[key] = {
            "target_name": target_name,
            "target_type": _sanitize_target_type(col.get("target_type"), "") or None,
            "include": bool(col.get("include", True)),
            "transform_expr": (col.get("transform_expr") or "").strip() or None,
        }

    mappings = dict(_get_target_mappings(target_connection))
    mappings[target_table_name] = {"columns": sanitized}

    config = dict(target_connection.config or {})
    config["warehouse_mapping"] = mappings
    target_connection.config = config
    _db.session.commit()


def _apply_mapping(tagged_raw_columns: List[Dict[str, Any]], mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for col in tagged_raw_columns:
        if not isinstance(col, dict) or not col.get("name"):
            continue
        source_name = col["name"]
        source_table = col.get("source_table")
        key = f"{source_table}::{source_name}" if source_table else source_name
        override = mapping.get(key)
        if override is None:
            # Back-compat with mappings saved before table groups existed,
            # when the key was always the plain source column name.
            override = mapping.get(source_name, {}) if isinstance(mapping, dict) else {}
        if override.get("include") is False:
            continue

        default_type = _normalize_type(col.get("data_type", "text"))
        target_type = _sanitize_target_type(override.get("target_type"), default_type)

        result.append({
            "source_table": source_table,
            "source_name": source_name,
            "target_name": (override.get("target_name") or source_name),
            "data_type": col.get("data_type", "text"),
            "nullable": bool(col.get("nullable", True)),
            "target_type": target_type,
            "transform_expr": override.get("transform_expr") or None,
        })
    return result


# ============================================================
# AI-assisted transformation suggestions (editable, never auto-applied)
# ============================================================

def _heuristic_suggestions(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for col in columns:
        name = col.get("name") or ""
        data_type = (col.get("data_type") or "").lower()
        lowered = name.lower()
        transform_expr = None
        rationale = "No change suggested."

        is_text = "text" in data_type or "char" in data_type
        if is_text and any(k in lowered for k in ["email", "code", "sku"]):
            transform_expr = f'LOWER(TRIM("{name}"))'
            rationale = "Normalize casing/whitespace on a code-like text column."
        elif is_text and any(k in lowered for k in ["name", "city", "state", "branch", "address"]):
            transform_expr = f'TRIM("{name}")'
            rationale = "Trim stray whitespace on a free-text column."

        out.append({
            "source_table": col.get("source_table"),
            "source_name": name,
            "suggested_target_name": name,
            "suggested_target_type": _normalize_type(col.get("data_type", "text")),
            "suggested_transform_expr": transform_expr,
            "rationale": rationale,
        })
    return out


def suggest_transformations(table_name: str, columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns editable suggestions: [{source_table, source_name,
    suggested_target_name, suggested_target_type, suggested_transform_expr,
    rationale}]. Falls back to a small rule-based pass when no
    OPENAI_API_KEY is configured or the LLM call fails, so the feature
    never hard-depends on an LLM provider."""
    fallback = _heuristic_suggestions(columns)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return fallback

    try:
        from typing import Optional as _Optional

        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
        from pydantic import BaseModel, Field

        class ColumnSuggestion(BaseModel):
            source_name: str
            target_name: str
            target_type: str = Field(
                description="One of TEXT, BIGINT, INTEGER, NUMERIC, DOUBLE PRECISION, BOOLEAN, TIMESTAMP, DATE, JSONB, UUID"
            )
            transform_expr: _Optional[str] = Field(
                default=None,
                description="A Postgres SQL expression producing this column's value from the source table's own columns, or null for a straight copy",
            )
            rationale: str

        class ColumnSuggestionList(BaseModel):
            suggestions: List[ColumnSuggestion]

        columns_desc = "\n".join(
            f"- {c.get('name')}: type={c.get('data_type')}, nullable={c.get('nullable', True)}"
            for c in columns
        )
        system_prompt = (
            "You are a data warehouse ETL assistant. Given a source table's columns, "
            "propose a target column name, a target Postgres type, and an optional SQL "
            "transform expression (referencing only this table's own source column "
            "names, quoted, e.g. TRIM(\"name\")) for low-risk cleanup like trimming, "
            "casing, or type casting. Keep target_name equal to source_name and "
            "transform_expr null unless there is a clear, low-risk improvement."
        )

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, openai_api_key=api_key)
        structured_llm = llm.with_structured_output(ColumnSuggestionList)
        result = structured_llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Table: {table_name}\nColumns:\n{columns_desc}"),
        ])

        by_name = {s.source_name: s for s in result.suggestions}
        merged = []
        for col in columns:
            name = col.get("name")
            hit = by_name.get(name)
            if hit:
                merged.append({
                    "source_table": col.get("source_table"),
                    "source_name": name,
                    "suggested_target_name": hit.target_name or name,
                    "suggested_target_type": _sanitize_target_type(hit.target_type, _normalize_type(col.get("data_type", "text"))),
                    "suggested_transform_expr": hit.transform_expr,
                    "rationale": hit.rationale,
                })
            else:
                merged.append(next(s for s in fallback if s["source_name"] == name))
        return merged
    except Exception as exc:
        print(f"⚠️ [WAREHOUSE] LLM transform suggestion failed, using heuristic fallback: {exc}")
        return fallback


# ============================================================
# Shared metadata build (used by generate/run/health alike)
# ============================================================

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
    if any(x in t for x in ["numeric", "decimal", "number"]):
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


def _choose_watermark(columns: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Picks an incremental watermark column from columns that aren't
    themselves computed (a transform_expr column can't reliably drive
    incremental filtering). Returns {source_name, source_table, target_name,
    kind} or None. Only ever called for single-source (non-joined) groups."""
    candidates = [c for c in columns if not c.get("transform_expr")]
    if not candidates:
        return None

    timestamp_priority = ["updated_at", "modified_at", "last_updated", "last_modified", "created_at", "created_on"]
    id_priority = ["id", "row_id", "record_id"]

    def _find(names: List[str], type_keywords: List[str]) -> Optional[Dict[str, Any]]:
        for wanted in names:
            for col in candidates:
                if str(col["target_name"]).lower() == wanted and any(
                    k in str(col.get("data_type", "")).lower() for k in type_keywords
                ):
                    return col
        return None

    col = _find(timestamp_priority, ["timestamp", "date"])
    if col:
        return {"source_name": col["source_name"], "source_table": col.get("source_table"), "target_name": col["target_name"], "kind": "timestamp"}

    col = _find(id_priority, ["int", "serial", "bigint", "numeric"])
    if col:
        return {"source_name": col["source_name"], "source_table": col.get("source_table"), "target_name": col["target_name"], "kind": "id"}

    for col in candidates:
        data_type = str(col.get("data_type", "")).lower()
        if "timestamp" in data_type or data_type == "date":
            return {"source_name": col["source_name"], "source_table": col.get("source_table"), "target_name": col["target_name"], "kind": "timestamp"}

    for col in candidates:
        data_type = str(col.get("data_type", "")).lower()
        if any(x in data_type for x in ["int", "serial", "bigint", "numeric"]):
            return {"source_name": col["source_name"], "source_table": col.get("source_table"), "target_name": col["target_name"], "kind": "id"}

    return None


def _build_table_metadata(
    raw_tables: Dict[str, Dict[str, Any]],
    groups: Dict[str, Any],
    selected_targets: List[str],
    mappings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    mappings = mappings or {}
    metadata: Dict[str, Any] = {}

    for target_name in selected_targets:
        group = groups.get(target_name)
        if not group:
            continue

        source_tables = group.get("source_tables") or []
        is_joined = len(source_tables) > 1

        tagged_raw_columns: List[Dict[str, Any]] = []
        source_type: Optional[str] = None
        mismatch = False
        for table_name in source_tables:
            table_info = raw_tables.get(table_name)
            if not isinstance(table_info, dict):
                continue
            this_type = table_info.get("source_type", "DB")
            if source_type is None:
                source_type = this_type
            elif this_type != source_type:
                mismatch = True
            for col in table_info.get("columns", []):
                if isinstance(col, dict) and col.get("name"):
                    tagged_raw_columns.append({**col, "source_table": table_name})

        if mismatch:
            raise WarehouseGenerationError(
                f"Target '{target_name}': cannot join database-sourced and spreadsheet-sourced tables together"
            )
        if not tagged_raw_columns:
            continue

        table_mapping = mappings.get(target_name, {})
        column_overrides = table_mapping.get("columns", {}) if isinstance(table_mapping, dict) else {}

        columns = _apply_mapping(tagged_raw_columns, column_overrides)
        if not columns:
            continue

        watermark = _choose_watermark(columns) if (source_type == "DB" and not is_joined) else None

        entry: Dict[str, Any] = {
            "source_type": source_type or "DB",
            "source_tables": source_tables,
            "join_type": group.get("join_type", "INNER"),
            "join_keys": group.get("join_keys", []),
            "is_joined": is_joined,
            "columns": columns,
            "watermark_column": watermark["source_name"] if watermark else None,
            "watermark_source_table": watermark["source_table"] if watermark else None,
            "watermark_target_column": watermark["target_name"] if watermark else None,
            "watermark_kind": watermark["kind"] if watermark else None,
        }

        if source_type == "SPREADSHEET" and not is_joined:
            from app.services.spreadsheet_service import get_table_record
            record = get_table_record(source_tables[0]) or {}
            entry["parquet_path"] = record.get("parquet_path")

        metadata[target_name] = entry

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
        "password": decrypt(target_connection.password) if target_connection.password else "",
    }


# ============================================================
# In-process execution (no arbitrary code exec - real functions, run
# directly from a validated job spec, shared by /run and /health)
# ============================================================

def _ensure_metadata_table(target_conn) -> None:
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


def _log_sync(target_conn, table_name, load_type, rows_loaded, status, error_message=None) -> None:
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


def _create_table_if_needed(target_conn, table_name: str, columns: List[Dict[str, Any]]) -> None:
    column_defs = [
        sql.SQL("{} {}{}").format(
            sql.Identifier(col["target_name"]),
            sql.SQL(col.get("target_type", "TEXT")),
            sql.SQL("" if col.get("nullable", True) else " NOT NULL"),
        )
        for col in columns
    ]
    ddl = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
        sql.Identifier(table_name), sql.SQL(", ").join(column_defs)
    )
    with target_conn.cursor() as cur:
        cur.execute(ddl)
    target_conn.commit()


def _select_expr(col: Dict[str, Any]):
    if col.get("transform_expr"):
        return sql.SQL(col["transform_expr"])
    if col.get("source_table"):
        return sql.Identifier(col["source_table"], col["source_name"])
    return sql.Identifier(col["source_name"])


def _from_clause(source_tables: List[str], join_type: str, join_keys: List[Dict[str, str]]):
    """Builds a FROM clause across one or more source tables. Extra source
    tables not connected to the joined set by any join key fall back to a
    CROSS JOIN rather than silently being dropped."""
    if len(source_tables) <= 1:
        return sql.Identifier(source_tables[0])

    from_sql = sql.Identifier(source_tables[0])
    joined = {source_tables[0]}
    remaining = list(join_keys)

    for _ in range(len(source_tables) - 1):
        applied = False
        for jk in list(remaining):
            lt, lc, rt, rc = jk["left_table"], jk["left_column"], jk["right_table"], jk["right_column"]
            if lt in joined and rt not in joined:
                pass
            elif rt in joined and lt not in joined:
                lt, lc, rt, rc = rt, rc, lt, lc
            else:
                continue
            from_sql = sql.SQL("{} {} JOIN {} ON {} = {}").format(
                from_sql, sql.SQL(join_type), sql.Identifier(rt),
                sql.Identifier(lt, lc), sql.Identifier(rt, rc),
            )
            joined.add(rt)
            remaining.remove(jk)
            applied = True
            break

        if not applied:
            missing = next((t for t in source_tables if t not in joined), None)
            if missing:
                from_sql = sql.SQL("{} CROSS JOIN {}").format(from_sql, sql.Identifier(missing))
                joined.add(missing)

    return from_sql


def _fetch_db_rows(source_conn, info, columns, where_clause=None, params=None):
    fields = sql.SQL(", ").join(
        sql.SQL("{} AS {}").format(_select_expr(col), sql.Identifier(col["target_name"]))
        for col in columns
    )
    from_sql = _from_clause(info["source_tables"], info.get("join_type", "INNER"), info.get("join_keys", []))
    query = sql.SQL("SELECT {} FROM {}").format(fields, from_sql)
    if where_clause:
        query = sql.SQL("{} WHERE {}").format(query, where_clause)

    with source_conn.cursor() as cur:
        cur.execute(query, params or [])
        return cur.fetchall()


def _fetch_spreadsheet_rows(source_tables, join_type, join_keys, columns):
    from app.services.spreadsheet_service import get_table_df

    if len(source_tables) == 1:
        df = get_table_df(source_tables[0])
        data = {}
        for col in columns:
            series = None
            if col.get("transform_expr"):
                try:
                    series = df.eval(col["transform_expr"])
                except Exception:
                    series = None
            if series is None:
                series = df[col["source_name"]] if col["source_name"] in df.columns else pd.Series([None] * len(df))
            data[col["target_name"]] = series

        built = pd.DataFrame(data)
        built = built.where(pd.notnull(built), None)
        return [tuple(row) for row in built.itertuples(index=False, name=None)]

    # Multi-source join: every column is renamed "<table>__<column>" before
    # merging so there's never any ambiguity about which table a name came
    # from. transform_expr isn't supported across a spreadsheet join - a
    # straight copy is used instead (this is enforced at save time).
    how = "left" if join_type == "LEFT" else "inner"
    dfs = {}
    for table_name in source_tables:
        d = get_table_df(table_name).copy()
        d.columns = [f"{table_name}__{c}" for c in d.columns]
        dfs[table_name] = d

    merged = dfs[source_tables[0]]
    joined = {source_tables[0]}
    remaining = list(join_keys)
    for _ in range(len(source_tables) - 1):
        applied = False
        for jk in list(remaining):
            lt, lc, rt, rc = jk["left_table"], jk["left_column"], jk["right_table"], jk["right_column"]
            if lt in joined and rt not in joined:
                pass
            elif rt in joined and lt not in joined:
                lt, lc, rt, rc = rt, rc, lt, lc
            else:
                continue
            merged = merged.merge(dfs[rt], how=how, left_on=f"{lt}__{lc}", right_on=f"{rt}__{rc}")
            joined.add(rt)
            remaining.remove(jk)
            applied = True
            break
        if not applied:
            missing = next((t for t in source_tables if t not in joined), None)
            if missing:
                merged = merged.merge(dfs[missing], how="cross")
                joined.add(missing)

    data = {}
    for col in columns:
        key = f"{col.get('source_table')}__{col['source_name']}"
        series = merged[key] if key in merged.columns else pd.Series([None] * len(merged))
        data[col["target_name"]] = series

    built = pd.DataFrame(data)
    built = built.where(pd.notnull(built), None)
    return [tuple(row) for row in built.itertuples(index=False, name=None)]


def _fetch_rows_for_table(source_conn, info):
    if info["source_type"] == "SPREADSHEET":
        return _fetch_spreadsheet_rows(info["source_tables"], info.get("join_type", "INNER"), info.get("join_keys", []), info["columns"])
    return _fetch_db_rows(source_conn, info, info["columns"])


def _replace_rows(target_conn, table_name, target_columns, rows) -> None:
    with target_conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(table_name)))
        if rows:
            insert_query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                sql.Identifier(table_name),
                sql.SQL(", ").join(sql.Identifier(c) for c in target_columns),
            )
            execute_values(cur, insert_query, rows)
    target_conn.commit()


def _append_rows(target_conn, table_name, target_columns, rows) -> None:
    if not rows:
        return
    with target_conn.cursor() as cur:
        insert_query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
            sql.Identifier(table_name),
            sql.SQL(", ").join(sql.Identifier(c) for c in target_columns),
        )
        execute_values(cur, insert_query, rows)
    target_conn.commit()


def _get_last_successful_run(target_conn, table_name, load_type):
    with target_conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_timestamp FROM warehouse_sync_log
            WHERE table_name = %s AND load_type = %s AND status = 'success'
            ORDER BY run_timestamp DESC LIMIT 1
            """,
            (table_name, load_type),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _run_schema_for_table(target_conn, table_name, info) -> Dict[str, Any]:
    try:
        _create_table_if_needed(target_conn, table_name, info["columns"])
        _log_sync(target_conn, table_name, "schema", 0, "success", None)
        return {"table": table_name, "load_type": "schema", "rows_loaded": 0, "status": "success", "error_message": None}
    except Exception as err:
        target_conn.rollback()
        _log_sync(target_conn, table_name, "schema", 0, "failed", str(err))
        return {"table": table_name, "load_type": "schema", "rows_loaded": 0, "status": "failed", "error_message": str(err)}


def _run_full_for_table(target_conn, source_conn, table_name, info, load_type="full") -> Dict[str, Any]:
    target_columns = [c["target_name"] for c in info["columns"]]
    try:
        rows = _fetch_rows_for_table(source_conn, info)
        _replace_rows(target_conn, table_name, target_columns, rows)
        _log_sync(target_conn, table_name, load_type, len(rows), "success", None)
        return {"table": table_name, "load_type": load_type, "rows_loaded": len(rows), "status": "success", "error_message": None}
    except Exception as err:
        target_conn.rollback()
        _log_sync(target_conn, table_name, load_type, 0, "failed", str(err))
        return {"table": table_name, "load_type": load_type, "rows_loaded": 0, "status": "failed", "error_message": str(err)}


def _run_incremental_for_table(target_conn, source_conn, table_name, info) -> Dict[str, Any]:
    columns = info["columns"]
    target_columns = [c["target_name"] for c in columns]
    watermark_source = info.get("watermark_column")
    watermark_source_table = info.get("watermark_source_table")
    watermark_target = info.get("watermark_target_column")
    watermark_kind = info.get("watermark_kind")

    if not watermark_source:
        _log_sync(target_conn, table_name, "incremental", 0, "failed", "No watermark column found")
        return {"table": table_name, "load_type": "incremental", "rows_loaded": 0, "status": "failed", "error_message": "No watermark column found"}

    try:
        watermark_identifier = sql.Identifier(watermark_source_table, watermark_source) if watermark_source_table else sql.Identifier(watermark_source)

        if watermark_kind == "timestamp":
            last_run_ts = _get_last_successful_run(target_conn, table_name, "incremental")
            where_clause = sql.SQL("{} > %s").format(watermark_identifier)
            rows = (
                _fetch_db_rows(source_conn, info, columns, where_clause, [last_run_ts])
                if last_run_ts else _fetch_db_rows(source_conn, info, columns)
            )
        else:
            with target_conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT COALESCE(MAX({}), 0) FROM {}").format(
                        sql.Identifier(watermark_target), sql.Identifier(table_name)
                    )
                )
                max_target_id = cur.fetchone()[0] or 0
            where_clause = sql.SQL("{} > %s").format(watermark_identifier)
            rows = _fetch_db_rows(source_conn, info, columns, where_clause, [max_target_id])

        _append_rows(target_conn, table_name, target_columns, rows)
        _log_sync(target_conn, table_name, "incremental", len(rows), "success", None)
        return {"table": table_name, "load_type": "incremental", "rows_loaded": len(rows), "status": "success", "error_message": None}
    except Exception as err:
        target_conn.rollback()
        _log_sync(target_conn, table_name, "incremental", 0, "failed", str(err))
        return {"table": table_name, "load_type": "incremental", "rows_loaded": 0, "status": "failed", "error_message": str(err)}


def run_job(
    *,
    target_connection: DatabaseConnection,
    selected_tables: List[str],
    schema_generator: bool,
    incremental_load: bool,
    full_load: bool,
    user_id: int,
) -> List[Dict[str, Any]]:
    """Executes the warehouse job in-process against a validated job spec
    (never against arbitrary edited script text) and returns per-table
    results. Spreadsheet-sourced tables and any joined (multi-source) group
    always run as a full replace regardless of mode, since neither has a
    natural single-column incremental watermark. selected_tables here are
    target table names (mapping-group keys), not raw source table names."""
    _validate_modes(schema_generator, incremental_load, full_load)
    if not selected_tables:
        raise WarehouseGenerationError("Select at least one table")

    raw_tables = _load_metamind_tables(user_id)
    groups = get_table_groups(target_connection, user_id)["groups"]
    mappings = _get_target_mappings(target_connection)
    table_metadata = _build_table_metadata(raw_tables, groups, selected_tables, mappings)
    target_config = _target_connection_payload(target_connection)

    target_conn = psycopg2.connect(connect_timeout=10, **target_config)
    source_conn = None
    results: List[Dict[str, Any]] = []

    try:
        _ensure_metadata_table(target_conn)

        if any(info["source_type"] == "DB" for info in table_metadata.values()):
            source_conn = psycopg2.connect(connect_timeout=10, **SOURCE_DB_CONFIG)

        if schema_generator:
            for table_name, info in table_metadata.items():
                results.append(_run_schema_for_table(target_conn, table_name, info))

        if full_load:
            for table_name, info in table_metadata.items():
                results.append(_run_full_for_table(target_conn, source_conn, table_name, info))

        if incremental_load:
            for table_name, info in table_metadata.items():
                if info["source_type"] == "DB" and not info["is_joined"]:
                    results.append(_run_incremental_for_table(target_conn, source_conn, table_name, info))
                else:
                    results.append(_run_full_for_table(target_conn, source_conn, table_name, info, load_type="incremental"))
    finally:
        if source_conn:
            source_conn.close()
        target_conn.close()

    return results


# ============================================================
# Health check
# ============================================================

def check_health(target_connection: DatabaseConnection, table_names: Optional[List[str]] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"target_reachable": False, "sync_log_exists": False, "tables": [], "error": None}

    try:
        target_config = _target_connection_payload(target_connection)
        conn = psycopg2.connect(connect_timeout=8, **target_config)
    except Exception as err:
        result["error"] = str(err)
        return result

    try:
        result["target_reachable"] = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'warehouse_sync_log'
                )
                """
            )
            result["sync_log_exists"] = bool(cur.fetchone()[0])

        tables_to_check = table_names
        if not tables_to_check and result["sync_log_exists"]:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT table_name FROM warehouse_sync_log ORDER BY table_name")
                tables_to_check = [row[0] for row in cur.fetchall()]

        for table_name in tables_to_check or []:
            entry: Dict[str, Any] = {
                "table": table_name, "last_run": None, "last_status": None,
                "last_error": None, "target_row_count": None,
            }
            if result["sync_log_exists"]:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT run_timestamp, status, error_message FROM warehouse_sync_log
                        WHERE table_name = %s ORDER BY run_timestamp DESC LIMIT 1
                        """,
                        (table_name,),
                    )
                    row = cur.fetchone()
                    if row:
                        entry["last_run"] = row[0].isoformat() if row[0] else None
                        entry["last_status"] = row[1]
                        entry["last_error"] = row[2]
            try:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name)))
                    entry["target_row_count"] = cur.fetchone()[0]
            except Exception:
                conn.rollback()
            result["tables"].append(entry)
    finally:
        conn.close()

    return result


def generate_health_script(target_connection: DatabaseConnection) -> Tuple[str, str]:
    """A small standalone script for external cron use: checks target
    reachability and the latest run per table, non-zero exit on failure."""
    target_config = _target_connection_payload(target_connection)
    generated_at = datetime.utcnow().isoformat() + "Z"

    script = (
        '#!/usr/bin/env python3\n'
        '"""\n'
        'Auto-generated Warehouse Health Check by Saarthi.\n'
        'Generated at: ' + generated_at + '\n'
        'Exit code is 1 if the target is unreachable or any table\'s most\n'
        'recent logged run failed.\n'
        '"""\n'
        'import sys\n'
        'import psycopg2\n\n'
        'TARGET_DB_CONFIG = ' + json.dumps(target_config, indent=4) + '\n\n\n'
        'def main():\n'
        '    try:\n'
        '        conn = psycopg2.connect(connect_timeout=8, **TARGET_DB_CONFIG)\n'
        '    except Exception as exc:\n'
        '        print("UNREACHABLE:", exc)\n'
        '        sys.exit(1)\n\n'
        '    exit_code = 0\n'
        '    try:\n'
        '        with conn.cursor() as cur:\n'
        '            cur.execute(\n'
        '                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "\n'
        '                "WHERE table_schema = \'public\' AND table_name = \'warehouse_sync_log\')"\n'
        '            )\n'
        '            exists = cur.fetchone()[0]\n\n'
        '        if not exists:\n'
        '            print("OK: target reachable, no warehouse_sync_log yet (no runs executed)")\n'
        '            return\n\n'
        '        with conn.cursor() as cur:\n'
        '            cur.execute(\n'
        '                "SELECT DISTINCT ON (table_name) table_name, status, run_timestamp, error_message "\n'
        '                "FROM warehouse_sync_log ORDER BY table_name, run_timestamp DESC"\n'
        '            )\n'
        '            rows = cur.fetchall()\n\n'
        '        for table_name, status, run_timestamp, error_message in rows:\n'
        '            if status == "success":\n'
        '                print("OK  ", table_name, "- last run", run_timestamp)\n'
        '            else:\n'
        '                exit_code = 1\n'
        '                print("FAIL", table_name, "- last run", run_timestamp, "-", error_message)\n'
        '    finally:\n'
        '        conn.close()\n\n'
        '    sys.exit(exit_code)\n\n\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"warehouse_health_{timestamp}.py"
    return script, filename


# ============================================================
# Downloadable ETL script (DB-sourced tables only - see generate_script)
# ============================================================

def _render_script(
    *,
    table_metadata: Dict[str, Any],
    selected_tables: List[str],
    schema_generator: bool,
    incremental_load: bool,
    full_load: bool,
    target_config: Dict[str, Any],
    skipped_tables: Optional[List[str]] = None,
) -> str:
    generated_at = datetime.utcnow().isoformat() + "Z"
    skipped_comment = ""
    if skipped_tables:
        skipped_comment = (
            "# NOTE: the following selected tables were left out of this script because\n"
            "# they are spreadsheet-sourced - use \"Run Now\" in the app for those instead:\n"
            "# " + ", ".join(skipped_tables) + "\n"
        )

    script = (
        '#!/usr/bin/env python3\n'
        '"""\n'
        'Auto-generated by Saarthi Warehouse Generator.\n'
        'Generated at: ' + generated_at + '\n'
        '"""\n'
        + skipped_comment +
        '\n'
        'import traceback\n\n'
        'import psycopg2\n'
        'from psycopg2 import sql\n'
        'from psycopg2.extras import execute_values\n\n'
        'SOURCE_DB_CONFIG = ' + json.dumps(SOURCE_DB_CONFIG, indent=4) + '\n'
        'TARGET_DB_CONFIG = ' + json.dumps(target_config, indent=4) + '\n'
        'TABLE_METADATA = ' + json.dumps(table_metadata, indent=4) + '\n'
        'SELECTED_TABLES = ' + json.dumps(selected_tables, indent=4) + '\n\n'
        'RUN_SCHEMA_GENERATOR = ' + str(schema_generator) + '\n'
        'RUN_INCREMENTAL_LOAD = ' + str(incremental_load) + '\n'
        'RUN_FULL_LOAD = ' + str(full_load) + '\n\n\n'
        'def ensure_metadata_table(target_conn):\n'
        '    with target_conn.cursor() as cur:\n'
        '        cur.execute(\n'
        '            """\n'
        '            CREATE TABLE IF NOT EXISTS warehouse_sync_log (\n'
        '                id BIGSERIAL PRIMARY KEY,\n'
        '                table_name TEXT NOT NULL,\n'
        '                load_type TEXT NOT NULL,\n'
        '                rows_loaded INTEGER DEFAULT 0,\n'
        '                run_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),\n'
        '                status TEXT NOT NULL,\n'
        '                error_message TEXT\n'
        '            );\n'
        '            """\n'
        '        )\n'
        '    target_conn.commit()\n\n\n'
        'def log_sync(target_conn, table_name, load_type, rows_loaded, status, error_message=None):\n'
        '    with target_conn.cursor() as cur:\n'
        '        cur.execute(\n'
        '            """\n'
        '            INSERT INTO warehouse_sync_log (\n'
        '                table_name, load_type, rows_loaded, run_timestamp, status, error_message\n'
        '            ) VALUES (%s, %s, %s, NOW(), %s, %s)\n'
        '            """,\n'
        '            (table_name, load_type, rows_loaded, status, error_message),\n'
        '        )\n'
        '    target_conn.commit()\n\n\n'
        'def create_table_if_needed(target_conn, table_name, columns):\n'
        '    column_defs = []\n'
        '    for col in columns:\n'
        '        nullable = "" if col.get("nullable", True) else " NOT NULL"\n'
        '        column_defs.append(\n'
        '            sql.SQL("{} {}{}").format(\n'
        '                sql.Identifier(col["target_name"]),\n'
        '                sql.SQL(col.get("target_type", "TEXT")),\n'
        '                sql.SQL(nullable),\n'
        '            )\n'
        '        )\n\n'
        '    ddl = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(\n'
        '        sql.Identifier(table_name), sql.SQL(", ").join(column_defs)\n'
        '    )\n\n'
        '    with target_conn.cursor() as cur:\n'
        '        cur.execute(ddl)\n'
        '    target_conn.commit()\n\n\n'
        'def select_expr(col):\n'
        '    if col.get("transform_expr"):\n'
        '        return sql.SQL(col["transform_expr"])\n'
        '    if col.get("source_table"):\n'
        '        return sql.Identifier(col["source_table"], col["source_name"])\n'
        '    return sql.Identifier(col["source_name"])\n\n\n'
        'def from_clause(source_tables, join_type, join_keys):\n'
        '    if len(source_tables) <= 1:\n'
        '        return sql.Identifier(source_tables[0])\n\n'
        '    from_sql = sql.Identifier(source_tables[0])\n'
        '    joined = {source_tables[0]}\n'
        '    remaining = list(join_keys)\n\n'
        '    for _ in range(len(source_tables) - 1):\n'
        '        applied = False\n'
        '        for jk in list(remaining):\n'
        '            lt, lc, rt, rc = jk["left_table"], jk["left_column"], jk["right_table"], jk["right_column"]\n'
        '            if lt in joined and rt not in joined:\n'
        '                pass\n'
        '            elif rt in joined and lt not in joined:\n'
        '                lt, lc, rt, rc = rt, rc, lt, lc\n'
        '            else:\n'
        '                continue\n'
        '            from_sql = sql.SQL("{} {} JOIN {} ON {} = {}").format(\n'
        '                from_sql, sql.SQL(join_type), sql.Identifier(rt),\n'
        '                sql.Identifier(lt, lc), sql.Identifier(rt, rc),\n'
        '            )\n'
        '            joined.add(rt)\n'
        '            remaining.remove(jk)\n'
        '            applied = True\n'
        '            break\n'
        '        if not applied:\n'
        '            missing = next((t for t in source_tables if t not in joined), None)\n'
        '            if missing:\n'
        '                from_sql = sql.SQL("{} CROSS JOIN {}").format(from_sql, sql.Identifier(missing))\n'
        '                joined.add(missing)\n\n'
        '    return from_sql\n\n\n'
        'def fetch_source_rows(source_conn, table_info, columns, where_clause=None, params=None):\n'
        '    fields = sql.SQL(", ").join(\n'
        '        sql.SQL("{} AS {}").format(select_expr(col), sql.Identifier(col["target_name"]))\n'
        '        for col in columns\n'
        '    )\n'
        '    from_sql = from_clause(table_info.get("source_tables") or [], table_info.get("join_type", "INNER"), table_info.get("join_keys", []))\n'
        '    query = sql.SQL("SELECT {} FROM {}").format(fields, from_sql)\n\n'
        '    if where_clause:\n'
        '        query = sql.SQL("{} WHERE {}").format(query, where_clause)\n\n'
        '    with source_conn.cursor() as cur:\n'
        '        cur.execute(query, params or [])\n'
        '        return cur.fetchall()\n\n\n'
        'def replace_table_data(target_conn, table_name, target_columns, rows):\n'
        '    with target_conn.cursor() as cur:\n'
        '        cur.execute(sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(table_name)))\n\n'
        '        if rows:\n'
        '            insert_query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(\n'
        '                sql.Identifier(table_name),\n'
        '                sql.SQL(", ").join(sql.Identifier(c) for c in target_columns),\n'
        '            )\n'
        '            execute_values(cur, insert_query, rows)\n\n'
        '    target_conn.commit()\n\n\n'
        'def append_table_data(target_conn, table_name, target_columns, rows):\n'
        '    if not rows:\n'
        '        return\n\n'
        '    with target_conn.cursor() as cur:\n'
        '        insert_query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(\n'
        '            sql.Identifier(table_name),\n'
        '            sql.SQL(", ").join(sql.Identifier(c) for c in target_columns),\n'
        '        )\n'
        '        execute_values(cur, insert_query, rows)\n\n'
        '    target_conn.commit()\n\n\n'
        'def get_last_successful_run(target_conn, table_name, load_type):\n'
        '    with target_conn.cursor() as cur:\n'
        '        cur.execute(\n'
        '            """\n'
        '            SELECT run_timestamp\n'
        '            FROM warehouse_sync_log\n'
        '            WHERE table_name = %s\n'
        '              AND load_type = %s\n'
        '              AND status = \'success\'\n'
        '            ORDER BY run_timestamp DESC\n'
        '            LIMIT 1\n'
        '            """,\n'
        '            (table_name, load_type),\n'
        '        )\n'
        '        row = cur.fetchone()\n'
        '        return row[0] if row else None\n\n\n'
        'def load_schema(target_conn):\n'
        '    for table_name in SELECTED_TABLES:\n'
        '        table_info = TABLE_METADATA.get(table_name, {})\n'
        '        columns = table_info.get("columns", [])\n\n'
        '        try:\n'
        '            create_table_if_needed(target_conn, table_name, columns)\n'
        '            log_sync(target_conn, table_name, "schema", 0, "success", None)\n'
        '        except Exception as err:\n'
        '            target_conn.rollback()\n'
        '            log_sync(target_conn, table_name, "schema", 0, "failed", str(err))\n\n\n'
        'def run_full_load(source_conn, target_conn):\n'
        '    for table_name in SELECTED_TABLES:\n'
        '        table_info = TABLE_METADATA.get(table_name, {})\n'
        '        columns = table_info.get("columns", [])\n'
        '        target_columns = [col["target_name"] for col in columns]\n\n'
        '        try:\n'
        '            if not target_columns:\n'
        '                log_sync(target_conn, table_name, "full", 0, "success", None)\n'
        '                continue\n\n'
        '            rows = fetch_source_rows(source_conn, table_info, columns)\n'
        '            replace_table_data(target_conn, table_name, target_columns, rows)\n'
        '            log_sync(target_conn, table_name, "full", len(rows), "success", None)\n'
        '        except Exception as err:\n'
        '            target_conn.rollback()\n'
        '            log_sync(target_conn, table_name, "full", 0, "failed", str(err))\n\n\n'
        'def run_incremental_load(source_conn, target_conn):\n'
        '    for table_name in SELECTED_TABLES:\n'
        '        table_info = TABLE_METADATA.get(table_name, {})\n'
        '        columns = table_info.get("columns", [])\n'
        '        target_columns = [col["target_name"] for col in columns]\n'
        '        watermark_column = table_info.get("watermark_column")\n'
        '        watermark_source_table = table_info.get("watermark_source_table")\n'
        '        watermark_target_column = table_info.get("watermark_target_column")\n'
        '        watermark_kind = table_info.get("watermark_kind")\n\n'
        '        try:\n'
        '            if not target_columns:\n'
        '                log_sync(target_conn, table_name, "incremental", 0, "success", None)\n'
        '                continue\n\n'
        '            if not watermark_column or table_info.get("is_joined"):\n'
        '                rows = fetch_source_rows(source_conn, table_info, columns)\n'
        '                replace_table_data(target_conn, table_name, target_columns, rows)\n'
        '                log_sync(target_conn, table_name, "incremental", len(rows), "success", None)\n'
        '                continue\n\n'
        '            watermark_identifier = (\n'
        '                sql.Identifier(watermark_source_table, watermark_column)\n'
        '                if watermark_source_table else sql.Identifier(watermark_column)\n'
        '            )\n\n'
        '            rows = []\n'
        '            if watermark_kind == "timestamp":\n'
        '                last_run_ts = get_last_successful_run(target_conn, table_name, "incremental")\n'
        '                where_clause = sql.SQL("{} > %s").format(watermark_identifier)\n'
        '                if last_run_ts:\n'
        '                    rows = fetch_source_rows(source_conn, table_info, columns, where_clause, [last_run_ts])\n'
        '                else:\n'
        '                    rows = fetch_source_rows(source_conn, table_info, columns)\n'
        '            else:\n'
        '                with target_conn.cursor() as cur:\n'
        '                    cur.execute(\n'
        '                        sql.SQL("SELECT COALESCE(MAX({}), 0) FROM {}").format(\n'
        '                            sql.Identifier(watermark_target_column),\n'
        '                            sql.Identifier(table_name),\n'
        '                        )\n'
        '                    )\n'
        '                    max_target_id = cur.fetchone()[0] or 0\n'
        '                where_clause = sql.SQL("{} > %s").format(watermark_identifier)\n'
        '                rows = fetch_source_rows(source_conn, table_info, columns, where_clause, [max_target_id])\n\n'
        '            append_table_data(target_conn, table_name, target_columns, rows)\n'
        '            log_sync(target_conn, table_name, "incremental", len(rows), "success", None)\n'
        '        except Exception as err:\n'
        '            target_conn.rollback()\n'
        '            log_sync(target_conn, table_name, "incremental", 0, "failed", str(err))\n\n\n'
        'def main():\n'
        '    source_conn = None\n'
        '    target_conn = None\n\n'
        '    try:\n'
        '        source_conn = psycopg2.connect(**SOURCE_DB_CONFIG)\n'
        '        target_conn = psycopg2.connect(**TARGET_DB_CONFIG)\n'
        '        ensure_metadata_table(target_conn)\n\n'
        '        if RUN_SCHEMA_GENERATOR:\n'
        '            load_schema(target_conn)\n\n'
        '        if RUN_FULL_LOAD:\n'
        '            run_full_load(source_conn, target_conn)\n\n'
        '        if RUN_INCREMENTAL_LOAD:\n'
        '            run_incremental_load(source_conn, target_conn)\n\n'
        '        print("Warehouse ETL run completed")\n'
        '    except Exception:\n'
        '        print("Warehouse ETL run failed")\n'
        '        print(traceback.format_exc())\n'
        '    finally:\n'
        '        if source_conn:\n'
        '            source_conn.close()\n'
        '        if target_conn:\n'
        '            target_conn.close()\n\n\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )
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
    user_id: int,
) -> Tuple[str, str]:
    """Build and validate a standalone, downloadable warehouse ETL script.
    DB-sourced tables only (including joined groups made entirely of
    DB-sourced tables) - spreadsheet-sourced selections are skipped (noted
    in a header comment) since a portable script can't carry the app's
    Parquet-backed spreadsheet store with it. Use run_job()/"Run Now" in
    the app for spreadsheet-sourced tables. selected_tables are target
    table names (mapping-group keys)."""
    _validate_modes(schema_generator, incremental_load, full_load)
    if not selected_tables:
        raise WarehouseGenerationError("Select at least one table")

    raw_tables = _load_metamind_tables(user_id)
    groups = get_table_groups(target_connection, user_id)["groups"]
    mappings = _get_target_mappings(target_connection)
    table_metadata = _build_table_metadata(raw_tables, groups, selected_tables, mappings)

    db_table_metadata = {k: v for k, v in table_metadata.items() if v["source_type"] == "DB"}
    skipped = sorted(set(table_metadata) - set(db_table_metadata))
    if not db_table_metadata:
        raise WarehouseGenerationError(
            "The downloadable script only supports database-sourced tables; "
            "use \"Run Now\" in the app for spreadsheet-sourced tables."
        )

    target_config = _target_connection_payload(target_connection)

    script = _render_script(
        table_metadata=db_table_metadata,
        selected_tables=list(db_table_metadata.keys()),
        schema_generator=schema_generator,
        incremental_load=incremental_load,
        full_load=full_load,
        target_config=target_config,
        skipped_tables=skipped,
    )

    try:
        _validate_python_script(script)
    except Exception:
        script = _render_script(
            table_metadata=db_table_metadata,
            selected_tables=list(db_table_metadata.keys()),
            schema_generator=schema_generator,
            incremental_load=incremental_load,
            full_load=full_load,
            target_config=target_config,
            skipped_tables=skipped,
        )
        _validate_python_script(script)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"warehouse_etl_{timestamp}.py"
    return script, filename


# ============================================================
# Execute a generated-or-uploaded script (manual-edit escape hatch)
# ============================================================

def execute_script(script_text: str, timeout_seconds: int = 900) -> Dict[str, Any]:
    """Runs a warehouse ETL script (the one just generated, or a copy a
    user downloaded, hand-edited, and re-uploaded) as its own OS process.

    Unlike run_job(), this DOES execute arbitrary script text - that is the
    entire point of the "upload a manually-edited script" escape hatch. To
    keep this bounded: it always runs as a separate subprocess (never
    exec()/eval() inside the Flask process itself), with a hard timeout, so
    it can only do what any script with this app's own OS/network
    permissions could already do, and a hang or crash in the script can't
    take the app down with it. It never runs unvalidated syntax - a source
    file that doesn't compile is rejected before anything is executed. The
    route wiring this up requires the same authentication as the rest of
    the warehouse admin API.
    """
    import subprocess
    import sys

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp_file:
        tmp_file.write(script_text)
        temp_path = tmp_file.name

    try:
        try:
            py_compile.compile(temp_path, doraise=True)
        except py_compile.PyCompileError as exc:
            raise WarehouseGenerationError(f"Script does not compile: {exc}") from exc

        try:
            proc = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "exit_code": None,
                "stdout": exc.stdout or "",
                "stderr": (exc.stderr or "") + f"\nScript timed out after {timeout_seconds}s and was terminated.",
                "timed_out": True,
            }
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
