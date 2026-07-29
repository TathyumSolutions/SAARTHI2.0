"""
Auto-generates metamind_router_config.json by introspecting:
1. databrige_db (PostgreSQL)   -> DB datasource (SAP-style tables)
2. saarthi_api_db (PostgreSQL) -> API datasource (registered API tools/endpoints)
3. Qdrant                      -> FILES datasource (RAG document collection)

Features:
- Completely dynamic database row position mapping (no hardcoded column lookups)
- Automatically isolates target registry tables dynamically
- Detects schema changes via a content hash (schema fingerprint)
- Skips regeneration if nothing changed since last run
- Skips any datasource that is unreachable/missing instead of failing
- Output matches existing metamind_router_config.json structure
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

DB_CONFIG = {
    "host": os.getenv("DATABRIDGE_DB_HOST", os.getenv("PGHOST", "db")),
    "port": os.getenv("DATABRIDGE_DB_PORT", os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("DATABRIDGE_DB_NAME", os.getenv("PGDATABASE", "saarthi_db")),
    "user": os.getenv("DATABRIDGE_DB_USER", os.getenv("PGUSER", "saarthi")),
    "password": os.getenv("DATABRIDGE_DB_PASSWORD", os.getenv("PGPASSWORD", "password")),
}

API_DB_CONFIG = {
    "host": os.getenv("API_DB_HOST", os.getenv("PGHOST", "db")),
    "port": os.getenv("API_DB_PORT", os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("API_DB_NAME", "saarthi_api_db"),
    "user": os.getenv("API_DB_USER", os.getenv("PGUSER", "saarthi")),
    "password": os.getenv("API_DB_PASSWORD", os.getenv("PGPASSWORD", "password")),
}

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "saarthi_unstructured")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(BASE_DIR, "metamind_router_config.json")
SUMMARY_OUTPUT_PATH = os.path.join(BASE_DIR, "metamind_router_config_summary.json")
HASH_PATH = os.path.join(BASE_DIR, ".router_config_hash")


# ============================================================
# STEP 1: INTROSPECT databrige_db -> DB datasource
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


def introspect_databridge_db():
    """
    Connects to databrige_db and pulls every table + column + simple
    description (derived from PostgreSQL comments if present, else generic),
    plus:
    - row_count: total rows in the table
    - constraints: primary key / foreign keys / unique columns
    - per column: data_type, nullable, unique_values, null_count, sample_values
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
    except Exception as e:
        print(f"⚠️ [DB] Could not connect to databrige_db: {e}")
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
        print(f"⚠️ [DB] Error introspecting databrige_db: {e}")
        return None
    finally:
        conn.close()

    if not tables_out:
        print("⚠️ [DB] No tables found in databrige_db, skipping DB datasource.")
        return None

    print(f"✅ [DB] Found {len(tables_out)} tables in databrige_db")
    return tables_out


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
# STEP 2: INTROSPECT saarthi_api_db -> API datasource (DYNAMIC)
# ============================================================

def introspect_api_db():
    """
    Connects to saarthi_api_db, targets tool registries dynamically,
    and reads data by order position to stay robust against custom schemas.
    """
    try:
        conn = psycopg2.connect(**API_DB_CONFIG, connect_timeout=5)
    except Exception as e:
        print(f"⚠️ [API] Could not connect to saarthi_api_db: {e}")
        return None

    tools_out = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            candidate_tables = [r["table_name"] for r in cur.fetchall()]

            likely_names = [
                "registered_tools", "api_tools", "registered_apis", 
                "api_endpoints", "api_configs", "api_registry", "tools"
            ]
            target_table = next((t for t in likely_names if t in candidate_tables), None)

            if not target_table:
                print("⚠️ [API] No recognizable API registry table found in saarthi_api_db.")
                return None

            cur.execute(f"SELECT * FROM {target_table};")
            rows = cur.fetchall()

            for row in rows:
                col_keys = list(row.keys())
                if not col_keys:
                    continue

                # Position-based assignments mapped from your SQL shape
                name = row[col_keys[1]] if len(col_keys) > 1 else "unnamed_api"
                endpoint = row[col_keys[3]] if len(col_keys) > 3 else ""
                method = row[col_keys[4]] if len(col_keys) > 4 else "GET"

                # Loop to extract the longest non-url string for description field
                description = f"API integration: {name}"
                for col in col_keys:
                    val = row[col]
                    if isinstance(val, str) and len(val) > len(description) and "http" not in str(val):
                        description = val

                tools_out.append({
                    "name": name,
                    "description": description,
                    "method": method,
                    "endpoint": endpoint
                })

    except Exception as e:
        print(f"⚠️ [API] Error introspecting saarthi_api_db: {e}")
        return None
    finally:
        conn.close()

    if not tools_out:
        print("⚠️ [API] No registered API tools found, skipping API datasource.")
        return None

    print(f"✅ [API] Found {len(tools_out)} registered API tools in saarthi_api_db")
    return tools_out


# ============================================================
# STEP 3: INTROSPECT Qdrant -> FILES datasource
# ============================================================

def introspect_qdrant():
    """
    Confirms Qdrant collection metrics to verify active uploads.
    """
    if QdrantClient is None:
        print("⚠️ [FILES] qdrant_client not installed, skipping FILES datasource.")
        return None

    try:
        client = QdrantClient(url=QDRANT_URL, timeout=5)
        collections = client.get_collections().collections
        names = [c.name for c in collections]

        if QDRANT_COLLECTION not in names:
            print(f"⚠️ [FILES] Collection '{QDRANT_COLLECTION}' not found in Qdrant, skipping.")
            return None

        info = client.get_collection(QDRANT_COLLECTION)
        points_count = info.points_count or 0

        if points_count == 0:
            print(f"⚠️ [FILES] Collection '{QDRANT_COLLECTION}' is empty, skipping FILES datasource.")
            return None

        print(f"✅ [FILES] Qdrant collection '{QDRANT_COLLECTION}' has {points_count} points")
        return {"collection": QDRANT_COLLECTION, "points_count": points_count}

    except Exception as e:
        print(f"⚠️ [FILES] Could not connect to Qdrant: {e}")
        return None


# ============================================================
# STEP 4: BUILD THE ROUTING MENU JSON
# ============================================================

def build_routing_menu(db_tables, api_tools, files_info):
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

    routing_rules = {
        "rule_1": "If query mentions table names or columns shown under DB.tables -> always choose DB",
        "rule_2": "If query has count/sum/list/show/how many -> prefer DB",
        "rule_3": "If query asks what/why/explain/describe and matches FILES content -> prefer FILES",
        "rule_4": "If query asks for live/real-time data or matches a registered_tools name/description under API -> always choose API",
        "rule_5": "If query could match more than one active datasource -> return all matching ones, e.g. [\"DB\", \"FILES\"]",
        "rule_6": "When in doubt between DB and FILES -> prefer FILES",
        "output_format": "Return ONLY a JSON array. Example: [\"DB\"] or [\"FILES\"] or [\"API\"] or [\"DB\", \"FILES\"]"
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

def compute_fingerprint(db_tables, api_tools, files_info):
    """
    Generates data fingerprints to capture structural state drift.
    """
    fingerprint_source = {
        "db_tables": db_tables or {},
        "api_tools": api_tools or [],
        "files_points_count": (files_info or {}).get("points_count", 0),
        "files_collection": (files_info or {}).get("collection", "")
    }
    raw = json.dumps(fingerprint_source, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_previous_hash():
    if os.path.exists(HASH_PATH):
        with open(HASH_PATH, "r") as f:
            return f.read().strip()
    return None


def save_hash(new_hash):
    with open(HASH_PATH, "w") as f:
        f.write(new_hash)


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
            "points_count": vs_info.get("points_count", 0)
        }

    if "API" in full_datasources:
        summary_datasources["API"] = {
            "description": full_datasources["API"].get("description", ""),
            "registered_tools": [
                {"name": t.get("name"), "description": t.get("description", "")}
                for t in full_datasources["API"].get("registered_tools", [])
            ]
        }

    return {
        "routing_menu_summary": {
            "datasources": summary_datasources,
            "generated_at": menu.get("routing_menu", {}).get("generated_at")
        }
    }


def generate_router_config_summary(menu: dict):
    """Writes the trimmed summary JSON to disk. Call this only after the
    full menu has already been built/written by generate_router_config."""
    summary = build_routing_menu_summary(menu)
    with open(SUMMARY_OUTPUT_PATH, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"✅ Router config summary regenerated -> {SUMMARY_OUTPUT_PATH}")
    return SUMMARY_OUTPUT_PATH

def generate_router_config(force=False):
    print("\n" + "=" * 60)
    print("🧠 METAMIND ROUTER CONFIG GENERATOR")
    print("=" * 60)

    db_tables = introspect_databridge_db()
    api_tools = introspect_api_db()
    files_info = introspect_qdrant()

    if not db_tables and not api_tools and not files_info:
        print("❌ All three datasources are unreachable or empty. Nothing to generate.")
        return None

    new_hash = compute_fingerprint(db_tables, api_tools, files_info)
    previous_hash = load_previous_hash()

    if not force and new_hash == previous_hash and os.path.exists(OUTPUT_PATH):
        print("✅ No schema changes detected since last run. Skipping regeneration.")
        print(f"   Existing config remains at: {OUTPUT_PATH}")
        return OUTPUT_PATH

    menu = build_routing_menu(db_tables, api_tools, files_info)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(menu, f, indent=2)

    generate_router_config_summary(menu)

    save_hash(new_hash)

    print(f"✅ Router config regenerated -> {OUTPUT_PATH}")
    print(f"   Active datasources: {list(menu['routing_menu']['datasources'].keys())}")
    return OUTPUT_PATH


if __name__ == "__main__":
    import sys
    force_flag = "--force" in sys.argv
    generate_router_config(force=force_flag)