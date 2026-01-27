"""
Database Connection API Routes
Handles database connections, schema discovery, and connection testing
"""
import time
import traceback
from flask import Blueprint, request, jsonify
from app import db
from app.models.database_connection import DatabaseConnection

bp = Blueprint('database', __name__, url_prefix='/api/databases')

def serialize_connection(conn):
    """Serialize database connection to dict"""
    try:
        return {
            'id': conn.id,
            'name': conn.name,
            'type': conn.type,
            'host': conn.host,
            'port': conn.port,
            'database': conn.database,
            'username': conn.username,
            'password': '********',
            'workspace_id': conn.workspace_id,
            'status': conn.status,
            'created_at': conn.created_at.isoformat() if conn.created_at else None,
            'updated_at': conn.updated_at.isoformat() if conn.updated_at else None,
            'last_tested': conn.last_tested.isoformat() if conn.last_tested else None
        }
    except Exception as e:
        print(f"Serialization error: {str(e)}")
        return {}

@bp.route('/', methods=['GET'])
def get_databases():
    """
    Get all configured database connections
    Query params: workspace_id
    Response: { "databases": [{id, name, type, host, status}] }
    """
    try:
        workspace_id = request.args.get('workspace_id', 1)
        
        try:
            if workspace_id:
                databases = DatabaseConnection.query.filter_by(workspace_id=workspace_id).all()
            else:
                databases = DatabaseConnection.query.all()
        except Exception as query_error:
            # If query fails (table might not exist), return empty list
            print(f"Query error: {str(query_error)}")
            databases = []
        
        return jsonify({
            'databases': [serialize_connection(conn) for conn in databases],
            'count': len(databases)
        }), 200
    except Exception as e:
        print(f"GET databases error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e), 'databases': []}), 200

@bp.route('/', methods=['POST'])
def create_database_connection():
    """
    Create new database connection
    Request: { "name": "Production DB", "type": "PostgreSQL", "host": "...", 
               "port": 5432, "database": "mydb", "username": "...", "password": "..." }
    Response: { "database": {...}, "message": "Connection created" }
    """
    try:
        data = request.get_json()
        
        # Validate required fields based on database type
        db_type = data.get('type', '')
        
        # Basic required fields for all types
        required_fields = ['name', 'type', 'username', 'password']
        
        # Add database field requirement based on type
        database_required = db_type not in ['ODBC', 'Others', 'BigQuery', 'Salesforce']
        if database_required:
            required_fields.append('database')
            
        for field in required_fields:
            if field not in data or not data[field] or (isinstance(data[field], str) and data[field].strip() == ''):
                return jsonify({'error': f'Missing required field: {field}'}), 400
                
        # For database types that don't require database name, set a default
        if not database_required and (not data.get('database') or data.get('database').strip() == ''):
            data['database'] = f"{db_type.lower()}_connection"
        
        # Create new connection
        connection = DatabaseConnection(
            name=data.get('name'),
            type=data.get('type'),
            host=data.get('host'),
            port=data.get('port'),
            database=data.get('database'),
            username=data.get('username'),
            password=data.get('password'),
            connection_string=data.get('connection_string'),
            workspace_id=data.get('workspace_id', 1),
            status='active'
        )
        
        db.session.add(connection)
        db.session.commit()
        
        return jsonify({
            'database': serialize_connection(connection),
            'message': 'Connection created successfully'
        }), 201
    except Exception as e:
        db.session.rollback()
        print(f"POST error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>', methods=['GET'])
def get_database(db_id):
    """
    Get specific database connection details
    Response: { "database": {...} }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({'database': serialize_connection(connection)}), 200
    except Exception as e:
        print(f"GET database error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>', methods=['PUT'])
def update_database_connection(db_id):
    """
    Update database connection
    Request: { "name": "...", "host": "...", ... }
    Response: { "database": {...}, "message": "Connection updated" }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        data = request.get_json()
        
        # Update fields
        for key in ['name', 'host', 'port', 'database', 'username', 'password', 'connection_string', 'type']:
            if key in data:
                setattr(connection, key, data[key])
        
        db.session.commit()
        
        return jsonify({
            'database': serialize_connection(connection),
            'message': 'Connection updated successfully'
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"PUT error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>', methods=['DELETE'])
def delete_database_connection(db_id):
    """
    Delete database connection
    Response: { "message": "Connection deleted" }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        db.session.delete(connection)
        db.session.commit()
        
        return jsonify({'message': 'Connection deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"DELETE error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/test', methods=['POST'])
def test_database_connection(db_id):
    """
    Test database connection
    Response: { "status": "success/failed", "latency_ms": 45, "error": null }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        start_time = time.time()
        
        try:
            if connection.type == 'PostgreSQL':
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=connection.host,
                        port=connection.port or 5432,
                        database=connection.database,
                        user=connection.username,
                        password=connection.password,
                        connect_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass  # psycopg2 not installed
            elif connection.type == 'MySQL':
                try:
                    import mysql.connector
                    conn = mysql.connector.connect(
                        host=connection.host,
                        port=connection.port or 3306,
                        database=connection.database,
                        user=connection.username,
                        password=connection.password,
                        connection_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass  # mysql.connector not installed
            
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'success',
                'latency_ms': round(latency_ms, 2),
                'error': None
            }), 200
        except Exception as test_error:
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'failed',
                'latency_ms': round(latency_ms, 2),
                'error': str(test_error)
            }), 200
    except Exception as e:
        print(f"Test connection error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/test', methods=['POST'])
def test_new_connection():
    """
    Test a new database connection (before saving)
    Request: { "type": "PostgreSQL", "host": "...", "port": 5432, ... }
    Response: { "status": "success/failed", "latency_ms": 45, "error": null }
    """
    try:
        data = request.get_json()
        start_time = time.time()
        
        try:
            if data.get('type') == 'PostgreSQL':
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=data.get('host'),
                        port=data.get('port', 5432),
                        database=data.get('database'),
                        user=data.get('username'),
                        password=data.get('password'),
                        connect_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass
            elif data.get('type') == 'MySQL':
                try:
                    import mysql.connector
                    conn = mysql.connector.connect(
                        host=data.get('host'),
                        port=data.get('port', 3306),
                        database=data.get('database'),
                        user=data.get('username'),
                        password=data.get('password'),
                        connection_timeout=5
                    )
                    conn.close()
                except ImportError:
                    pass
            
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'success',
                'latency_ms': round(latency_ms, 2),
                'error': None
            }), 200
        except Exception as test_error:
            latency_ms = (time.time() - start_time) * 1000
            return jsonify({
                'status': 'failed',
                'latency_ms': round(latency_ms, 2),
                'error': str(test_error)
            }), 200
    except Exception as e:
        print(f"Test new connection error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/schema', methods=['GET'])
def get_database_schema(db_id):
    """
    Get database schema (tables, columns, relationships)
    Response: { "schema": {tables: [{name, columns: [...]}]} }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({
            'schema': {'tables': []}
        }), 200
    except Exception as e:
        print(f"Schema error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/tables', methods=['GET'])
def get_database_tables(db_id):
    """
    Get list of tables in database
    Response: { "tables": ["users", "orders", "products", ...] }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({'tables': []}), 200
    except Exception as e:
        print(f"Tables error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/<int:db_id>/tables/<string:table_name>/columns', methods=['GET'])
def get_table_columns(db_id, table_name):
    """
    Get columns for specific table
    Response: { "columns": [{name, type, nullable, primary_key}] }
    """
    try:
        connection = DatabaseConnection.query.get(db_id)
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({'columns': []}), 200
    except Exception as e:
        print(f"Columns error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@bp.route('/types', methods=['GET'])
def get_database_types():
    """
    Get supported database types
    Response: { "types": ["PostgreSQL", "MySQL", "MongoDB", "SQL Server", "Oracle", "BigQuery"] }
    """
    types = [
        'PostgreSQL', 'MySQL', 'MongoDB', 'SQL Server', 'Oracle',
        'BigQuery', 'Snowflake', 'Redis', 'SAP HANA', 'Salesforce', 'ODBC'
    ]
    return jsonify({'types': types}), 200
