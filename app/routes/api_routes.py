from flask import Blueprint, render_template, request, jsonify
from flask_jwt_extended import jwt_required
import requests
from app import db, limiter
from app.models.api_connector import ApiConnector
from app.utils.crypto import encrypt, decrypt
from app.utils.network_guard import is_safe_url
from app.utils.auth_helpers import get_current_user
from app.services.audit_service import log_event

# 1. Define the separate blueprint for API data sources
bp = Blueprint('api_connectors', __name__)


@bp.route('/api/feedback', methods=['POST'])
def submit_feedback_alias():
    """Alias endpoint for feedback submission."""
    from app.routes.chat_routes import submit_feedback
    return submit_feedback()

@bp.route('/api_connectors/rest_apis')
def rest_apis_page():
    """Renders the REST API custom tool registration dashboard"""
    return render_template('api_connectors/rest_apis.html')

@bp.route('/api_connectors/test_connection', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def test_connection():
    """Pings the target API endpoint to check if it's live"""
    data = request.get_json() or {}
    base_url = data.get('baseUrl', '')
    endpoint = data.get('endpoint', '')
    method = data.get('method', 'GET')
    auth_type = data.get('authType', 'No Auth')
    api_token = data.get('apiToken') or ''

    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    safe, reason = is_safe_url(full_url)
    if not safe:
        return jsonify({"status": "error", "message": reason}), 400

    # Mirrors the header logic actually used at query time
    # (app.services.api_services._auth_headers) - the token here is
    # whatever's currently typed into the form (plaintext), not the
    # encrypted value read back from storage, so no decrypt() needed.
    headers = {}
    if api_token and auth_type == 'Bearer Token':
        headers['Authorization'] = f'Bearer {api_token}'
    elif api_token and auth_type == 'API Key':
        headers['X-API-Key'] = api_token

    try:
        response = requests.request(method=method, url=full_url, headers=headers, timeout=5)
        return jsonify({
            "status": "success",
            "code": response.status_code,
            "message": "Connection test succeeded."
        })
    except Exception as e:
        print(f"❌ Test connection failed for '{full_url}': {e}")
        return jsonify({
            "status": "error",
            "message": "Connection test failed. Please check the URL and try again."
        })

@bp.route('/api_connectors/save_tool', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def save_tool():
    """Registers (or updates) an API connector tool."""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    data = request.get_json() or {}

    integration_name = data.get('integrationName')
    base_url = data.get('baseUrl')
    endpoint = data.get('endpoint')
    method = data.get('method')
    auth_type = data.get('authType')
    api_description = data.get('apiDescription')
    # Empty means "leave the existing token alone" on edit - the frontend
    # never re-sends a previously-saved token back to the client.
    new_token = data.get('apiToken') or ''

    if not integration_name or not base_url or not endpoint:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    safe, reason = is_safe_url(full_url)
    if not safe:
        return jsonify({"status": "error", "message": reason}), 400

    try:
        tool = ApiConnector.query.filter_by(integration_name=integration_name).first()
        if tool:
            tool.base_url = base_url
            tool.endpoint = endpoint
            tool.method = method
            tool.auth_type = auth_type
            tool.api_description = api_description
            if new_token:
                tool.api_token = encrypt(new_token)
        else:
            tool = ApiConnector(
                integration_name=integration_name,
                base_url=base_url,
                endpoint=endpoint,
                method=method,
                auth_type=auth_type,
                api_token=encrypt(new_token) if new_token else None,
                api_description=api_description,
                company_code=current_user.company_code,
                created_by_user_id=current_user.id,
            )
            db.session.add(tool)

        db.session.commit()
        log_event('api_connector_saved', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='api', resource_id=tool.id, details={'integration_name': integration_name})

        from app.services.automated_metamind import generate_router_config
        generate_router_config(user_id=current_user.id, force=True)

        return jsonify({
            "status": "success",
            "message": f"'{integration_name}' was saved successfully."
        })

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error saving tool record: {e}")
        return jsonify({
            "status": "error",
            "message": "Something went wrong while saving this tool. Please try again."
        }), 500

@bp.route('/api_connectors/delete_tool/<string:integration_name>', methods=['DELETE'])
@jwt_required()
def delete_tool(integration_name):
    """Deletes a registered API tool by its unique name"""
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    try:
        tool = ApiConnector.query.filter_by(integration_name=integration_name).first()
        if not tool:
            return jsonify({"status": "error", "message": "Tool not found."}), 404

        if tool.created_by_user_id != current_user.id and current_user.role != 'admin':
            return jsonify({"status": "error", "message": "Only the creator or a company admin can delete this tool"}), 403

        from app.models.resource_mapping import ResourceMapping
        affected_user_ids = {current_user.id, tool.created_by_user_id} | {
            m.user_id for m in ResourceMapping.query.filter_by(resource_type='api', resource_id=tool.id).all()
        }

        tool_id = tool.id
        db.session.delete(tool)
        db.session.commit()

        log_event('api_connector_deleted', company_code=current_user.company_code, user_id=current_user.id,
                   resource_type='api', resource_id=tool_id, details={'integration_name': integration_name})

        from app.services.automated_metamind import generate_router_config
        for uid in affected_user_ids:
            generate_router_config(user_id=uid, force=True)

        return jsonify({
            "status": "success",
            "message": f"'{integration_name}' was removed successfully."
        })

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error deleting tool record: {e}")
        return jsonify({
            "status": "error",
            "message": "Something went wrong while removing this tool. Please try again."
        }), 500

@bp.route('/api_connectors/get_tools', methods=['GET'])
@jwt_required()
def get_tools():
    """
    Lists API connectors the current user created, plus any explicitly
    granted to them via Resource Mapping - nothing is auto-shared.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    try:
        own_tools = ApiConnector.query.filter_by(created_by_user_id=current_user.id).all()

        from app.models.resource_mapping import ResourceMapping
        granted_ids = [
            m.resource_id for m in ResourceMapping.query.filter_by(
                resource_type='api', user_id=current_user.id
            ).all()
        ]
        granted_tools = ApiConnector.query.filter(ApiConnector.id.in_(granted_ids)).all() if granted_ids else []

        seen_ids = set()
        tools_list = []
        for tool in own_tools + granted_tools:
            if tool.id not in seen_ids:
                seen_ids.add(tool.id)
                d = tool.to_dict()
                d['has_token'] = bool(tool.api_token)
                del d['api_token']
                tools_list.append(d)

        return jsonify({
            "status": "success",
            "tools": tools_list
        })

    except Exception as e:
        print(f"❌ Error fetching tool records: {e}")
        return jsonify({
            "status": "error",
            "message": "Could not load your tools. Please refresh and try again."
        }), 500


@bp.route('/api_connectors/tools/<string:integration_name>/process', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def process_tool(integration_name):
    """
    Explicit process action for a saved API tool.
    Triggers router config regeneration (for whoever can currently see
    this tool) only when the user clicks Process.
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    try:
        tool = ApiConnector.query.filter_by(integration_name=integration_name).first()
        if not tool:
            return jsonify({"status": "error", "message": "This tool could not be found."}), 404

        from app.models.resource_mapping import ResourceMapping
        affected_user_ids = {current_user.id, tool.created_by_user_id} | {
            m.user_id for m in ResourceMapping.query.filter_by(resource_type='api', resource_id=tool.id).all()
        }

        from app.services.automated_metamind import generate_router_config
        try:
            for uid in affected_user_ids:
                generate_router_config(user_id=uid, force=True)
            return jsonify({"status": "success", "message": "Tool is now active and ready to use."})
        except Exception as e:
            print(f"❌ Error regenerating router config for '{integration_name}': {e}")
            return jsonify({"status": "error", "message": "Something went wrong while activating this tool. Please try again."}), 500
    except Exception as e:
        print(f"❌ Error processing tool '{integration_name}': {e}")
        return jsonify({"status": "error", "message": "Something went wrong while activating this tool. Please try again."}), 500
