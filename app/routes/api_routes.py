from flask import Blueprint, render_template, request, jsonify,current_app
import requests
import psycopg2
from urllib.parse import urlparse
# 1. Define the separate blueprint for API data sources
bp = Blueprint('api_connectors', __name__)

@bp.route('/api_connectors/rest_apis')
def rest_apis_page():
    """Renders the REST API custom tool registration dashboard"""
    print("Rendering api_connectors/rest_apis.html from dedicated file")
    return render_template('api_connectors/rest_apis.html')

@bp.route('/api_connectors/test_connection', methods=['POST'])
def test_connection():
    """Pings the target API endpoint to check if it's live"""
    data = request.get_json() or {}
    base_url = data.get('baseUrl', '')
    endpoint = data.get('endpoint', '')
    method = data.get('method', 'GET')
    
    full_url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    
    try:
        # Perform a live mock request with a short timeout
        response = requests.request(method=method, url=full_url, timeout=5)
        return jsonify({
            "status": "success", 
            "code": response.status_code,
            "message": f"Connected successfully! Endpoint returned status {response.status_code}"
        })
    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": f"Could not reach endpoint: {str(e)}"
        })

@bp.route('/api_connectors/save_tool', methods=['POST'])
def save_tool():
    """Receives form data to save the configured API tool"""
    data = request.get_json() or {}
    
    # Extract form fields sent by the frontend
    integration_name = data.get('integrationName')
    base_url = data.get('baseUrl')
    endpoint = data.get('endpoint')
    method = data.get('method')
    auth_type = data.get('authType')
    api_token = data.get('apiToken')
    api_description = data.get('apiDescription')

    if not integration_name or not base_url or not endpoint:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

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
            api_token = EXCLUDED.api_token,
            api_description = EXCLUDED.api_description;
        """
        
        cursor.execute(insert_query, (integration_name, base_url, endpoint, method, auth_type, api_token, api_description))
        conn.commit()
        
        cursor.close()
        conn.close()
        
        print(f"🔥 Successfully written tool to registry: {integration_name} -> {base_url}{endpoint}")
        return jsonify({
            "status": "success", 
            "message": f"Tool '{integration_name}' successfully registered and saved to Saarthi Core Tool Registry!"
        })

    except Exception as e:
        print(f"❌ Error inserting tool record: {e}")
        return jsonify({
            "status": "error",
            "message": f"Database storage failure: {str(e)}"
        }), 500

@bp.route('/api_connectors/delete_tool/<string:integration_name>', methods=['DELETE'])
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
            "message": f"Tool '{integration_name}' successfully removed from Saarthi Core Registry!"
        })

    except Exception as e:
        print(f"❌ Error deleting tool record: {e}")
        return jsonify({
            "status": "error",
            "message": f"Database execution failure: {str(e)}"
        }), 500    
    
@bp.route('/api_connectors/get_tools', methods=['GET'])
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
        
        # Format database rows cleanly into digestible objects for the frontend fetch query
        tools_list = []
        for row in rows:
            tools_list.append({
                "integration_name": row[0],
                "base_url": row[1],
                "endpoint": row[2],
                "method": row[3],
                "auth_type": row[4],
                "api_token": row[5],
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
            "message": f"Database read transaction failure: {str(e)}"
        }), 500

    # Connect your DB execution helper here (e.g., db.execute or models.save)
    #print(f"Saving new tool to registry: {integration_name} -> {base_url}{endpoint}")

    #return jsonify({
    #    "status": "success", 
    #    "message": f"Tool '{integration_name}' successfully registered to Saarthi core!"
    #})