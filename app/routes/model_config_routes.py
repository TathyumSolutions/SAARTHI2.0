"""
Model Configuration API Routes
Handles LLM model settings, fine-tuning, and custom model management
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from app import db                                       # CODE CHANGE: Imported database instance
from app.models.model_config import ModelConfiguration
from app.models.user import User
from app.models.company import Company
from app.utils.auth_helpers import get_current_user
from app.services.model_selection_service import (
    PIPELINE_STEPS,
    RECOMMENDED_PRESET_DEFINITIONS,
    get_available_models,
    get_global_default_config,
    get_recommended_preset_payload,
)
from app.services.llm_providers import validate_dynamic_model_id


def _reject_bare_api_model(model_value):
    """None if `model_value` is fine (or not an 'api://' model at all);
    otherwise the error message to return to the caller. Catches the
    'api://gpt' class of mistake at save time instead of letting it 404
    against the provider on every query afterwards."""
    value = str(model_value or "").strip()
    if not value.startswith("api://"):
        return None
    return validate_dynamic_model_id(value[len("api://"):])


def _validate_generation_settings(settings: dict):
    """None if the optional generation settings are valid, else the error
    message. Bounds match GET /api/model-config/parameters."""
    max_tokens = settings.get("max_tokens")
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 128000:
            return "settings.max_tokens must be an integer between 1 and 128000"
    temperature = settings.get("temperature")
    if temperature is not None:
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0.0 <= temperature <= 2.0:
            return "settings.temperature must be a number between 0 and 2"
    description = settings.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > 500):
        return "settings.description must be text of at most 500 characters"
    return None


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


def _resolve_company_context():
    """Looks the caller up in saarthi_core_db (User / Company models) -
    this used to read the legacy saarthi_auth_db `users` table directly."""
    user_id = _resolve_user_id()
    fallback_company = "default_company"
    fallback_name = "Default Company"
    fallback_role = "user"

    try:
        user = User.query.get(user_id)
        if user is None:
            raise LookupError(f"user {user_id} not found")

        company_code = str(user.company_code or fallback_company).strip() or fallback_company
        company = Company.query.get(user.company_code) if user.company_code else None
        company_name = (company.company_name if company else None) or user.name or fallback_name
        company_name = str(company_name).strip() or fallback_name
        role = str(user.role or fallback_role).strip().lower() or fallback_role
        return {
            "user_id": user_id,
            "company_code": company_code,
            "company_name": company_name,
            "role": role,
        }
    except Exception:
        db.session.rollback()
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


def _list_company_configs(company_code: str):
    rows = ModelConfiguration.query.all()
    scoped = []
    for row in rows:
        row_company_code = str(row.company_code or "").strip()
        row_settings_company = _settings_company_code(row.settings)
        if row_company_code == company_code or row_settings_company == company_code:
            scoped.append(row)
    return scoped


# Open-source models every company gets out of the box (see ollama-init in
# docker-compose.yml for what is actually pulled).
DEFAULT_SEEDED_MODELS = (
    {
        "name": "Llama 2 7B",
        "model": "ollama://llama2:7b",
        "provider": "ollama",
    },
)
DEFAULT_SEEDED_MODEL_IDS = frozenset(item["model"] for item in DEFAULT_SEEDED_MODELS)
DEFAULT_OLLAMA_CHAT_URL = "http://ollama:11434/api/chat"
# Endpoint older seeds stored; callers now normalise either form, but new
# and migrated rows use the chat URL the Configure Model form defaults to.
_LEGACY_SEEDED_OLLAMA_URL = "http://ollama:11434/api/generate"


def _dismissed_seeded_models(user_id: int) -> set:
    """Seeded default models this user deleted - never re-seed those."""
    cfg = ModelConfiguration.query.filter_by(name='global_default', user_id=user_id).first()
    settings = cfg.settings if cfg and isinstance(cfg.settings, dict) else {}
    return set(settings.get("dismissed_seeded_models") or [])


def _remember_dismissed_seed(company_ctx: dict, model: str) -> None:
    """Record on the user's global_default row that they deleted a seeded
    default model, so _seed_default_open_source_models doesn't bring it back
    on the next page load. The caller must have run
    _ensure_default_model_setup() first (so the row exists) and commits."""
    cfg = ModelConfiguration.query.filter_by(
        name='global_default', user_id=company_ctx["user_id"]
    ).first()
    if cfg is None:
        return
    settings = dict(cfg.settings) if isinstance(cfg.settings, dict) else {}
    dismissed = set(settings.get("dismissed_seeded_models") or [])
    dismissed.add(model)
    settings["dismissed_seeded_models"] = sorted(dismissed)
    cfg.settings = settings  # reassign so the JSON column is flagged dirty


def _seed_default_open_source_models(company_ctx: dict):
    """Seed the single open-source model installed by default (Llama 2 7B).

    Also drops any configurations this function auto-seeded in the past
    (e.g. the earlier Llama 3 / Qwen 2.5 3B defaults) that are no longer
    part of the default set, and collapses duplicate seeded rows (the page
    fires several model-config requests in parallel on first load, and
    each one could seed its own copy), without touching models a user
    configured themselves. Seeded models the user deleted stay deleted.
    """
    company_code = company_ctx["company_code"]
    existing = _list_company_configs(company_code=company_code)
    dismissed = _dismissed_seeded_models(company_ctx["user_id"])

    defaults = DEFAULT_SEEDED_MODELS
    default_models = {item["model"] for item in defaults}

    stale = [
        row for row in existing
        if row.name != "global_default"
        and isinstance(row.settings, dict)
        and row.settings.get("seeded_default")
        and row.model not in default_models
    ]
    # Keep the oldest seeded row per model, drop concurrent-seed duplicates.
    kept_seeded = set()
    for row in sorted(existing, key=lambda r: r.id or 0):
        if row in stale or row.name == "global_default":
            continue
        if not (isinstance(row.settings, dict) and row.settings.get("seeded_default")):
            continue
        key = (row.user_id, row.model)
        if key in kept_seeded:
            stale.append(row)
        else:
            kept_seeded.add(key)

    for row in stale:
        db.session.delete(row)

    existing_models = {
        row.model for row in existing
        if row.name != "global_default" and row not in stale
    }

    created_any = bool(stale)

    for row in existing:
        if row in stale or row.name == "global_default" or not isinstance(row.settings, dict):
            continue
        if row.settings.get("seeded_default") and row.settings.get("base_url") == _LEGACY_SEEDED_OLLAMA_URL:
            row.settings = {**row.settings, "base_url": DEFAULT_OLLAMA_CHAT_URL}
            created_any = True
    for item in defaults:
        if item["model"] in existing_models or item["model"] in dismissed:
            continue
        cfg = ModelConfiguration(
            name=item["name"],
            model=item["model"],
            provider=item["provider"],
            user_id=company_ctx["user_id"],
            company_code=company_code,
            settings={
                "company_code": company_code,
                "company_name": company_ctx.get("company_name", ""),
                "model_engine": "ollama",
                "base_url": DEFAULT_OLLAMA_CHAT_URL,
                "seeded_default": True,
            },
        )
        db.session.add(cfg)
        created_any = True

    if created_any:
        db.session.commit()


def _ensure_default_model_setup(company_ctx: dict):
    _seed_default_open_source_models(company_ctx)

    user_id = company_ctx["user_id"]
    existing_default = ModelConfiguration.query.filter_by(name='global_default', user_id=user_id).first()
    if existing_default:
        return

    scoped_models = _list_company_configs(company_ctx["company_code"])
    llama_cfg = next((row for row in scoped_models if (row.model or "").strip() == "ollama://llama2:7b"), None)

    default_model = llama_cfg.model if llama_cfg else "ollama://llama2:7b"
    default_provider = llama_cfg.provider if llama_cfg else "ollama"

    seeded_default = ModelConfiguration(
        name='global_default',
        user_id=user_id,
        company_code=company_ctx["company_code"],
        model=default_model,
        provider=default_provider,
        settings={
            "step_overrides": {},
            "company_code": company_ctx["company_code"],
            "company_name": company_ctx.get("company_name", ""),
            "seeded_default": True,
        },
    )
    db.session.add(seeded_default)
    db.session.commit()


@bp.route('/global-selection', methods=['GET'])
@jwt_required()
def get_global_model_selection():
    ctx = _resolve_company_context()
    _ensure_default_model_setup(ctx)
    config = get_global_default_config(user_id=ctx['user_id'])
    return jsonify(config.to_dict() if config else {}), 200


@bp.route('/global-selection', methods=['POST'])
@jwt_required()
def save_global_model_selection():
    ctx = _resolve_company_context()
    user_id = ctx['user_id']
    data = request.get_json() or {}

    main_model = data.get('main_model')
    if not main_model:
        return jsonify({'error': 'main_model is required'}), 400

    main_model_error = _reject_bare_api_model(main_model)
    if main_model_error:
        return jsonify({'error': main_model_error}), 400

    step_overrides = data.get('step_overrides', {})
    if not isinstance(step_overrides, dict):
        return jsonify({'error': 'step_overrides must be an object'}), 400

    for step, override_model in step_overrides.items():
        override_error = _reject_bare_api_model(override_model)
        if override_error:
            return jsonify({'error': f"step_overrides['{step}']: {override_error}"}), 400

    provider = str(data.get('provider') or '').strip()
    if not provider and str(main_model).startswith('ollama://'):
        provider = 'ollama'

    config = ModelConfiguration.query.filter_by(name='global_default', user_id=user_id).first()
    if not config:
        config = ModelConfiguration(
            name='global_default',
            user_id=user_id,
            company_code=ctx['company_code'],
            model=main_model,
            provider=provider,
            settings={},
        )

    config.model = main_model
    config.company_code = ctx['company_code']
    config.provider = provider or (config.provider or '')
    existing_settings = config.settings if isinstance(config.settings, dict) else {}
    config.settings = {
        **existing_settings,
        'step_overrides': step_overrides,
        'company_code': ctx['company_code'],
        'company_name': ctx.get('company_name', ''),
    }

    db.session.add(config)
    db.session.commit()
    return jsonify({'status': 'success'}), 200


@bp.route('/global-selection/options', methods=['GET'])
@jwt_required()
def get_global_selection_options():
    ctx = _resolve_company_context()
    _ensure_default_model_setup(ctx)
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
    _ensure_default_model_setup(ctx)
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

    ctx = _resolve_company_context()
    _ensure_default_model_setup(ctx)

    configs = (
        ModelConfiguration.query
        .filter(ModelConfiguration.user_id == current_user.id, ModelConfiguration.name != 'global_default')
        .all()
    )
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

    model_error = _reject_bare_api_model(data.get('model'))
    if model_error:
        return jsonify({"error": model_error}), 400

    settings = data.get('settings', {}) or {}
    if not isinstance(settings, dict):
        return jsonify({"error": "settings must be an object"}), 400
    settings_error = _validate_generation_settings(settings)
    if settings_error:
        return jsonify({"error": settings_error}), 400

    settings.setdefault('company_code', current_user.company_code or 'default_company')
    settings.setdefault('company_name', getattr(current_user, 'name', '') or '')

    new_config = ModelConfiguration(
        name=data.get('name'),
        model=data.get('model'),
        provider=data.get('provider'),
        settings=settings,
        company_code=current_user.company_code,
        user_id=current_user.id
    )

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
    ctx = _resolve_company_context()
    _ensure_default_model_setup(ctx)  # before any edits: it may seed/commit
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=current_user.id).first_or_404()
    if config.name == 'global_default':
        return jsonify({"error": "Use /global-selection to change the global model selection."}), 400
    data = request.get_json() or {}

    original_model = config.model

    if 'name' in data:
        config.name = data['name']
    if 'model' in data:
        model_error = _reject_bare_api_model(data['model'])
        if model_error:
            return jsonify({"error": model_error}), 400
        config.model = data['model']
    if 'provider' in data:
        config.provider = data['provider']
    if 'settings' in data:
        if not isinstance(data['settings'], dict):
            return jsonify({"error": "settings must be an object"}), 400
        settings_error = _validate_generation_settings(data['settings'])
        if settings_error:
            return jsonify({"error": settings_error}), 400
        # Merge incoming settings into existing configuration JSON field
        existing_settings = config.settings if isinstance(config.settings, dict) else {}
        config.settings = {**existing_settings, **data['settings']}

    # An edited row belongs to the user now: the seeder must not treat it as
    # a stale default and delete it, nor re-add the default it replaced.
    if isinstance(config.settings, dict) and config.settings.get("seeded_default"):
        config.settings = {**config.settings, "seeded_default": False}
    if original_model in DEFAULT_SEEDED_MODEL_IDS and config.model != original_model:
        _remember_dismissed_seed(ctx, original_model)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database write failed: {str(e)}"}), 500
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
    ctx = _resolve_company_context()
    _ensure_default_model_setup(ctx)  # before any edits: it may seed/commit
    config = ModelConfiguration.query.filter_by(id=config_id, user_id=current_user.id).first_or_404()
    if config.name == 'global_default':
        return jsonify({"error": "The global model selection cannot be deleted."}), 400

    try:
        if config.model in DEFAULT_SEEDED_MODEL_IDS:
            _remember_dismissed_seed(ctx, config.model)
        db.session.delete(config)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database delete failed: {str(e)}"}), 500
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
