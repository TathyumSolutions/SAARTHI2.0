"""
LLM Connection API Routes
Admin-configurable LLM provider connections (OpenAI, Anthropic, Azure
OpenAI, Google, custom/self-hosted) - the LLM analogue of
database_routes.py's DatabaseConnection CRUD. Any authenticated user may
register their own connection; it only becomes visible to other users of
the same company once an admin grants it via Resource Mapping
(resource_type='llm', see resource_mapping_routes.py).
"""
import traceback
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app import db
from app.models.llm_connection import LLMConnection
from app.models.resource_mapping import ResourceMapping
from app.utils.auth_helpers import get_current_user
from app.utils.crypto import encrypt
from app.services.audit_service import log_event
from app.services.llm_connection_service import get_user_llm_connections, get_budget_status

bp = Blueprint('llm_connections', __name__, url_prefix='/api/llm-connections')

PROVIDERS = ('openai', 'anthropic', 'azure_openai', 'google', 'custom')


@bp.route('/', methods=['GET'])
@jwt_required()
def list_llm_connections():
    """Connections the current user created, plus any granted to them via
    Resource Mapping - same visibility rule as /api/databases."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'connections': []}), 401

    try:
        connections = get_user_llm_connections(current_user.id, current_user.company_code)
        result = []
        for conn in connections:
            data = conn.to_dict()
            data['budget'] = get_budget_status(current_user.id, conn.id)
            result.append(data)
        return jsonify({'connections': result, 'count': len(result)}), 200
    except Exception as e:
        print(f"GET llm-connections error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e), 'connections': []}), 200


@bp.route('/', methods=['POST'])
@jwt_required()
def create_llm_connection():
    """
    Request: { "name": "Company OpenAI", "provider": "openai", "model": "gpt-4o",
               "api_key": "...", "api_base_url": "...", "api_version": "...", "config": {} }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json(silent=True) or {}
        for field in ('name', 'provider', 'model'):
            if not data.get(field) or not str(data[field]).strip():
                return jsonify({'error': f'Missing required field: {field}'}), 400

        provider = str(data['provider']).strip().lower()
        if provider not in PROVIDERS:
            return jsonify({'error': f"provider must be one of {PROVIDERS}"}), 400

        connection = LLMConnection(
            name=data['name'].strip(),
            provider=provider,
            model=data['model'].strip(),
            api_key=encrypt(data.get('api_key') or None),
            api_base_url=(data.get('api_base_url') or '').strip() or None,
            api_version=(data.get('api_version') or '').strip() or None,
            config=data.get('config') or {},
            description=(data.get('description') or '').strip() or None,
            company_code=current_user.company_code,
            created_by_user_id=current_user.id,
            status='active',
        )
        db.session.add(connection)
        db.session.commit()

        log_event('llm_connection_created', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='llm', resource_id=connection.id,
                   details={'name': connection.name, 'provider': connection.provider, 'model': connection.model})

        return jsonify({'connection': connection.to_dict(), 'message': 'LLM connection created successfully'}), 201
    except Exception as e:
        db.session.rollback()
        print(f"POST llm-connections error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:connection_id>', methods=['PUT'])
@jwt_required()
def update_llm_connection(connection_id):
    """Only the creator (or an admin of the same company) may edit a connection."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    connection = LLMConnection.query.get(connection_id)
    if not connection:
        return jsonify({'error': 'LLM connection not found'}), 404
    is_owner = connection.created_by_user_id == current_user.id
    is_company_admin = current_user.is_admin_of_company(connection.company_code) if connection.company_code else False
    if not (is_owner or is_company_admin):
        return jsonify({'error': 'Not authorized to edit this connection'}), 403

    try:
        data = request.get_json(silent=True) or {}
        for field in ('name', 'model', 'api_base_url', 'api_version', 'description'):
            if field in data:
                setattr(connection, field, (data[field] or '').strip() or None)
        if 'provider' in data:
            provider = str(data['provider']).strip().lower()
            if provider not in PROVIDERS:
                return jsonify({'error': f"provider must be one of {PROVIDERS}"}), 400
            connection.provider = provider
        if 'api_key' in data and data['api_key']:
            connection.api_key = encrypt(data['api_key'])
        if 'config' in data:
            connection.config = data['config'] or {}
        if 'status' in data:
            connection.status = data['status']

        db.session.commit()
        log_event('llm_connection_updated', company_code=connection.company_code, user_id=current_user.id,
                   resource_type='llm', resource_id=connection.id)
        return jsonify({'connection': connection.to_dict(), 'message': 'LLM connection updated'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"PUT llm-connections error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:connection_id>', methods=['DELETE'])
@jwt_required()
def delete_llm_connection(connection_id):
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    connection = LLMConnection.query.get(connection_id)
    if not connection:
        return jsonify({'error': 'LLM connection not found'}), 404
    is_owner = connection.created_by_user_id == current_user.id
    is_company_admin = current_user.is_admin_of_company(connection.company_code) if connection.company_code else False
    if not (is_owner or is_company_admin):
        return jsonify({'error': 'Not authorized to delete this connection'}), 403

    try:
        ResourceMapping.query.filter_by(resource_type='llm', resource_id=connection_id).delete()
        db.session.delete(connection)
        db.session.commit()
        log_event('llm_connection_deleted', company_code=connection.company_code, user_id=current_user.id,
                   resource_type='llm', resource_id=connection_id)
        return jsonify({'message': 'LLM connection deleted'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"DELETE llm-connections error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:connection_id>/test', methods=['POST'])
@jwt_required()
def test_llm_connection(connection_id):
    """Lightweight reachability check - validates the stored credentials
    look usable without spending a real token budget on a full completion."""
    from datetime import datetime

    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    connection = LLMConnection.query.get(connection_id)
    if not connection:
        return jsonify({'error': 'LLM connection not found'}), 404

    try:
        if connection.provider != 'custom' and not connection.api_key:
            connection.status = 'error'
            connection.error_message = 'No API key configured'
        else:
            connection.status = 'active'
            connection.error_message = None
        connection.last_tested = datetime.utcnow()
        db.session.commit()
        return jsonify({'status': connection.status, 'error_message': connection.error_message}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
