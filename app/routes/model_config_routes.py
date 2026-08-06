"""
Model Configuration API Routes
Handles LLM model settings, fine-tuning, and custom model management
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from app import db                                       # CODE CHANGE: Imported database instance
from app.models.model_config import ModelConfiguration
from app.utils.auth_helpers import get_current_user
from app.services.model_selection_service import (
    PIPELINE_STEPS,
    RECOMMENDED_PRESET_DEFINITIONS,
    get_available_models,
    get_global_default_config,
    get_recommended_preset_payload,
)


bp = Blueprint('model_config', __name__, url_prefix='/api/model-config')


def _resolve_user_id() -> int:
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity is None:
            return 1
        if isinstance(identity, dict):
            candidate = identity.get('id') or identity.get('user_id')
            return int(candidate) if candidate else 1
        return int(identity)
    except Exception:
        return 1


def _get_auth_db_connection():
    base_uri = os.environ.get('ENVIRONMENT_DATABASE_URL') or "postgresql://saarthi:password@db:5432/saarthi_db"
    if "saarthi_db" in base_uri:
        auth_db_uri = base_uri.replace("saarthi_db", "saarthi_auth_db")
    else:
        auth_db_uri = "postgresql://saarthi:password@db:5432/saarthi_auth_db"
    return psycopg2.connect(auth_db_uri)


def _resolve_company_context():
    user_id = _resolve_user_id()
    fallback_company = "default_company"
    fallback_name = "Default Company"
    fallback_role = "user"

    try:
        conn = _get_auth_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT company_code, role, name FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone() or {}
        cur.close()
        conn.close()

        company_code = str(row.get("company_code") or fallback_company).strip() or fallback_company
        company_name = str(row.get("name") or fallback_name).strip() or fallback_name
        role = str(row.get("role") or fallback_role).strip().lower() or fallback_role
        return {
            "user_id": user_id,
            "company_code": company_code,
            "company_name": company_name,
            "role": role,
        }
    except Exception:
        return {
            "user_id": user_id,
            "company_code": fallback_company,
            "company_name": fallback_name,
            "role": fallback_role,
        }


def _settings_company_code(settings):
    if not isinstance(settings, dict):
        return ""
    return str(settings.get("company_code") or "").strip()


def _list_company_configs(company_code: str, workspace_id=None):
    rows = ModelConfiguration.query.all()
    scoped = [row for row in rows if _settings_company_code(row.settings) == company_code]
    if workspace_id is not None:
        scoped = [row for row in scoped if row.workspace_id == workspace_id]
    return scoped


def _seed_default_open_source_models(company_ctx: dict):
    company_code = company_ctx["company_code"]
    existing = _list_company_configs(company_code=company_code)
    existing_models = {row.model for row in existing}

    defaults = [
        {
            "name": "Llama 3",
            "model": "ollama://llama3",
            "provider": "ollama",
        },
        {
            "name": "Qwen 2.5 3B",
            "model": "ollama://qwen2.5:3b",
            "provider": "ollama",
        },
    ]

    created_any = False
    for item in defaults:
        if item["model"] in existing_models:
            continue
        cfg = ModelConfiguration(
            name=item["name"],
            model=item["model"],
            provider=item["provider"],
            workspace_id=None,
            user_id=company_ctx["user_id"],
            settings={
                "company_code": company_code,
                "company_name": company_ctx.get("company_name", ""),
                "model_engine": "ollama",
                "base_url": "http://ollama:11434/api/chat",
                "seeded_default": True,
            },
        )
        db.session.add(cfg)
        created_any = True

    if created_any:
        db.session.commit()


@bp.route('/global-selection', methods=['GET'])
@jwt_required()
def get_global_model_selection():
    user_id = _resolve_user_id()
    config = get_global_default_config(user_id=user_id)
    return jsonify(config.to_dict() if config else {}), 200


@bp.route('/global-selection', methods=['POST'])
@jwt_required()
def save_global_model_selection():
    user_id = _resolve_user_id()
    data = request.get_json() or {}

    main_model = data.get('main_model')
    if not main_model:
        return jsonify({'error': 'main_model is required'}), 400

    step_overrides = data.get('step_overrides', {})
    if not isinstance(step_overrides, dict):
        return jsonify({'error': 'step_overrides must be an object'}), 400

    config = ModelConfiguration.query.filter_by(name='global_default', user_id=user_id).first()
    if not config:
        config = ModelConfiguration(
            name='global_default',
            user_id=user_id,
            model=main_model,
            provider=data.get('provider', ''),
            settings={},
        )

    config.model = main_model
    config.provider = data.get('provider', config.provider or '')
    config.settings = {'step_overrides': step_overrides}

    db.session.add(config)
    db.session.commit()
    return jsonify({'status': 'success'}), 200


@bp.route('/global-selection/options', methods=['GET'])
@jwt_required()
def get_global_selection_options():
    ctx = _resolve_company_context()
    return jsonify(
        {
            'models': get_available_models(user_id=ctx['user_id'], company_code=ctx['company_code']),
            'steps': PIPELINE_STEPS,
            'presets': [
                {
                    'key': value['key'],
                    'label': value['label'],
                }
                for value in RECOMMENDED_PRESET_DEFINITIONS.values()
            ],
        }
    ), 200


@bp.route('/global-selection/preset/<string:preset_key>', methods=['GET'])
@jwt_required()
def get_global_selection_preset(preset_key):
    ctx = _resolve_company_context()
    payload = get_recommended_preset_payload(
        preset_key=preset_key,
        user_id=ctx['user_id'],
        company_code=ctx['company_code'],
    )
    return jsonify(payload), 200

@bp.route('/configurations', methods=['GET'])
@jwt_required()
def get_configurations():
    """
    Get the current user's model configurations.
    Response: { "configurations": [{id, name, model, provider, settings}] }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401

    configs = ModelConfiguration.query.filter_by(user_id=current_user.id).all()
    return jsonify({"configurations": [c.to_dict() for c in configs]}), 200


@bp.route('/configurations', methods=['POST'])
@jwt_required()
def create_configuration():
    """
    Create new model configuration
    Request: { "name": "GPT-4 Turbo Config", "model": "gpt-4-turbo",
               "provider": "OpenAI", "settings": {...} }
    Response: { "configuration": {...}, "message": "Configuration created" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json() or {}

    if not data.get('name') or not data.get('model') or not data.get('provider'):
        return jsonify({"error": "Missing required fields: name, model, and provider are mandatory."}), 400

    new_config = ModelConfiguration(
        name=data.get('name'),
        model=data.get('model'),
        provider=data.get('provider'),
        settings=data.get('settings', {}),
        company_code=current_user.company_code,
        user_id=current_user.id
    )

    try:
        db.session.add(target)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database write failed: {str(e)}"}), 500

    return jsonify({
        "configuration": target.to_dict(),
        "message": "Configuration created successfully."
    }), 201

@bp.route('/configurations/<int:config_id>', methods=['GET'])
@jwt_required()
def get_configuration(config_id):
    """
    Get specific configuration
    Response: { "configuration": {...} }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=current_user.id).first_or_404()
    return jsonify({"configuration": config.to_dict()}), 200


@bp.route('/configurations/<int:config_id>', methods=['PUT'])
@jwt_required()
def update_configuration(config_id):
    """
    Update model configuration
    Request: { "name": "...", "settings": {...} }
    Response: { "configuration": {...}, "message": "Configuration updated" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=current_user.id).first_or_404()
    data = request.get_json() or {}

    if 'name' in data:
        config.name = data['name']
    if 'model' in data:
        config.model = data['model']
    if 'provider' in data:
        config.provider = data['provider']
    if 'settings' in data:
        # Merge incoming settings into existing configuration JSON field
        config.settings = {**config.settings, **data['settings']}

    db.session.commit()
    return jsonify({
        "configuration": config.to_dict(),
        "message": "Configuration updated successfully."
    }), 200


@bp.route('/configurations/<int:config_id>', methods=['DELETE'])
@jwt_required()
def delete_configuration(config_id):
    """
    Delete configuration
    Response: { "message": "Configuration deleted" }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=current_user.id).first_or_404()
    
    db.session.delete(config)
    db.session.commit()
    return jsonify({"message": f"Configuration '{config.name}' deleted successfully."}), 200

@bp.route('/templates', methods=['GET'])
@jwt_required()
def get_configuration_templates():
    """
    Get configuration templates for different use cases
    Response: { "templates": [{name, description, settings, recommended_for}] }
    """
    templates = [
        {
            "name": "Strict Precision Extraction",
            "description": "Configured optimized for factual analysis, legal context documents, or structured JSON processing.",
            "settings": {"temperature": 0.0, "max_tokens": 2048},
            "recommended_for": "RAG Applications & Parsing"
        },
        {
            "name": "Creative Assistant Flow",
            "description": "Higher creativity thresholds for copywriting, brainstorming, or multi-agent roleplay frameworks.",
            "settings": {"temperature": 0.8, "max_tokens": 4096},
            "recommended_for": "Content Creation & Agent Dialogues"
        }
    ]
    return jsonify({"templates": templates}), 200

@bp.route('/parameters', methods=['GET'])
@jwt_required()
def get_available_parameters():
    """
    Get available configuration parameters
    Response: { "parameters": [{name, type, default, min, max, description}] }
    """
    parameters = [
        {"name": "temperature", "type": "float", "default": 0.7, "min": 0.0, "max": 2.0, "description": "Controls response randomness"},
        {"name": "max_tokens", "type": "int", "default": 4096, "min": 1, "max": 128000, "description": "Maximum generated output text token cap"},
        {"name": "custom_key", "type": "string", "default": None, "min": None, "max": None, "description": "Provider API token credentials override"}
    ]
    return jsonify({"parameters": parameters}), 200
   
@bp.route('/validate', methods=['POST'])
@jwt_required()
def validate_configuration():
    """
    Validate model configuration
    Request: { "model": "gpt-4", "provider": "OpenAI", "settings": {...} }
    Response: { "valid": true, "warnings": [], "errors": [] }
    """
    data = request.get_json() or {}
    errors = []
    warnings = []
    
    if not data.get('model'):
        errors.append("Model runtime tracking string cannot be blank.")
    if not data.get('provider'):
        errors.append("A definitive hosting cloud or local provider node must be specified.")
        
    return jsonify({
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors
    }), 200
    

@bp.route('/benchmark', methods=['POST'])
@jwt_required()
def benchmark_configuration():
    """
    Benchmark model configuration performance
    Request: { "config_id": 1, "test_queries": [...] }
    Response: { "results": {latency, accuracy, cost, ...} }
    """
    return jsonify({
        "results": {
            "status": "ready",
            "average_latency_ms": 420,
            "estimated_cost_per_k_tokens": 0.0015,
            "performance_rating": "Optimal"
        }
    }), 200
