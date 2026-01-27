from flask import Blueprint, request, jsonify
from app.models.database_connection import DatabaseConnection
from app.services.database_services import DatabaseService

database_bp = Blueprint('database', __name__, url_prefix='/api/databases')

@database_bp.route('/', methods=['GET'])
def get_all_connections():
    """Get all database connections"""
    try:
        connections = DatabaseConnection.get_all()
        return jsonify({
            'databases': [conn.to_dict() for conn in connections],
            'total': len(connections)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@database_bp.route('/<int:connection_id>', methods=['GET'])
def get_connection(connection_id):
    """Get a specific database connection"""
    try:
        connection = DatabaseConnection.get_by_id(connection_id)
        
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        return jsonify({'database': connection.to_dict()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@database_bp.route('/', methods=['POST'])
def create_connection():
    """Create a new database connection"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'type', 'database', 'username', 'password']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Create new connection
        connection = DatabaseConnection.create(
            name=data.get('name'),
            db_type=data.get('type'),
            host=data.get('host', ''),
            port=data.get('port'),
            database=data.get('database'),
            username=data.get('username'),
            password=data.get('password'),
            workspace_id=data.get('workspace_id', ''),
            **{k: v for k, v in data.items() if k not in ['name', 'type', 'host', 'port', 'database', 'username', 'password', 'workspace_id']}
        )
        
        return jsonify({
            'message': 'Connection created successfully',
            'database': connection.to_dict()
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@database_bp.route('/<int:connection_id>', methods=['PUT'])
def update_connection(connection_id):
    """Update an existing database connection"""
    try:
        data = request.get_json()
        
        connection = DatabaseConnection.get_by_id(connection_id)
        
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        # Update connection
        connection.update(**data)
        
        return jsonify({
            'message': 'Connection updated successfully',
            'database': connection.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@database_bp.route('/<int:connection_id>', methods=['DELETE'])
def delete_connection(connection_id):
    """Delete a database connection"""
    try:
        connection = DatabaseConnection.get_by_id(connection_id)
        
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        DatabaseConnection.delete_by_id(connection_id)
        
        return jsonify({
            'message': 'Connection deleted successfully',
            'deleted_id': connection_id
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@database_bp.route('/test', methods=['POST'])
def test_new_connection():
    """Test a new database connection (without saving)"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if 'type' not in data:
            return jsonify({
                'status': 'error',
                'error': 'Database type is required'
            }), 400
        
        # Test the connection
        success, message, latency_ms = DatabaseService.test_connection(
            data.get('type'),
            data
        )
        
        if success:
            return jsonify({
                'status': 'success',
                'message': message,
                'latency_ms': latency_ms
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'error': message,
                'latency_ms': latency_ms
            }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@database_bp.route('/<int:connection_id>/test', methods=['POST'])
def test_existing_connection(connection_id):
    """Test an existing database connection"""
    try:
        connection = DatabaseConnection.get_by_id(connection_id)
        
        if not connection:
            return jsonify({
                'status': 'error',
                'error': 'Connection not found'
            }), 404
        
        # Test the connection
        config = connection.to_dict(include_password=True)
        success, message, latency_ms = DatabaseService.test_connection(
            connection.type,
            config
        )
        
        # Update connection status
        connection.status = 'connected' if success else 'disconnected'
        from datetime import datetime
        connection.last_tested = datetime.now().isoformat()
        
        if success:
            return jsonify({
                'status': 'success',
                'message': message,
                'latency_ms': latency_ms
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'error': message,
                'latency_ms': latency_ms
            }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@database_bp.route('/<int:connection_id>/schema', methods=['GET'])
def get_connection_schema(connection_id):
    """Get database schema for a connection"""
    try:
        connection = DatabaseConnection.get_by_id(connection_id)
        
        if not connection:
            return jsonify({'error': 'Connection not found'}), 404
        
        # Get schema
        schema = DatabaseService.get_schema(connection)
        
        return jsonify({'schema': schema}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500