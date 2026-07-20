from flask import Blueprint, jsonify, request, render_template
import yaml
import os

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


@bp.route('/settings')
def settings_page():
    return render_template('settings.html')


@bp.route('/api/settings/rag-config', methods=['GET'])
def get_rag_config():
    with open(RAG_CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return jsonify(config)


@bp.route('/api/settings/rag-config', methods=['POST'])
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
