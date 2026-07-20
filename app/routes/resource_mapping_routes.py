import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, jsonify

from app.routes.auth_routes import get_auth_db_connection
from app.models import DatabaseConnection

bp = Blueprint('resource_mapping', __name__, url_prefix='/api/resource-mapping')


def _get_api_db_connection():
    base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
    if "saarthi_db" in base_uri:
        api_db_uri = base_uri.replace("saarthi_db", "saarthi_api_db")
    else:
        api_db_uri = "postgresql://saarthi:password@db:5432/saarthi_api_db"
    return psycopg2.connect(api_db_uri)


def _get_file_metadata():
    """Reads the same metadata JSON file the file-management routes already use."""
    metadata_path = os.environ.get(
        'FILE_METADATA_PATH',
        os.path.join(os.getcwd(), 'uploads', 'file_metadata.json')
    )
    if not os.path.exists(metadata_path):
        return []
    with open(metadata_path, 'r', encoding='utf-8') as f:
        return json.load(f)


@bp.route('/users', methods=['GET'])
def list_users():
    """Returns all users, for the resource-mapping dropdown."""
    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, email, role, company_code FROM users ORDER BY name;")
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({"users": users}), 200
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not list users: {e}")
        return jsonify({"status": "error", "message": "Could not load users."}), 500


@bp.route('/resources', methods=['GET'])
def list_resources():
    """Returns every available resource across all three types, normalized into one list."""
    resources = []

    try:
        db_connections = DatabaseConnection.query.all()
        for conn in db_connections:
            resources.append({"type": "database", "id": str(conn.id), "name": conn.name})
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not list database connections: {e}")

    try:
        for file_metadata in _get_file_metadata():
            document_code = file_metadata.get("document_code")
            if not document_code:
                continue
            resources.append({
                "type": "file",
                "id": document_code,
                "name": file_metadata.get("file_name", document_code)
            })
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not list files: {e}")

    try:
        api_conn = _get_api_db_connection()
        api_cursor = api_conn.cursor(cursor_factory=RealDictCursor)
        api_cursor.execute("SELECT id, integration_name FROM registered_tools WHERE status = 'Active';")
        for tool in api_cursor.fetchall():
            resources.append({"type": "api", "id": str(tool["id"]), "name": tool["integration_name"]})
        api_cursor.close()
        api_conn.close()
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not list API tools: {e}")

    return jsonify({"resources": resources}), 200


@bp.route('/<int:user_id>', methods=['GET'])
def get_user_mappings(user_id):
    """Returns the resources a specific user is currently mapped to."""
    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT id, resource_type, resource_id, resource_name, created_at "
            "FROM user_resource_mapping WHERE user_id = %s ORDER BY created_at DESC;",
            (user_id,)
        )
        mappings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({"mappings": mappings}), 200
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not load mappings for user {user_id}: {e}")
        return jsonify({"status": "error", "message": "Could not load mappings."}), 500


@bp.route('', methods=['POST'])
def create_mapping():
    """Connects a user to a resource."""
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    resource_type = data.get("resource_type")
    resource_id = data.get("resource_id")
    resource_name = data.get("resource_name")

    if not all([user_id, resource_type, resource_id]):
        return jsonify({"status": "error", "message": "user_id, resource_type, and resource_id are required."}), 400

    if resource_type not in ("database", "file", "api"):
        return jsonify({"status": "error", "message": "resource_type must be 'database', 'file', or 'api'."}), 400

    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_resource_mapping (user_id, resource_type, resource_id, resource_name) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, resource_type, resource_id) DO NOTHING;",
            (user_id, resource_type, str(resource_id), resource_name)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Resource mapped to user."}), 201
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not create mapping: {e}")
        return jsonify({"status": "error", "message": "Could not create mapping."}), 500


@bp.route('/<int:mapping_id>', methods=['DELETE'])
def delete_mapping(mapping_id):
    """Removes a single mapping."""
    try:
        conn = get_auth_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_resource_mapping WHERE id = %s;", (mapping_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Mapping removed."}), 200
    except Exception as e:
        print(f"⚠️ [Resource Mapping] Could not delete mapping {mapping_id}: {e}")
        return jsonify({"status": "error", "message": "Could not delete mapping."}), 500