"""
Datasource API Routes
Handles data source connections (APIs, files, cloud storage)
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
from app import db
from app.services.llm_service import LLMService
from app.models.file_resource import FileResource
from app.models.database_connection import DatabaseConnection
from app.models.api_connector import ApiConnector
from app.models.resource_mapping import ResourceMapping
from app.models.user import User
from app.utils.auth_helpers import get_current_user
from app.services.audit_service import log_event
from qdrant_client import QdrantClient
from qdrant_client.http import models

bp = Blueprint('datasource', __name__, url_prefix='/api/datasources')


def _format_bytes(size):
    if not size:
        return None
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _database_description(conn):
    if (conn.type or '').lower() == 'excel':
        source_tables = (conn.config or {}).get('source_tables') or []
        table_count = len(source_tables)
        row_count = (conn.config or {}).get('row_count')
        parts = [f"Spreadsheet upload ({conn.type})"]
        if table_count:
            parts.append(f"{table_count} table(s)")
        if row_count:
            parts.append(f"{row_count} rows")
        return ", ".join(parts) + "."
    location = conn.database or conn.host or ''
    return f"{conn.type} database connection" + (f" to \"{location}\"." if location else ".")


def _file_description(resource):
    parts = [resource.file_type.upper() if resource.file_type else "Uploaded file"]
    size = _format_bytes(resource.file_size)
    if size:
        parts.append(size)
    return ", ".join(parts) + "."


def get_visible_datasources(user):
    """
    Every data source (database connection, uploaded file, API connector)
    visible to `user` - their own, plus anything explicitly granted to
    them via Resource Mapping. Same "own + granted" visibility rule used
    by automated_metamind.py, so this list always matches what the AI
    router can actually see for this user.
    """
    granted_by_type = {'database': set(), 'file': set(), 'api': set()}
    for m in ResourceMapping.query.filter_by(user_id=user.id).all():
        if m.resource_type in granted_by_type:
            granted_by_type[m.resource_type].add(m.resource_id)

    databases = DatabaseConnection.query.filter(
        (DatabaseConnection.created_by_user_id == user.id)
        | (DatabaseConnection.id.in_(granted_by_type['database'] or [-1]))
    ).all()
    files = FileResource.query.filter(
        (FileResource.created_by_user_id == user.id)
        | (FileResource.id.in_(granted_by_type['file'] or [-1]))
    ).all()
    apis = ApiConnector.query.filter(
        (ApiConnector.created_by_user_id == user.id)
        | (ApiConnector.id.in_(granted_by_type['api'] or [-1]))
    ).all()

    creator_ids = {r.created_by_user_id for r in (databases + files + apis)}
    creators = {u.id: u for u in User.query.filter(User.id.in_(creator_ids or [-1])).all()}

    def _creator(resource):
        creator = creators.get(resource.created_by_user_id)
        return {
            'id': resource.created_by_user_id,
            'name': creator.name if creator else None,
            'email': creator.email if creator else None,
        }

    def _access(resource):
        return 'owner' if resource.created_by_user_id == user.id else 'shared'

    datasources = []
    for conn in databases:
        datasources.append({
            'id': conn.id,
            'type': 'database',
            'name': conn.name,
            'subtype': conn.type,
            'description': _database_description(conn),
            'status': conn.status,
            'creator': _creator(conn),
            'created_at': conn.created_at.isoformat() if conn.created_at else None,
            'access': _access(conn),
        })
    for f in files:
        datasources.append({
            'id': f.id,
            'type': 'file',
            'name': f.file_name,
            'subtype': (f.file_type or '').upper() or None,
            'description': _file_description(f),
            'status': 'active',
            'creator': _creator(f),
            'created_at': f.created_at.isoformat() if f.created_at else None,
            'access': _access(f),
        })
    for tool in apis:
        datasources.append({
            'id': tool.id,
            'type': 'api',
            'name': tool.integration_name,
            'subtype': tool.method,
            'description': tool.api_description or f"API integration: {tool.integration_name}",
            'status': tool.status,
            'creator': _creator(tool),
            'created_at': tool.created_at.isoformat() if tool.created_at else None,
            'access': _access(tool),
        })

    datasources.sort(key=lambda d: d['created_at'] or '', reverse=True)
    return datasources


@bp.route('/', methods=['GET'])
@jwt_required()
def get_datasources():
    """
    Get all data sources (database connections, files, API connectors)
    visible to the current user - their own, plus anything explicitly
    granted to them via Resource Mapping.
    Query params: type ('database' | 'file' | 'api')
    Response: { "datasources": [{id, type, name, description, status, creator, created_at}] }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'datasources': []}), 401

    try:
        datasources = get_visible_datasources(current_user)

        type_filter = request.args.get('type')
        if type_filter:
            datasources = [d for d in datasources if d['type'] == type_filter]

        return jsonify({'datasources': datasources, 'count': len(datasources)}), 200
    except Exception as e:
        return jsonify({'error': str(e), 'datasources': []}), 500

@bp.route('/', methods=['POST'])
@jwt_required()
def create_datasource():
    """
    Create new data source connection
    Request: { "name": "Salesforce", "type": "api", "config": {...}, "workspace_id": 1 }
    Response: { "datasource": {...}, "message": "Datasource created" }
    """
    # TODO: Implement create datasource logic
    pass

@bp.route('/<int:datasource_id>', methods=['GET'])
@jwt_required()
def get_datasource(datasource_id):
    """
    Get specific datasource details
    Response: { "datasource": {...} }
    """
    # TODO: Implement get datasource details
    pass

@bp.route('/<int:datasource_id>', methods=['PUT'])
@jwt_required()
def update_datasource(datasource_id):
    """
    Update datasource configuration
    Request: { "name": "...", "config": {...} }
    Response: { "datasource": {...}, "message": "Datasource updated" }
    """
    # TODO: Implement update datasource logic
    pass

# @bp.route('/<int:datasource_id>', methods=['DELETE'])
# @jwt_required()
# def delete_datasource(datasource_id):
#     """
#     Delete datasource
#     Response: { "message": "Datasource deleted" }
#     """
#     #  Implement delete datasource logic
#     pass

@bp.route('/<int:datasource_id>/sync', methods=['POST'])
@jwt_required()
def sync_datasource(datasource_id):
    """
    Trigger data sync for datasource
    Response: { "status": "syncing", "job_id": "..." }
    """
    # TODO: Implement sync logic
    pass

@bp.route('/<int:datasource_id>/test', methods=['POST'])
@jwt_required()
def test_datasource(datasource_id):
    """
    Test datasource connection
    Response: { "status": "success/failed", "error": null }
    """
    # TODO: Implement test connection logic
    pass

@bp.route('/types', methods=['GET'])
@jwt_required()
def get_datasource_types():
    """
    Get supported datasource types
    Response: { "types": ["api", "file", "s3", "gcs", "azure_blob", "ftp"] }
    """
    # TODO: Implement get types logic
    pass

@bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_file():
    """
    Upload file as datasource
    Form data: file, name, workspace_id
    Response: { "datasource": {...}, "message": "File uploaded" }
    """
    # TODO: Implement file upload logic
    pass

llm_service = LLMService()


@bp.route('/unstructured/<document_code>', methods=['DELETE'])
@jwt_required()
def delete_datasource(document_code):
    """
    Delete a file: its FileResource row, Qdrant vector chunks, and the
    physical file on disk.
    Response: { "message": "Datasource deleted completely" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    try:
        resource = FileResource.query.filter_by(document_code=document_code).first()
        if not resource:
            return jsonify({"status": "error", "message": f"Document code {document_code} not found."}), 404

        if resource.created_by_user_id != current_user.id and current_user.role != 'admin':
            return jsonify({"status": "error", "message": "Only the uploader or a company admin can delete this file"}), 403

        qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
        qdrant_client.delete(
            collection_name=os.getenv("QDRANT_COLLECTION", "saarthi_unstructured"),
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="metadata.document_code",
                            match=models.MatchValue(value=document_code),
                        )
                    ]
                )
            ),
        )

        if resource.file_path and os.path.exists(resource.file_path):
            os.remove(resource.file_path)

        file_name = resource.file_name
        resource_id = resource.id
        db.session.delete(resource)
        db.session.commit()

        log_event('file_deleted', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='file', resource_id=resource_id, details={'document_code': document_code})

        return jsonify({
            "status": "success",
            "message": f"Successfully deleted {file_name} from system storage and Qdrant vectors."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/unstructured/<document_code>/process', methods=['POST'])
@jwt_required()
def process_unstructured_file(document_code):
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    try:
        resource = FileResource.query.filter_by(document_code=document_code).first()
        if not resource:
            return jsonify({"status": "error", "message": f"Document code {document_code} not found."}), 404

        if resource.created_by_user_id != current_user.id and current_user.role != 'admin':
            return jsonify({"status": "error", "message": "Only the uploader or a company admin can process this file"}), 403

        file_path = resource.file_path

        # Trigger the AI Pipeline
        if file_path and os.path.exists(file_path):
            # PASSING document_code here is essential for the Vector DB
            result = llm_service.process_to_embeddings(file_path, document_code=document_code)

            if "error" in result:
                print(f"❌ Error processing document {document_code}: {result['error']}")
                return jsonify({"status": "error", "message": "Something went wrong while processing this file. Please try again."}), 500

            from app.services.automated_metamind import generate_router_config
            try:
                generate_router_config(user_id=current_user.id, force=True)
            except Exception as e:
                print(f"❌ Error regenerating router config after processing {document_code}: {e}")
                return jsonify({"status": "error", "message": "Something went wrong while activating this file. Please try again."}), 500

            log_event('file_processed', company_code=current_user.company_code, user_id=current_user.id,
                       resource_type='file', resource_id=resource.id, details={'document_code': document_code})

            return jsonify({
                "status": "success",
                "message": "File processed and added to your knowledge base.",
                "processing_message": result.get("message"),
                "data": {
                    "filename": resource.file_name,
                    "chunk_count": result.get("chunk_count")
                }
            }), 200
        else:
            return jsonify({"status": "error", "message": "Physical file could not be located on disk."}), 404

    except Exception as e:
        # Catch-all for system errors
        print(f"❌ Unexpected error processing document {document_code}: {e}")
        return jsonify({"status": "error", "message": "Something went wrong while processing this file. Please try again."}), 500

# Minimal GET route to keep the blueprint valid