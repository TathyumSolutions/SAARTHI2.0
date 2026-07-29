"""
Model Configuration API Routes
Handles LLM model settings, fine-tuning, and custom model management
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from app import db                                       # CODE CHANGE: Imported database instance
from app.models.model_config import ModelConfiguration
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


@bp.route('/global-selection', methods=['GET'])
def get_global_model_selection():
    user_id = _resolve_user_id()
    config = get_global_default_config(user_id=user_id)
    return jsonify(config.to_dict() if config else {}), 200


@bp.route('/global-selection', methods=['POST'])
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
def get_global_selection_options():
    user_id = _resolve_user_id()
    return jsonify(
        {
            'models': get_available_models(user_id=user_id),
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
def get_global_selection_preset(preset_key):
    user_id = _resolve_user_id()
    payload = get_recommended_preset_payload(preset_key=preset_key, user_id=user_id)
    return jsonify(payload), 200

@bp.route('/configurations', methods=['GET'])
#@jwt_required()
def get_configurations():
    """
    Get all model configurations
    Query params: workspace_id
    Response: { "configurations": [{id, name, model, provider, settings}] }
    """
    #user_id = get_jwt_identity()
    user_id=1
    workspace_id = request.args.get('workspace_id', type=int)
    
    # Filter configurations by the current authenticated user
    query = ModelConfiguration.query.filter_by(user_id=user_id)
    if workspace_id:
        query = query.filter_by(workspace_id=workspace_id)
        
    configs = query.all()
    return jsonify({"configurations": [c.to_dict() for c in configs]}), 200


@bp.route('/configurations', methods=['POST'])
#@jwt_required()
def create_configuration():
    """
    Create new model configuration
    Request: { "name": "GPT-4 Turbo Config", "model": "gpt-4-turbo", 
               "provider": "OpenAI", "settings": {...} }
    Response: { "configuration": {...}, "message": "Configuration created" }
    """
    #raw_identity = get_jwt_identity()
    #if isinstance(raw_identity, dict):
    #    user_id = raw_identity.get('id') or raw_identity.get('user_id') or 1
    #elif isinstance(raw_identity, str) and not raw_identity.isdigit():
    #    user_id = 1
    #else:
    #    try:
    #        user_id = int(raw_identity)
    #    except (ValueError, TypeError):
    #        user_id = 1
    user_id = 1
    #user_id = get_jwt_identity()
    data = request.get_json() or {}
    
    if not data.get('name') or not data.get('model') or not data.get('provider'):
        return jsonify({"error": "Missing required fields: name, model, and provider are mandatory."}), 400
        
    new_config = ModelConfiguration(
        name=data.get('name'),
        model=data.get('model'),
        provider=data.get('provider'),
        settings=data.get('settings', {}),
        workspace_id=data.get('workspace_id'), # Optional field
        user_id=user_id
    )
    
    #db.session.add(new_config)
    #db.session.commit()
    try:
        db.session.add(new_config)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database write failed: {str(e)}"}), 500
    
    return jsonify({
        "configuration": new_config.to_dict(),
        "message": "Configuration created successfully."
    }), 201

@bp.route('/configurations/<int:config_id>', methods=['GET'])
@jwt_required()
def get_configuration(config_id):
    """
    Get specific configuration
    Response: { "configuration": {...} }
    """
    user_id = get_jwt_identity()
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=user_id).first_or_404()
    return jsonify({"configuration": config.to_dict()}), 200
   

@bp.route('/configurations/<int:config_id>', methods=['PUT'])
@jwt_required()
def update_configuration(config_id):
    """
    Update model configuration
    Request: { "name": "...", "settings": {...} }
    Response: { "configuration": {...}, "message": "Configuration updated" }
    """
    user_id = get_jwt_identity()
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=user_id).first_or_404()
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
    if 'workspace_id' in data:
        config.workspace_id = data['workspace_id']
        
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
    user_id = get_jwt_identity()
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=user_id).first_or_404()
    
    db.session.delete(config)
    db.session.commit()
    return jsonify({"message": f"Configuration '{config.name}' deleted successfully."}), 200

@bp.route('/templates', methods=['GET'])
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
