"""
LLM Provider API Routes
Read-only views over the LLM connections a user is allowed to use (their
own, plus anything granted to them via Resource Mapping - see
app/routes/llm_connection_routes.py for connection CRUD and
app/routes/resource_mapping_routes.py for granting) and their budget status.
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from app.utils.auth_helpers import get_current_user
from app.services.llm_connection_service import get_user_llm_connections, get_budget_status

bp = Blueprint('llm', __name__, url_prefix='/api/llm')


@bp.route('/providers', methods=['GET'])
@jwt_required()
def get_providers():
    """Distinct providers across the LLM connections available to the current user."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'providers': []}), 401

    connections = get_user_llm_connections(current_user.id, current_user.company_code)
    providers = sorted({c.provider for c in connections})
    return jsonify({'providers': providers}), 200


@bp.route('/models', methods=['GET'])
@jwt_required()
def get_models():
    """Every LLM connection (i.e. model) available to the current user, with
    today's budget status for each."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'models': []}), 401

    connections = get_user_llm_connections(current_user.id, current_user.company_code)
    models = []
    for conn in connections:
        data = conn.to_dict()
        data['budget'] = get_budget_status(current_user.id, conn.id)
        models.append(data)
    return jsonify({'models': models}), 200
