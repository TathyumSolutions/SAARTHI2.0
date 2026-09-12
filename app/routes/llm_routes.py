"""
LLM Provider API Routes
Read-only views over the Model Configurations ("Configured Models" under
AI & Models) a user is allowed to use - their own, plus anything granted
to them via Resource Mapping (see app/routes/resource_mapping_routes.py,
resource_type='llm') - and their budget status.
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from app.utils.auth_helpers import get_current_user
from app.services.model_config_access_service import get_user_model_configurations, get_budget_status

bp = Blueprint('llm', __name__, url_prefix='/api/llm')


@bp.route('/providers', methods=['GET'])
@jwt_required()
def get_providers():
    """Distinct providers across the Model Configurations available to the current user."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'providers': []}), 401

    configs = get_user_model_configurations(current_user.id, current_user.company_code)
    providers = sorted({c.provider for c in configs if c.provider})
    return jsonify({'providers': providers}), 200


@bp.route('/models', methods=['GET'])
@jwt_required()
def get_models():
    """Every Model Configuration available to the current user, with today's
    budget status for each."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'models': []}), 401

    configs = get_user_model_configurations(current_user.id, current_user.company_code)
    models = []
    for cfg in configs:
        data = cfg.to_dict()
        data['budget'] = get_budget_status(current_user.id, cfg.id)
        models.append(data)
    return jsonify({'models': models}), 200
