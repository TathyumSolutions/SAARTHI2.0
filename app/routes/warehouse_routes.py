"""Warehouse API routes."""

from __future__ import annotations

import io
from typing import Any, Dict, List

import psycopg2
from flask import Blueprint, jsonify, request, send_file

from flask_jwt_extended import jwt_required
from app.models.database_connection import DatabaseConnection
from app.services.warehouse_generator import (
    WarehouseGenerationError,
    check_health,
    execute_script,
    generate_health_script,
    generate_script,
    get_data_model,
    get_discovered_tables,
    get_group_source_columns,
    get_table_groups,
    get_table_mapping,
    run_job,
    save_table_groups,
    save_table_mapping,
    suggest_transformations,
)
from app.utils.auth_helpers import get_current_user

bp = Blueprint("warehouse", __name__)


def _is_warehouse_target(connection: DatabaseConnection) -> bool:
    config = connection.config or {}
    return isinstance(config, dict) and config.get("role") == "warehouse_target"


def _serialize_target_connection(conn: DatabaseConnection) -> Dict[str, Any]:
    return {
        "id": conn.id,
        "name": conn.name,
        "type": conn.type,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "username": conn.username,
        "company_code": conn.company_code,
        "status": conn.status,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }


@bp.route("/api/warehouse/tables", methods=["GET"])
@jwt_required()
def warehouse_tables():
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required", "tables": []}), 401
    try:
        return jsonify({"tables": get_discovered_tables(current_user.id)}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "tables": []}), 500


@bp.route("/api/warehouse/targets", methods=["GET"])
@jwt_required()
def warehouse_targets():
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required", "connections": []}), 401
    try:
        all_connections = (
            DatabaseConnection.query
            .filter_by(created_by_user_id=current_user.id)
            .order_by(DatabaseConnection.updated_at.desc())
            .all()
        )
        targets = [conn for conn in all_connections if _is_warehouse_target(conn)]

        return jsonify({
            "connections": [_serialize_target_connection(conn) for conn in targets],
            "count": len(targets),
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "connections": []}), 500


@bp.route("/api/warehouse/history", methods=["GET"])
@jwt_required()
def warehouse_history():
    try:
        target_connection_id = request.args.get("target_connection_id", type=int)
        limit = request.args.get("limit", default=50, type=int)

        target_connection = None
        if target_connection_id:
            target_connection = DatabaseConnection.query.get(target_connection_id)
        else:
            all_connections = DatabaseConnection.query.order_by(DatabaseConnection.updated_at.desc()).all()
            target_connection = next((conn for conn in all_connections if _is_warehouse_target(conn)), None)

        if not target_connection:
            return jsonify({"target_connection_id": None, "history": []}), 200

        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not a warehouse target"}), 400

        conn = psycopg2.connect(
            host=target_connection.host,
            port=target_connection.port or 5432,
            dbname=target_connection.database,
            user=target_connection.username,
            password=target_connection.password,
            connect_timeout=8,
        )

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'warehouse_sync_log'
                    )
                    """
                )
                exists = cur.fetchone()[0]
                if not exists:
                    return jsonify({"target_connection_id": target_connection.id, "history": []}), 200

                cur.execute(
                    """
                    SELECT table_name, load_type, rows_loaded, run_timestamp, status, error_message
                    FROM warehouse_sync_log
                    ORDER BY run_timestamp DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

            history: List[Dict[str, Any]] = []
            for row in rows:
                history.append(
                    {
                        "table_name": row[0],
                        "load_type": row[1],
                        "rows_loaded": row[2],
                        "run_timestamp": row[3].isoformat() if row[3] else None,
                        "status": row[4],
                        "error_message": row[5],
                    }
                )

            return jsonify({
                "target_connection_id": target_connection.id,
                "history": history,
            }), 200
        finally:
            conn.close()
    except Exception as exc:
        return jsonify({"error": str(exc), "history": []}), 500


@bp.route("/api/warehouse/generate", methods=["POST"])
@jwt_required()
def generate_warehouse_script():
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        data = request.get_json() or {}

        target_connection_id = data.get("target_connection_id")
        selected_tables = data.get("selected_tables", [])

        schema_generator = bool(data.get("schema_generator"))
        incremental_load = bool(data.get("incremental_load"))
        full_load = bool(data.get("full_load"))

        if not target_connection_id:
            return jsonify({"error": "target_connection_id is required"}), 400

        target_connection = DatabaseConnection.query.get(target_connection_id)
        if not target_connection:
            return jsonify({"error": "Target connection not found"}), 404

        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not marked as warehouse_target"}), 400

        script, filename = generate_script(
            target_connection=target_connection,
            selected_tables=selected_tables,
            schema_generator=schema_generator,
            incremental_load=incremental_load,
            full_load=full_load,
            user_id=current_user.id,
        )

        return send_file(
            io.BytesIO(script.encode("utf-8")),
            mimetype="text/x-python",
            as_attachment=True,
            download_name=filename,
        )
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/run", methods=["POST"])
@jwt_required()
def run_warehouse():
    """Executes the job in-process against a validated job spec (schema/
    full/incremental) and returns per-table results - no arbitrary script
    text is ever exec'd server-side."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        data = request.get_json() or {}

        target_connection_id = data.get("target_connection_id")
        selected_tables = data.get("selected_tables", [])
        schema_generator = bool(data.get("schema_generator"))
        incremental_load = bool(data.get("incremental_load"))
        full_load = bool(data.get("full_load"))

        if not target_connection_id:
            return jsonify({"error": "target_connection_id is required"}), 400

        target_connection = DatabaseConnection.query.get(target_connection_id)
        if not target_connection:
            return jsonify({"error": "Target connection not found"}), 404
        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not marked as warehouse_target"}), 400

        results = run_job(
            target_connection=target_connection,
            selected_tables=selected_tables,
            schema_generator=schema_generator,
            incremental_load=incremental_load,
            full_load=full_load,
            user_id=current_user.id,
        )
        return jsonify({"results": results}), 200
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/health", methods=["GET"])
@jwt_required()
def warehouse_health():
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        target_connection_id = request.args.get("target_connection_id", type=int)
        if not target_connection_id:
            return jsonify({"error": "target_connection_id is required"}), 400

        target_connection = DatabaseConnection.query.get(target_connection_id)
        if not target_connection:
            return jsonify({"error": "Target connection not found"}), 404
        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not marked as warehouse_target"}), 400

        return jsonify(check_health(target_connection)), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/health/script", methods=["GET"])
@jwt_required()
def warehouse_health_script():
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        target_connection_id = request.args.get("target_connection_id", type=int)
        if not target_connection_id:
            return jsonify({"error": "target_connection_id is required"}), 400

        target_connection = DatabaseConnection.query.get(target_connection_id)
        if not target_connection:
            return jsonify({"error": "Target connection not found"}), 404
        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not marked as warehouse_target"}), 400

        script, filename = generate_health_script(target_connection)
        return send_file(
            io.BytesIO(script.encode("utf-8")),
            mimetype="text/x-python",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/data-model", methods=["GET"])
@jwt_required()
def warehouse_data_model():
    """Every discovered table plus relationships between them, for the Data
    Model overview shown above Table-Level Mapping. Relationships are
    sourced from the data sources' own introspected metadata wherever
    possible (declared FK constraints, then the router's sample-value-based
    inference) before falling back to a naming-convention guess - see
    get_data_model()'s docstring for the full priority order."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required", "tables": [], "relationships": []}), 401
    try:
        return jsonify(get_data_model(current_user.id)), 200
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc), "tables": [], "relationships": []}), 400
    except Exception as exc:
        return jsonify({"error": str(exc), "tables": [], "relationships": []}), 500


@bp.route("/api/warehouse/table-groups", methods=["GET"])
@jwt_required()
def warehouse_table_groups():
    """Table-level mapping: every discovered source table, plus the
    effective source-tables-per-target-table grouping (a straight 1:1
    default for anything not explicitly grouped/joined otherwise)."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required", "tables": [], "groups": {}}), 401
    try:
        target_connection_id = request.args.get("target_connection_id", type=int)
        target_connection = (
            DatabaseConnection.query.get(target_connection_id) if target_connection_id else None
        )
        return jsonify(get_table_groups(target_connection, current_user.id)), 200
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc), "tables": [], "groups": {}}), 400
    except Exception as exc:
        return jsonify({"error": str(exc), "tables": [], "groups": {}}), 500


@bp.route("/api/warehouse/table-groups", methods=["POST"])
@jwt_required()
def save_warehouse_table_groups():
    """Saves the drag-and-drop table-level mapping: which source table(s)
    feed each target table, and (for a group of more than one source
    table) how they're joined."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        data = request.get_json() or {}
        target_connection_id = data.get("target_connection_id")
        groups = data.get("groups", {})

        if not target_connection_id:
            return jsonify({"error": "target_connection_id is required"}), 400

        target_connection = DatabaseConnection.query.get(target_connection_id)
        if not target_connection:
            return jsonify({"error": "Target connection not found"}), 404
        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not marked as warehouse_target"}), 400

        save_table_groups(target_connection, groups)
        return jsonify({"message": "Table-level mapping saved"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/mapping/<path:target_table_name>", methods=["GET"])
@jwt_required()
def get_warehouse_mapping(target_table_name):
    """Merged view for the column mapping editor: every column across the
    target table's mapped source table(s) plus any saved override for it
    (defaults are a straight 1:1 pass-through)."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        target_connection_id = request.args.get("target_connection_id", type=int)
        target_connection = (
            DatabaseConnection.query.get(target_connection_id) if target_connection_id else None
        )

        groups = get_table_groups(target_connection, current_user.id)["groups"]
        group = groups.get(target_table_name)
        if not group:
            return jsonify({"error": f"No table mapping found for target '{target_table_name}'"}), 404

        tagged_columns, _source_type = get_group_source_columns(current_user.id, group["source_tables"])
        saved = get_table_mapping(target_connection, target_table_name)

        columns = []
        for col in tagged_columns:
            key = f"{col['source_table']}::{col['name']}"
            override = saved.get(key) or saved.get(col["name"], {})
            columns.append({
                "source_table": col["source_table"],
                "source_name": col["name"],
                "data_type": col.get("data_type"),
                "nullable": col.get("nullable", True),
                "target_name": override.get("target_name", col["name"]),
                "target_type": override.get("target_type") or "",
                "include": override.get("include", True),
                "transform_expr": override.get("transform_expr") or "",
            })

        return jsonify({
            "target_table": target_table_name,
            "source_tables": group["source_tables"],
            "join_type": group.get("join_type", "INNER"),
            "join_keys": group.get("join_keys", []),
            "columns": columns,
        }), 200
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/mapping/<path:target_table_name>", methods=["POST"])
@jwt_required()
def save_warehouse_mapping(target_table_name):
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        data = request.get_json() or {}
        target_connection_id = data.get("target_connection_id")
        columns = data.get("columns", [])

        if not target_connection_id:
            return jsonify({"error": "target_connection_id is required"}), 400

        target_connection = DatabaseConnection.query.get(target_connection_id)
        if not target_connection:
            return jsonify({"error": "Target connection not found"}), 404
        if not _is_warehouse_target(target_connection):
            return jsonify({"error": "Selected connection is not marked as warehouse_target"}), 400

        save_table_mapping(target_connection, target_table_name, columns)
        return jsonify({"message": "Mapping saved"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/mapping/<path:target_table_name>/suggest", methods=["POST"])
@jwt_required()
def suggest_warehouse_mapping(target_table_name):
    """AI-assisted (with a rule-based fallback) starting point for the
    mapping editor - always returned for the user to review/edit, never
    saved automatically."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        target_connection_id = request.args.get("target_connection_id", type=int)
        target_connection = (
            DatabaseConnection.query.get(target_connection_id) if target_connection_id else None
        )
        groups = get_table_groups(target_connection, current_user.id)["groups"]
        group = groups.get(target_table_name)
        if not group:
            return jsonify({"error": f"No table mapping found for target '{target_table_name}'"}), 404

        tagged_columns, _source_type = get_group_source_columns(current_user.id, group["source_tables"])
        suggestions = suggest_transformations(target_table_name, tagged_columns)
        return jsonify({"table": target_table_name, "suggestions": suggestions}), 200
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/warehouse/execute-script", methods=["POST"])
@jwt_required()
def execute_warehouse_script():
    """Runs a warehouse ETL script - either the one just generated, or a
    copy the user downloaded, hand-edited outside the app, and uploaded
    back - as its own subprocess (see execute_script()'s docstring for the
    trust boundary this crosses: this route does run arbitrary script
    text, on purpose, as the escape hatch for manual edits generate_script()
    itself can't express)."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    try:
        data = request.get_json() or {}
        script_text = data.get("script")
        if not script_text or not isinstance(script_text, str) or not script_text.strip():
            return jsonify({"error": "script is required"}), 400

        result = execute_script(script_text)
        status_code = 200 if (result["exit_code"] == 0 and not result["timed_out"]) else 422
        return jsonify(result), status_code
    except WarehouseGenerationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
