"""
Helper Utilities
"""
from datetime import datetime
import json

def format_response(data, message=None, status='success'):
    """Format API response"""
    response = {
        'status': status,
        'data': data,
        'timestamp': datetime.utcnow().isoformat()
    }
    if message:
        response['message'] = message
    return response

def format_error(error_message, status_code=400):
    """Format error response"""
    return {
        'status': 'error',
        'error': error_message,
        'timestamp': datetime.utcnow().isoformat()
    }, status_code

def paginate_results(query, page=1, per_page=20):
    """Paginate database query results"""
    # TODO: Implement pagination
    pass

def serialize_datetime(obj):
    """Serialize datetime objects for JSON"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")
