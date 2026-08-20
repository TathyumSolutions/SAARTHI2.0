from flask import Blueprint, jsonify, request
import yaml
import os
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models.user import User

bp = Blueprint('settings', __name__)

RAG_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'services', 'rag_config.yaml'
)


def _deep_merge(base, updates):
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@bp.route('/api/settings/rag-config', methods=['GET'])
@jwt_required()
def get_rag_config():
    with open(RAG_CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return jsonify(config)


@bp.route('/api/settings/rag-config', methods=['POST'])
@jwt_required()
def update_rag_config():
    updates = request.get_json()
    if not updates:
        return jsonify({"error": "No settings provided"}), 400

    with open(RAG_CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    _deep_merge(config, updates)

    with open(RAG_CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, sort_keys=False)

    return jsonify({"status": "success", "config": config})


@bp.route('/api/settings/query-instructions', methods=['GET'])
@jwt_required()
def get_query_instructions():
    """Standing instructions this user wants applied to every query -
    e.g. "for top N questions, rank by total sales amount unless told
    otherwise". Stored per-user (User.query_instructions), not in the
    shared rag_config.yaml, since it's personal to whoever is asking."""
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"instructions": user.query_instructions or ""})


@bp.route('/api/settings/query-instructions', methods=['POST'])
@jwt_required()
def update_query_instructions():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    instructions = data.get('instructions', '')
    if not isinstance(instructions, str):
        return jsonify({"error": "'instructions' must be a string"}), 400

    user.query_instructions = instructions.strip() or None
    db.session.commit()
    return jsonify({"status": "success", "instructions": user.query_instructions or ""})
