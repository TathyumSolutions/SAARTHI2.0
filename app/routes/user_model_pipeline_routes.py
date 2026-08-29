"""
User Model Pipeline Routes
Handles user-specific model selection for pipeline steps
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from app import db
from app.models.user_model_pipeline import UserModelPipeline
from app.services.model_registry_service import (
    get_all_models_sorted,
    get_models_by_type,
    get_recommendations_for_preset,
    PIPELINE_STEPS,
    model_exists
)

bp = Blueprint('user_model_pipeline', __name__, url_prefix='/api')


def _get_user_id() -> int:
    """Extract user_id from JWT token, default to 1"""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity is None:
            return 1
        if isinstance(identity, dict):
            return int(identity.get('id') or identity.get('user_id') or 1)
        return int(identity)
    except Exception:
        return 1


@bp.route('/models/registry', methods=['GET'])
def get_models_registry():
    """
    Get all available models sorted by overall score
    Includes metadata for sorting/display in main model dropdown
    """
    try:
        models = get_all_models_sorted()
        return jsonify({
            'status': 'success',
            'count': len(models),
            'models': models
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/models/recommendations', methods=['GET'])
def get_model_recommendations():
    """
    Get recommended models for each pipeline step
    Query params:
      - type: 'oss', 'api', or 'hybrid' (default: hybrid)
    """
    try:
        preset_type = request.args.get('type', 'hybrid').lower()
        
        if preset_type not in ['oss', 'api', 'hybrid']:
            preset_type = 'hybrid'
        
        recommendations = get_recommendations_for_preset(preset_type)
        
        return jsonify({
            'status': 'success',
            'preset_type': preset_type,
            'recommendations': recommendations,
            'steps': PIPELINE_STEPS
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/user/model-pipeline', methods=['GET'])
def get_user_model_pipeline():
    """
    Get user's saved model pipeline configuration
    """
    try:
        user_id = _get_user_id()
        
        config = UserModelPipeline.query.filter_by(user_id=user_id).first()
        
        if not config:
            # Return default empty config
            return jsonify({
                'status': 'success',
                'config': {
                    'user_id': user_id,
                    'main_model': None,
                    'model_type_preference': 'oss',
                    'step_models': {},
                    'created_at': None,
                    'updated_at': None
                }
            }), 200
        
        return jsonify({
            'status': 'success',
            'config': config.to_dict()
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/user/model-pipeline', methods=['POST'])
def save_user_model_pipeline():
    """
    Save user's model pipeline configuration
    
    Request body:
    {
        "main_model": "llama2:7b",
        "model_type_preference": "oss",  # or "api" or "hybrid"
        "step_models": {
            "Query Sense": "llama2:7b",
            "SQL Generator": "gpt-4o",
            ...
        }
    }
    """
    try:
        user_id = _get_user_id()
        data = request.get_json() or {}
        
        # Validate input
        main_model = data.get('main_model')
        model_type_preference = data.get('model_type_preference', 'oss').lower()
        step_models = data.get('step_models', {})
        
        # Validate model_type_preference
        if model_type_preference not in ['oss', 'api', 'hybrid']:
            model_type_preference = 'oss'
        
        # Validate step_models - ensure all selected models exist
        for step, model in step_models.items():
            if not model_exists(model):
                return jsonify({
                    'status': 'error',
                    'message': f"Unknown model '{model}' for step '{step}'"
                }), 400
        
        # Get or create config
        config = UserModelPipeline.query.filter_by(user_id=user_id).first()
        
        if not config:
            config = UserModelPipeline(user_id=user_id)
        
        config.main_model = main_model
        config.model_type_preference = model_type_preference
        config.step_models = step_models
        
        db.session.add(config)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Model pipeline configuration saved',
            'config': config.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/user/model-pipeline/auto-fill', methods=['POST'])
def auto_fill_pipeline():
    """
    Auto-fill entire pipeline with recommendations based on main model or preset type
    
    Request body:
    {
        "action": "use_main_model" | "use_preset",
        "main_model": "llama2:7b",  # Required if action is use_main_model
        "preset_type": "oss"         # Required if action is use_preset (oss/api/hybrid)
    }
    """
    try:
        user_id = _get_user_id()
        data = request.get_json() or {}
        action = data.get('action', 'use_preset').lower()
        
        step_models = {}
        main_model = None
        model_type_preference = 'oss'
        
        if action == 'use_main_model':
            # Fill all steps with the same main model
            main_model = data.get('main_model')
            if not main_model or not model_exists(main_model):
                return jsonify({
                    'status': 'error',
                    'message': f"Invalid main model: {main_model}"
                }), 400
            
            step_models = {step: main_model for step in PIPELINE_STEPS}
            
            # Determine preference from model type
            from app.services.model_registry_service import MODELS_REGISTRY
            model_info = MODELS_REGISTRY.get(main_model, {})
            model_type_preference = 'api' if model_info.get('type') == 'api' else 'oss'
        
        elif action == 'use_preset':
            # Use preset recommendations
            preset_type = data.get('preset_type', 'hybrid').lower()
            if preset_type not in ['oss', 'api', 'hybrid']:
                preset_type = 'hybrid'
            
            step_models = get_recommendations_for_preset(preset_type)
            model_type_preference = preset_type
        
        # Get or create config
        config = UserModelPipeline.query.filter_by(user_id=user_id).first()
        if not config:
            config = UserModelPipeline(user_id=user_id)
        
        config.main_model = main_model
        config.model_type_preference = model_type_preference
        config.step_models = step_models
        
        db.session.add(config)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Pipeline auto-filled',
            'config': config.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
