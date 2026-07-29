"""Warehouse API routes."""

from __future__ import annotations

import io
from typing import Any, Dict, List

import psycopg2
from flask import Blueprint, jsonify, request, send_file

from app.models.database_connection import DatabaseConnection
from app.services.warehouse_generator import (
    WarehouseGenerationError,
    generate_script,
    get_discovered_tables,
)

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
        "workspace_id": conn.workspace_id,
        "status": conn.status,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }


@bp.route("/api/warehouse/tables", methods=["GET"])
def warehouse_tables():
    try:
        return jsonify({"tables": get_discovered_tables()}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "tables": []}), 500


@bp.route("/api/warehouse/targets", methods=["GET"])
def warehouse_targets():
    try:
        workspace_id = request.args.get("workspace_id", type=int)

        query = DatabaseConnection.query
        if workspace_id:
            query = query.filter_by(workspace_id=workspace_id)

        all_connections = query.order_by(DatabaseConnection.updated_at.desc()).all()
        targets = [conn for conn in all_connections if _is_warehouse_target(conn)]

        return jsonify({
            "connections": [_serialize_target_connection(conn) for conn in targets],
            "count": len(targets),
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "connections": []}), 500


@bp.route("/api/warehouse/history", methods=["GET"])
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
def generate_warehouse_script():
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
