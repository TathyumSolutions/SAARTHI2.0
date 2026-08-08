"""
Builds each user's personal router config (saved to their row in
router_configs, see app/models/router_config.py - not a shared file) by
introspecting:
1. This user's own + resource-mapped PostgreSQL database connections
   (falling back to the legacy DATABRIDGE_TARGET_* env vars if this user
   has none registered) -> DB datasource (SAP-style tables)
2. This user's own + resource-mapped API connectors (saarthi_resources_db,
   via the ApiConnector ORM model) -> API datasource
3. This user's own + resource-mapped spreadsheet-backed tables -> SPREADSHEET datasource
4. This user's own + resource-mapped documents in Qdrant -> FILES datasource
   (RAG document collection, filtered by metadata.document_code)

Features:
- Detects schema changes via a per-user content hash (fingerprint column)
- Skips regeneration if nothing changed since last run
- Skips any datasource that is unreachable/missing instead of failing
"""

import os
import json
import hashlib
import datetime

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

try:
    from qdrant_client import QdrantClient
except ImportError:
    QdrantClient = None


# ============================================================
# CONFIG - Environment-driven DB credentials
# ============================================================

# The SAP demo database is external (see app/services/databridge_services/db.py) -
# no fallback to the app's own Postgres here. If DATABRIDGE_TARGET_HOST
# isn't set, the connect attempt below fails fast and is caught, same as
# any other unreachable/unconfigured datasource.
DB_CONFIG = {
    "host": os.getenv("DATABRIDGE_TARGET_HOST"),
    "port": os.getenv("DATABRIDGE_TARGET_PORT", "5432"),
    "dbname": os.getenv("DATABRIDGE_TARGET_DBNAME"),
    "user": os.getenv("DATABRIDGE_TARGET_USER"),
    "password": os.getenv("DATABRIDGE_TARGET_PASSWORD", ""),
}

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "saarthi_unstructured")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _persist_metamind_summary(resource, summary_text):
    """
    Writes the AI-generated `metamind_summary` field on a resource (a
    DatabaseConnection, FileResource, or ApiConnector row) - kept separate
    from that resource's own user-editable `description`. No-ops if the
    text hasn't changed, so router config regeneration (which can run
    often) doesn't churn out no-op commits every time.
    """
    if not resource or resource.metamind_summary == summary_text:
        return
    from app import db
    resource.metamind_summary = summary_text
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Could not persist metamind_summary for {resource.__class__.__name__} id={getattr(resource, 'id', None)}: {e}")


# These are Saarthi's own internal application tables - never show them
# to the AI as if they were customer/business data.
INTERNAL_SYSTEM_TABLES = {
    "charts", "reports", "audit_logs", "activities",
    "chat_sessions", "chat_messages", "database_connections",
    "datasources", "response_feedback", "model_configurations",
    "queries", "saved_queries", "app_users", "workspaces",
    "users", "user_resource_mapping", "alembic_version",
}


# ============================================================
# STEP 1: INTROSPECT the external SAP database -> DB datasource
# ============================================================

# Tables larger than this are still counted, but skipped for the
# per-column null/unique/sample profiling queries below, since those run
# roughly one full-table scan per column - fine for hundreds/thousands of
# rows, not something you want on a 50-million-row table every time a
# datasource is added. Raise/remove this if your tables are small and you
# always want full stats.
MAX_ROWS_FOR_COLUMN_PROFILING = 100_000


def _safe_fetchone(cur, conn, query, params=None, context="query"):
    try:
        cur.execute(query, params)
        return cur.fetchone()
    except Exception as e:
        conn.rollback()
        print(f"⚠️ [DB] Could not run {context}: {e}")
        return None


def _safe_fetchall(cur, conn, query, params=None, context="query"):
    try:
        cur.execute(query, params)
        return cur.fetchall()
    except Exception as e:
        conn.rollback()
        print(f"⚠️ [DB] Could not run {context}: {e}")
        return []


def introspect_databridge_db(db_config=None):
    """
    Connects to the external SAP database and pulls every table + column + simple
    description (derived from PostgreSQL comments if present, else generic),
    plus:
    - row_count: total rows in the table
    - constraints: primary key / foreign keys / unique columns
    - per column: data_type, nullable, unique_values, null_count, sample_values

    db_config, if given, overrides the module-level DB_CONFIG (which reads
    DATABRIDGE_TARGET_* from this process's own environment) - used by
    run_agentic_process() to introspect the exact connection it just
    seeded, using that connection's stored credentials directly rather
    than relying on env vars that were only ever set for a subprocess.
    """
    try:
        conn = psycopg2.connect(**(db_config or DB_CONFIG), connect_timeout=5)
    except Exception as e:
        print(f"⚠️ [DB] Could not connect to the external SAP database: {e}")
        return None

    tables_out = {}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            table_rows = _safe_fetchall(
                cur,
                conn,
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """,
                context="table list query",
            )

            for row in table_rows:
                table_name = row["table_name"]

                if table_name in INTERNAL_SYSTEM_TABLES:
                    continue

                comment_row = _safe_fetchone(
                    cur,
                    conn,
                    """
                    SELECT obj_description(
                        (quote_ident(%s))::regclass, 'pg_class'
                    ) AS comment;
                    """,
                    (table_name,),
                    context=f"table comment query for {table_name}",
                )
                description = (comment_row["comment"] if comment_row and comment_row["comment"]
                               else f"Table storing {table_name} records.")

                row_count_row = _safe_fetchone(
                    cur,
                    conn,
                    sql.SQL("SELECT COUNT(*) AS cnt FROM {};").format(sql.Identifier(table_name)),
                    context=f"row count for {table_name}",
                )
                row_count = row_count_row["cnt"] if row_count_row else None

                constraints = _get_table_constraints(cur, conn, table_name)

                col_rows = _safe_fetchall(
                    cur,
                    conn,
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (table_name,),
                    context=f"column metadata for {table_name}",
                )

                columns = []
                should_profile = isinstance(row_count, int) and row_count is not None and row_count <= MAX_ROWS_FOR_COLUMN_PROFILING

                if not should_profile and isinstance(row_count, int):
                    print(f"ℹ️ [DB] Skipping column profiling for {table_name} because row_count={row_count} exceeds {MAX_ROWS_FOR_COLUMN_PROFILING}.")

                for col in col_rows:
                    col_name = col["column_name"]
                    col_type = col["data_type"]
                    nullable = col["is_nullable"] == "YES"
                    type_normalized = (col_type or "").lower()

                    if type_normalized in {"json", "jsonb"}:
                        unique_values = None
                        null_count = None
                        sample_values = []
                        profiling_note = "distinct count not supported for json/jsonb columns"
                    elif should_profile:
                        profiling_note = None
                        profile_row = _safe_fetchone(
                            cur,
                            conn,
                            sql.SQL(
                                "SELECT COUNT(DISTINCT {}) AS unique_values, "
                                "SUM(CASE WHEN {} IS NULL THEN 1 ELSE 0 END) AS null_count "
                                "FROM {};"
                            ).format(
                                sql.Identifier(col_name),
                                sql.Identifier(col_name),
                                sql.Identifier(table_name),
                            ),
                            context=f"profiling count for {table_name}.{col_name}",
                        )

                        if profile_row:
                            unique_values = profile_row["unique_values"]
                            null_count = profile_row["null_count"]
                        else:
                            unique_values = None
                            null_count = None

                        sample_rows = _safe_fetchall(
                            cur,
                            conn,
                            sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL LIMIT 5;").format(
                                sql.Identifier(col_name),
                                sql.Identifier(table_name),
                                sql.Identifier(col_name),
                            ),
                            context=f"sample query for {table_name}.{col_name}",
                        )

                        sample_values = []
                        for sample_row in sample_rows:
                            value = sample_row.get(col_name)
                            if value is None:
                                continue
                            if not isinstance(value, (str, int, float, bool)):
                                value = str(value)
                            sample_values.append(value)
                    else:
                        unique_values = None
                        null_count = None
                        sample_values = []
                        profiling_note = None

                    column_entry = {
                        "name": col_name,
                        "data_type": col_type,
                        "nullable": nullable,
                        "unique_values": unique_values,
                        "null_count": null_count,
                        "sample_values": sample_values,
                    }

                    if profiling_note:
                        column_entry["profiling_note"] = profiling_note

                    columns.append(column_entry)

                tables_out[table_name] = {
                    "description": description,
                    "row_count": row_count,
                    "constraints": constraints,
                    "columns": columns
                }

    except Exception as e:
        print(f"⚠️ [DB] Error introspecting the external SAP database: {e}")
        return None
    finally:
        conn.close()

    if not tables_out:
        print("⚠️ [DB] No tables found in the external SAP database, skipping DB datasource.")
        return None

    print(f"✅ [DB] Found {len(tables_out)} tables in the external SAP database")
    return tables_out


def to_sql_agent_schema(db_tables: dict) -> dict:
    """
    Converts introspect_databridge_db()'s output shape into the
    {"tables": {name: {"description", "columns": {col: {...}}, "foreign_keys"}}}
    shape the LangGraph SQL agents (databridge_services/agents/*) expect -
    columns keyed by name rather than a list, and foreign keys flattened to
    "table.column" references. Used to feed those agents this specific
    user's own introspected schema (from their router_configs row) instead
    of a static, global schema file.
    """
    tables = {}
    for table_name, table_data in (db_tables or {}).items():
        columns = {
            col["name"]: {
                "type": col.get("data_type"),
                "nullable": col.get("nullable"),
                "example_values": col.get("sample_values", []),
            }
            for col in table_data.get("columns", [])
        }
        foreign_keys = [
            {"column": fk["column"], "references": f"{fk['references_table']}.{fk['references_column']}"}
            for fk in (table_data.get("constraints") or {}).get("foreign_keys", [])
        ]
        tables[table_name] = {
            "description": table_data.get("description", ""),
            "columns": columns,
            "foreign_keys": foreign_keys,
        }
    return {"tables": tables}


def _get_table_constraints(cur, conn, table_name):
    """
    Returns primary key, foreign key, and unique constraint info for one
    table, using Postgres's own information_schema (same trusted catalog
    source as everything else in this file - no user input involved).
    """
    constraints = {"primary_key": [], "foreign_keys": [], "unique_columns": []}

    try:
        primary_rows = _safe_fetchall(
            cur,
            conn,
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_name = %s AND tc.table_schema = 'public';
            """,
            (table_name,),
            context=f"primary key lookup for {table_name}",
        )
        constraints["primary_key"] = [r["column_name"] for r in primary_rows]

        foreign_rows = _safe_fetchall(
            cur,
            conn,
            """
            SELECT
                kcu.column_name AS column,
                ccu.table_name AS references_table,
                ccu.column_name AS references_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s AND tc.table_schema = 'public';
            """,
            (table_name,),
            context=f"foreign key lookup for {table_name}",
        )
        constraints["foreign_keys"] = [
            {
                "column": r["column"],
                "references_table": r["references_table"],
                "references_column": r["references_column"],
            }
            for r in foreign_rows
        ]

        unique_rows = _safe_fetchall(
            cur,
            conn,
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'UNIQUE'
              AND tc.table_name = %s AND tc.table_schema = 'public';
            """,
            (table_name,),
            context=f"unique constraint lookup for {table_name}",
        )
        constraints["unique_columns"] = [r["column_name"] for r in unique_rows]

    except Exception as e:
        print(f"⚠️ [DB] Could not fetch constraints for {table_name}: {e}")

    return constraints


# ============================================================
# STEP 2: INTROSPECT saarthi_resources_db -> API datasource (DYNAMIC)
# ============================================================

def _visible_resource_ids(user_id, resource_type):
    """
    IDs of resources of the given type visible to this user - their own,
    plus anything explicitly granted via Resource Mapping. Same "own +
    granted" rule used everywhere else in the app; nothing is auto-shared
    just for sharing a company_code.
    """
    from app.models.resource_mapping import ResourceMapping

    granted = {
        m.resource_id for m in ResourceMapping.query.filter_by(
            resource_type=resource_type, user_id=user_id
        ).all()
    }
    return granted


def visible_document_codes(user_id):
    """
    document_code values for uploaded files visible to this user - their
    own uploads, plus anything explicitly granted via Resource Mapping.
    Same "own + granted" rule as introspect_api_db/introspect_spreadsheets;
    used to scope both the FILES status shown in the router config and
    the actual Qdrant retrieval in llm_service.answer_from_docs, so a
    document uploaded by (or not shared with) another user never surfaces
    in this user's answers.
    """
    from app.models.file_resource import FileResource

    granted_ids = _visible_resource_ids(user_id, 'file')
    resources = FileResource.query.filter(
        (FileResource.created_by_user_id == user_id) | (FileResource.id.in_(granted_ids or [-1]))
    ).all()
    return [r.document_code for r in resources]


def _introspect_visible_databases(user_id, sap_db_config=None):
    """
    Introspects the external SAP-style database(s) this user can actually
    see - their own PostgreSQL database connections plus any granted via
    Resource Mapping (same "own + granted" rule as everywhere else),
    merging their tables into one DB datasource.

    If sap_db_config is given explicitly, it's used as-is instead (see
    introspect_databridge_db's docstring) - this is how the Process button
    and run_agentic_process ask for one *specific* connection to be
    (re)introspected right after testing/seeding it, without this broader
    per-user lookup. Every other caller (creating/updating/deleting a
    connection, resource mapping changes, file uploads, etc.) doesn't know
    - and shouldn't need to know - which connection to use, so they rely
    on this lookup instead of passing sap_db_config themselves.

    Falls back to the legacy DATABRIDGE_TARGET_* env vars (via
    introspect_databridge_db(None)) only if this user has no PostgreSQL
    connection registered at all - the standalone/dev CLI use case
    documented on DB_CONFIG above.
    """
    if sap_db_config is not None:
        return introspect_databridge_db(sap_db_config)

    connections = _visible_postgresql_connections(user_id)
    if not connections:
        return introspect_databridge_db(None)

    merged_tables = {}
    for connection in connections:
        tables = introspect_databridge_db(_connection_to_db_config(connection))
        if tables:
            summary_text = "; ".join(
                f"{name} ({t.get('row_count')} rows): {t.get('description', '')}".strip()
                for name, t in tables.items()
            )
            _persist_metamind_summary(connection, summary_text)

            if connection.description:
                for table_data in tables.values():
                    table_data["description"] = f"{connection.description} — {table_data.get('description', '')}".strip(" —")
            merged_tables.update(tables)

    return merged_tables or None


def _visible_postgresql_connections(user_id):
    """PostgreSQL DatabaseConnection rows visible to this user - own + resource-mapped."""
    from app.models.database_connection import DatabaseConnection

    granted_ids = _visible_resource_ids(user_id, 'database')
    return DatabaseConnection.query.filter(
        DatabaseConnection.type == 'PostgreSQL',
        (DatabaseConnection.created_by_user_id == user_id) | (DatabaseConnection.id.in_(granted_ids or [-1]))
    ).all()


def _connection_to_db_config(connection):
    from app.utils.crypto import decrypt
    return {
        "host": connection.host,
        "port": connection.port or 5432,
        "dbname": connection.database,
        "user": connection.username,
        "password": decrypt(connection.password) if connection.password else "",
    }


def resolve_query_execution_config(user_id):
    """
    Connection config to actually RUN generated SQL against for this user -
    not just introspect for schema. Picks this user's first visible
    PostgreSQL connection (own + resource-mapped); returns None if they
    have none registered, in which case the caller should fall back to its
    own default (e.g. the app's own database, for local/dev use).

    Only a single connection is supported here for now - if a user has
    multiple PostgreSQL connections, their combined schema is still shown.
    (introspect_databridge_db can merge tables across connections; query
    execution against a specific one of several cannot yet, since nothing
    tracks which connection a given table actually came from once the two
    schemas are merged.) This matches the existing "still global for now"
    caveat on the external SAP-style database.
    """
    connections = _visible_postgresql_connections(user_id)
    if not connections:
        return None
    return _connection_to_db_config(connections[0])


def introspect_api_db(user_id):
    """
    API connectors visible to this specific user - their own, plus any
    explicitly granted via Resource Mapping.
    """
    from app.models.api_connector import ApiConnector
    from app.utils.redaction import redact_secrets

    granted_ids = _visible_resource_ids(user_id, 'api')
    tools = ApiConnector.query.filter(
        (ApiConnector.created_by_user_id == user_id) | (ApiConnector.id.in_(granted_ids or [-1])),
        ApiConnector.status == 'Active',
    ).all()

    if not tools:
        print(f"⚠️ [API] No API tools visible to user {user_id}, skipping API datasource.")
        return None

    tools_out = []
    for tool in tools:
        description = redact_secrets(tool.api_description) or f"API integration: {tool.integration_name}"
        method = tool.method
        endpoint = redact_secrets(tool.endpoint)
        _persist_metamind_summary(tool, f"{method} {endpoint} — {description}".strip(" —"))
        tools_out.append({
            "name": tool.integration_name,
            "description": description,
            "method": method,
            "endpoint": endpoint,
        })

    print(f"✅ [API] Found {len(tools_out)} API tool(s) visible to user {user_id}")
    return tools_out


# ============================================================
# STEP 3: INTROSPECT Qdrant -> FILES datasource
# ============================================================

def introspect_qdrant(user_id):
    """
    Confirms Qdrant collection metrics to verify active uploads visible to
    this specific user - their own uploads plus anything explicitly
    granted via Resource Mapping (see visible_document_codes). Points
    belonging to other users'/companies' documents are never counted here,
    so the router never even reports them as "available" to this user.
    """
    if QdrantClient is None:
        print("⚠️ [FILES] qdrant_client not installed, skipping FILES datasource.")
        return None

    doc_codes = visible_document_codes(user_id)
    if not doc_codes:
        print(f"⚠️ [FILES] No documents visible to user {user_id}, skipping FILES datasource.")
        return None

    try:
        from qdrant_client.http import models as qmodels

        client = QdrantClient(url=QDRANT_URL, timeout=5)
        collections = client.get_collections().collections
        names = [c.name for c in collections]

        if QDRANT_COLLECTION not in names:
            print(f"⚠️ [FILES] Collection '{QDRANT_COLLECTION}' not found in Qdrant, skipping.")
            return None

        visibility_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="metadata.document_code",
                    match=qmodels.MatchAny(any=doc_codes),
                )
            ]
        )

        # Count chunks by type (text / table / image) so the router knows
        # what kind of content is actually available in FILES - scoped to
        # this user's own/granted documents only, never the whole collection.
        # Also tracked per-document, so each FileResource's metamind_summary
        # reflects only its own chunks, not the whole collection's.
        chunk_type_counts = {"text": 0, "table": 0, "image": 0, "other": 0}
        per_doc_counts = {}
        points_count = 0
        next_offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter=visibility_filter,
                limit=500,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            points_count += len(points)
            for point in points:
                payload = point.payload or {}
                chunk_type = payload.get("chunk_type")

                # Backward-compatible fallback for older points without chunk_type.
                if not chunk_type:
                    source = str(payload.get("source", "")).lower()
                    if "table" in source:
                        chunk_type = "table"
                    elif "image" in source:
                        chunk_type = "image"
                    else:
                        chunk_type = "text"

                chunk_type = str(chunk_type).lower()
                if chunk_type not in chunk_type_counts:
                    chunk_type = "other"
                chunk_type_counts[chunk_type] += 1

                doc_code = (payload.get("metadata") or {}).get("document_code")
                if doc_code:
                    doc_counts = per_doc_counts.setdefault(doc_code, {"text": 0, "table": 0, "image": 0, "other": 0})
                    doc_counts[chunk_type] += 1

            if next_offset is None:
                break

        if points_count == 0:
            print(f"⚠️ [FILES] No indexed chunks visible to user {user_id}, skipping FILES datasource.")
            return None

        from app.models.file_resource import FileResource
        documents = []
        for r in FileResource.query.filter(FileResource.document_code.in_(doc_codes)).all():
            doc_counts = per_doc_counts.get(r.document_code)
            if doc_counts:
                doc_total = sum(doc_counts.values())
                breakdown = ", ".join(f"{v} {k}" for k, v in doc_counts.items() if v)
                _persist_metamind_summary(r, f"{doc_total} chunk(s) indexed ({breakdown}).")
            documents.append({
                "document_code": r.document_code,
                "name": r.file_name,
                "description": r.description or f"Uploaded {r.file_type or 'file'}.",
                "status": r.status or "uploaded",
            })

        print(f"✅ [FILES] Qdrant collection '{QDRANT_COLLECTION}' has {points_count} points visible to user {user_id}: {chunk_type_counts}")
        return {
            "collection": QDRANT_COLLECTION,
            "points_count": points_count,
            "chunk_type_breakdown": chunk_type_counts,
            "documents": documents,
        }

    except Exception as e:
        print(f"⚠️ [FILES] Could not connect to Qdrant: {e}")
        return None


# ============================================================
# STEP 3.5: INTROSPECT spreadsheet-backed tables -> SPREADSHEET datasource
# ============================================================

def introspect_spreadsheets(user_id):
    """
    Reads the Parquet-backed table manifest (spreadsheet_service.py) - not
    a database - for Excel/CSV uploads that deliberately never got written
    into Postgres. Mirrors the DB datasource's shape closely enough that
    the router prompt and the SPREADSHEET query path can both work off it.
    Only tables from a database_connections row (Excel uploads create one
    per file) visible to this user - own or resource-mapped - are included.
    """
    try:
        from app.services.spreadsheet_service import list_all_tables
    except Exception as e:
        print(f"⚠️ [SPREADSHEET] Could not import spreadsheet_service: {e}")
        return None

    try:
        tables = list_all_tables()
    except Exception as e:
        print(f"⚠️ [SPREADSHEET] Could not read spreadsheet manifest: {e}")
        return None

    if not tables:
        return None

    from app.models.database_connection import DatabaseConnection
    granted_ids = _visible_resource_ids(user_id, 'database')
    connections_by_id = {
        conn.id: conn for conn in DatabaseConnection.query.filter(
            (DatabaseConnection.created_by_user_id == user_id) | (DatabaseConnection.id.in_(granted_ids or [-1]))
        ).all()
    }
    visible_connection_ids = set(connections_by_id.keys())

    tables_out = {}
    summary_parts_by_connection = {}
    for table in tables:
        connection_id = table.get("connection_id")
        if connection_id not in visible_connection_ids:
            continue
        auto_description = table.get("description") or f"Spreadsheet table storing {table['table']} records."
        summary_parts_by_connection.setdefault(connection_id, []).append(
            f"{table['table']} ({table.get('row_count')} rows): {auto_description}"
        )

        description = auto_description
        custom_description = connections_by_id[connection_id].description
        if custom_description:
            description = f"{custom_description} — {description}".strip(" —")
        tables_out[table["table"]] = {
            "description": description,
            "row_count": table.get("row_count"),
            "columns": table.get("columns", []),
        }

    for connection_id, parts in summary_parts_by_connection.items():
        _persist_metamind_summary(connections_by_id[connection_id], "; ".join(parts))

    if not tables_out:
        print(f"⚠️ [SPREADSHEET] No spreadsheet-backed tables visible to user {user_id}.")
        return None

    print(f"✅ [SPREADSHEET] Found {len(tables_out)} spreadsheet-backed table(s) visible to user {user_id}.")
    return tables_out


# ============================================================
# STEP 4: BUILD THE ROUTING MENU JSON
# ============================================================

def build_routing_menu(db_tables, api_tools, files_info, spreadsheet_tables=None):
    """
    Assembles the contextual schema payload mapping active nodes.
    """
    datasources = {}

    if db_tables:
        datasources["DB"] = {
            "description": "Use when query needs structured data, row counts, calculations, filters, aggregations, or specific column values from business database tables.",
            "trigger_keywords": ["how many", "list", "show", "count", "total", "sum", "average", "top", "find", "fetch", "records", "entries"],
            "example_queries": [
                "Show top 5 materials",
                "How many customers are in Germany?",
                "Total invoice amount for last month",
                "List all sales orders"
            ],
            "tables": db_tables
        }

    if files_info:
        datasources["FILES"] = {
            "description": "Use when query asks for explanations, policies, summaries, company information, documentation content, or any textual knowledge stored in uploaded documents.",
            "trigger_keywords": ["what is", "explain", "describe", "tell me about", "who is", "where is", "what does", "summarize", "policy", "process", "company"],
            "example_queries": [
                "What is the company name?",
                "Explain the procurement process",
                "What does the company do?",
                "Where is the headquarters?",
                "Summarize the uploaded document"
            ],
            "vector_store_info": files_info
        }

    if api_tools:
        datasources["API"] = {
            "description": "Use when query needs real-time data, live statuses, or explicitly matches any available integration capabilities listed in registered_tools below.",
            "trigger_keywords": ["real-time", "live", "current status", "api", "endpoint", "connection", "integration", "latest", "lookup", "fetch external"],
            "example_queries": [
                "What is the current stock price?",
                "Check the API connection status",
                "Get live data from the endpoint",
                "What does the API return for this request?"
            ],
            "registered_tools": api_tools
        }

    if spreadsheet_tables:
        datasources["SPREADSHEET"] = {
            "description": "Use when query needs data from an uploaded Excel or CSV file (not the main business database). These tables live outside Postgres as separate spreadsheet-backed tables and are queried with a Python/pandas-based path, never SQL.",
            "trigger_keywords": ["excel", "csv", "spreadsheet", "sheet", "workbook", "uploaded file"],
            "example_queries": [
                "Show player performance from the uploaded sheet",
                "Total sales in the Q1 spreadsheet",
                "How many rows are in the excel file?"
            ],
            "tables": spreadsheet_tables
        }

    routing_rules = {
        "rule_1": "If query mentions table names or columns shown under DB.tables -> always choose DB",
        "rule_2": "If query has count/sum/list/show/how many -> prefer DB",
        "rule_3": "If query asks what/why/explain/describe and matches FILES content -> prefer FILES",
        "rule_4": "If query asks for live/real-time data or matches a registered_tools name/description under API -> always choose API",
        "rule_5": "If query could match more than one active datasource -> return all matching ones, e.g. [\"DB\", \"FILES\"]",
        "rule_6": "When in doubt between DB and FILES -> prefer FILES",
        "rule_7": "If query mentions table names or columns shown under SPREADSHEET.tables, or explicitly refers to an uploaded excel/csv/spreadsheet file -> always choose SPREADSHEET",
        "output_format": "Return ONLY a JSON array. Example: [\"DB\"] or [\"FILES\"] or [\"API\"] or [\"SPREADSHEET\"] or [\"DB\", \"FILES\"]"
    }

    menu = {
        "routing_menu": {
            "instructions": "Analyze the user query carefully. Select ONE or MORE datasources from the list below. Return ONLY a valid JSON array like: [\"DB\"] or [\"FILES\"] or [\"API\"] or [\"DB\", \"FILES\"]",
            "datasources": datasources,
            "routing_rules": routing_rules,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
    }
    return menu


# ============================================================
# STEP 5: CHANGE DETECTION (hash-based)
# ============================================================

def compute_fingerprint(db_tables, api_tools, files_info, spreadsheet_tables=None):
    """
    Generates data fingerprints to capture structural state drift.
    """
    fingerprint_source = {
        "db_tables": db_tables or {},
        "api_tools": api_tools or [],
        "files_points_count": (files_info or {}).get("points_count", 0),
        "files_collection": (files_info or {}).get("collection", ""),
        "files_documents": (files_info or {}).get("documents", []),
        "spreadsheet_tables": spreadsheet_tables or {}
    }
    raw = json.dumps(fingerprint_source, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_or_create_router_config_row(user_id):
    from app import db
    from app.models.router_config import RouterConfig

    row = RouterConfig.query.filter_by(user_id=user_id).first()
    if not row:
        row = RouterConfig(user_id=user_id)
        db.session.add(row)
    return row


# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def build_routing_menu_summary(menu: dict) -> dict:
    """
    Strips the full routing menu down to names + descriptions only -
    no data_type, nullable, unique_values, null_count, sample_values,
    row_count, or constraints. Used as a smaller, faster-to-scan config
    for lightweight routing/UI purposes. Structure mirrors the full menu
    so downstream consumers can treat it the same way.
    """
    full_datasources = menu.get("routing_menu", {}).get("datasources", {})
    summary_datasources = {}

    if "DB" in full_datasources:
        summary_tables = {}
        for table_name, table_data in full_datasources["DB"].get("tables", {}).items():
            summary_tables[table_name] = {
                "description": table_data.get("description", ""),
                "columns": [col.get("name") for col in table_data.get("columns", [])]
            }
        summary_datasources["DB"] = {
            "description": full_datasources["DB"].get("description", ""),
            "tables": summary_tables
        }

    if "FILES" in full_datasources:
        vs_info = full_datasources["FILES"].get("vector_store_info", {})
        summary_datasources["FILES"] = {
            "description": full_datasources["FILES"].get("description", ""),
            "collection": vs_info.get("collection", ""),
            "points_count": vs_info.get("points_count", 0),
            "documents": [
                {"document_code": d.get("document_code"), "name": d.get("name"), "description": d.get("description")}
                for d in vs_info.get("documents", [])
            ]
        }

    if "API" in full_datasources:
        summary_datasources["API"] = {
            "description": full_datasources["API"].get("description", ""),
            "registered_tools": [
                {"name": t.get("name"), "description": t.get("description", "")}
                for t in full_datasources["API"].get("registered_tools", [])
            ]
        }

    if "SPREADSHEET" in full_datasources:
        summary_tables = {}
        for table_name, table_data in full_datasources["SPREADSHEET"].get("tables", {}).items():
            summary_tables[table_name] = {
                "description": table_data.get("description", ""),
                "columns": [col.get("name") for col in table_data.get("columns", [])]
            }
        summary_datasources["SPREADSHEET"] = {
            "description": full_datasources["SPREADSHEET"].get("description", ""),
            "tables": summary_tables
        }

    return {
        "routing_menu_summary": {
            "datasources": summary_datasources,
            "generated_at": menu.get("routing_menu", {}).get("generated_at")
        }
    }


def generate_router_config(user_id, force=False, sap_db_config=None):
    """
    Builds and saves this specific user's router config - which
    datasources/tables/API tools/spreadsheets the smart router considers
    when answering their questions. Saved to that user's row in
    router_configs (saarthi_workspace_db), not a shared global file, so
    two users never see each other's private resources through routing.

    The external SAP-style database is resolved from this user's own
    PostgreSQL connections (own + resource-mapped) unless sap_db_config is
    given explicitly - see _introspect_visible_databases()'s docstring.
    Qdrant documents (introspect_qdrant) are scoped the same way, via
    visible_document_codes() - so every datasource here now reflects only
    what this user created or was granted, not the whole company/system.
    """
    from app import db
    from app.models.user import User

    user = User.query.get(user_id)
    if not user:
        print(f"❌ Unknown user_id={user_id}, cannot generate router config.")
        return None

    print("\n" + "=" * 60)
    print(f"🧠 METAMIND ROUTER CONFIG GENERATOR (user_id={user_id})")
    print("=" * 60)

    db_tables = _introspect_visible_databases(user_id, sap_db_config)
    api_tools = introspect_api_db(user_id)
    files_info = introspect_qdrant(user_id)
    spreadsheet_tables = introspect_spreadsheets(user_id)

    if not db_tables and not api_tools and not files_info and not spreadsheet_tables:
        print(f"❌ No datasources visible to user {user_id}. Nothing to generate.")
        return None

    row = _get_or_create_router_config_row(user_id)

    new_hash = compute_fingerprint(db_tables, api_tools, files_info, spreadsheet_tables)
    if not force and new_hash == row.fingerprint and row.config:
        print("✅ No schema changes detected since last run. Skipping regeneration.")
        return row

    menu = build_routing_menu(db_tables, api_tools, files_info, spreadsheet_tables)
    summary = build_routing_menu_summary(menu)

    row.company_code = user.company_code
    row.config = menu
    row.summary = summary
    row.fingerprint = new_hash
    db.session.commit()

    print(f"✅ Router config regenerated for user {user_id}")
    print(f"   Active datasources: {list(menu['routing_menu']['datasources'].keys())}")
    return row


if __name__ == "__main__":
    # Manual/dev use only - the live app always calls generate_router_config()
    # as a function, in-process, with a real Flask app context already active.
    import argparse
    parser = argparse.ArgumentParser(description="Regenerate a user's router config.")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        generate_router_config(user_id=args.user_id, force=args.force)