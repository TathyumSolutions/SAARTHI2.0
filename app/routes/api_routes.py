from flask import Blueprint, render_template, request, jsonify,current_app
from flask_jwt_extended import jwt_required
import requests
import psycopg2
from urllib.parse import urlparse
from app.utils.crypto import encrypt, decrypt
from app.utils.network_guard import is_safe_url
from app import limiter
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
    print("Rendering api_connectors/rest_apis.html from dedicated file")
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

    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    safe, reason = is_safe_url(full_url)
    if not safe:
        return jsonify({"status": "error", "message": reason}), 400

    try:
        # Perform a live mock request with a short timeout
        response = requests.request(method=method, url=full_url, timeout=5)
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
    """Receives form data to save the configured API tool"""
    data = request.get_json() or {}

    # Extract form fields sent by the frontend
    integration_name = data.get('integrationName')
    base_url = data.get('baseUrl')
    endpoint = data.get('endpoint')
    method = data.get('method')
    auth_type = data.get('authType')
    # Encrypted at rest. An empty value here means "leave the existing
    # token alone" (the frontend never re-sends a previously-saved token
    # back to the client, so on edit this field is blank unless the user
    # is deliberately setting a new one) - handled via COALESCE/NULLIF
    # below rather than overwriting a real token with an empty string.
    api_token = encrypt(data.get('apiToken') or '')
    api_description = data.get('apiDescription')

    if not integration_name or not base_url or not endpoint:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    safe, reason = is_safe_url(full_url)
    if not safe:
        return jsonify({"status": "error", "message": reason}), 400

    # Dynamically extract your exact container credentials directly from the app configuration
    base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')

    # Parse the host/credentials to build the targeted DSN to your custom database room
    try:
        from urllib.parse import urlparse
        result = urlparse(base_uri)
        dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"

        # Connect and insert the row cleanly
        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()

        insert_query = """
        INSERT INTO registered_tools (integration_name, base_url, endpoint, method, auth_type, api_token, api_description)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (integration_name)
        DO UPDATE SET
            base_url = EXCLUDED.base_url,
            endpoint = EXCLUDED.endpoint,
            method = EXCLUDED.method,
            auth_type = EXCLUDED.auth_type,
            api_token = COALESCE(NULLIF(EXCLUDED.api_token, ''), registered_tools.api_token),
            api_description = EXCLUDED.api_description;
        """
        
        cursor.execute(insert_query, (integration_name, base_url, endpoint, method, auth_type, api_token, api_description))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        print(f"🔥 Successfully written tool to registry: {integration_name} -> {base_url}{endpoint}")
        return jsonify({
            "status": "success",
            "message": f"'{integration_name}' was saved successfully."
        })

    except Exception as e:
        print(f"❌ Error inserting tool record: {e}")
        return jsonify({
            "status": "error",
            "message": "Something went wrong while saving this tool. Please try again."
        }), 500

@bp.route('/api_connectors/delete_tool/<string:integration_name>', methods=['DELETE'])
@jwt_required()
def delete_tool(integration_name):
    """Deletes a registered API tool from saarthi_api_db by its unique name"""
    base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    
    try:
        from urllib.parse import urlparse
        result = urlparse(base_uri)
        dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"
        
        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        
        delete_query = "DELETE FROM registered_tools WHERE integration_name = %s;"
        cursor.execute(delete_query, (integration_name,))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        print(f"🗑️ Successfully deleted tool from registry: {integration_name}")
        return jsonify({
            "status": "success",
            "message": f"'{integration_name}' was removed successfully."
        })

    except Exception as e:
        print(f"❌ Error deleting tool record: {e}")
        return jsonify({
            "status": "error",
            "message": "Something went wrong while removing this tool. Please try again."
        }), 500
    
@bp.route('/api_connectors/get_tools', methods=['GET'])
@jwt_required()
def get_tools():
    """Retrieves all registered custom active endpoints directly out of saarthi_api_db"""
    base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    
    try:
        from urllib.parse import urlparse
        result = urlparse(base_uri)
        dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"
        
        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        
        select_query = """
        SELECT integration_name, base_url, endpoint, method, auth_type, api_token, api_description 
        FROM registered_tools 
        ORDER BY created_at DESC;
        """
        cursor.execute(select_query)
        rows = cursor.fetchall()
        
        # Format database rows cleanly into digestible objects for the frontend fetch query.
        # The stored token is never sent back to the browser once saved -
        # only whether one exists, so the edit form can show that state
        # without re-exposing the secret on every list load.
        tools_list = []
        for row in rows:
            tools_list.append({
                "integration_name": row[0],
                "base_url": row[1],
                "endpoint": row[2],
                "method": row[3],
                "auth_type": row[4],
                "has_token": bool(row[5]),
                "api_description": row[6]
            })
            
        cursor.close()
        conn.close()
        
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
    Triggers router config regeneration only when user clicks Process.
    """
    base_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')

    try:
        result = urlparse(base_uri)
        dsn = f"postgresql://{result.username}:{result.password}@{result.hostname}:{result.port or 5432}/saarthi_api_db"

        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM registered_tools WHERE integration_name = %s;", (integration_name,))
        exists = cursor.fetchone() is not None
        cursor.close()
        conn.close()

        if not exists:
            return jsonify({"status": "error", "message": "This tool could not be found."}), 404

        from app.services.automated_metamind import generate_router_config
        try:
            generate_router_config(force=True)
            return jsonify({"status": "success", "message": "Tool is now active and ready to use."})
        except Exception as e:
            print(f"❌ Error regenerating router config for '{integration_name}': {e}")
            return jsonify({"status": "error", "message": "Something went wrong while activating this tool. Please try again."}), 500
    except Exception as e:
        print(f"❌ Error processing tool '{integration_name}': {e}")
        return jsonify({"status": "error", "message": "Something went wrong while activating this tool. Please try again."}), 500

    # Connect your DB execution helper here (e.g., db.execute or models.save)
    #print(f"Saving new tool to registry: {integration_name} -> {base_url}{endpoint}")

    #return jsonify({
    #    "status": "success", 
    #    "message": f"Tool '{integration_name}' successfully registered to Saarthi core!"
    #})