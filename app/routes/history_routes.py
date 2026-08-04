"""
History API Routes
Handles activity history, audit logs, and recent activities
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.audit_log import AuditLog
from app.utils.decorators import admin_required

bp = Blueprint('history', __name__, url_prefix='/api/history')

@bp.route('/activities', methods=['GET'])
@jwt_required()
def get_activities():
    """
    Get activity history
    Query params: workspace_id, limit, offset, type, date_range
    Response: { "activities": [{id, type, action, user, timestamp, details}] }
    """
    # TODO: Implement get activities logic
    pass

@bp.route('/recent', methods=['GET'])
@jwt_required()
def get_recent_activities():
    """
    Get recent activities (last 24 hours)
    Query params: workspace_id, limit
    Response: { "activities": [...] }
    """
    # TODO: Implement get recent activities
    pass

@bp.route('/queries', methods=['GET'])
@jwt_required()
def get_query_history():
    """
    Get query execution history with filters
    Query params: workspace_id, database_id, date_range, status, limit, offset
    Response: { "queries": [{id, query, sql, status, duration, timestamp}] }
    """
    # TODO: Implement get query history logic
    pass

@bp.route('/exports', methods=['GET'])
@jwt_required()
def get_export_history():
    """
    Get export history
    Query params: workspace_id, limit, offset
    Response: { "exports": [{id, type, file_name, status, created_at, download_url}] }
    """
    # TODO: Implement get export history
    pass

@bp.route('/audit', methods=['GET'])
@jwt_required()
@admin_required
def get_audit_logs(current_user):
    """
    Get audit logs for the acting admin's own company.
    Query params: action, resource_type, limit (default 200, max 500)
    Response: { "logs": [{id, user_id, action, resource_type, resource_id, details, created_at}] }
    """
    if not current_user.company_code:
        return jsonify({"logs": []}), 200

    query = AuditLog.query.filter_by(company_code=current_user.company_code)

    action = request.args.get('action')
    if action:
        query = query.filter_by(action=action)

    resource_type = request.args.get('resource_type')
    if resource_type:
        query = query.filter_by(resource_type=resource_type)

    limit = min(int(request.args.get('limit', 200)), 500)
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    return jsonify({"logs": [log.to_dict() for log in logs]}), 200

@bp.route('/stats', methods=['GET'])
@jwt_required()
def get_usage_stats():
    """
    Get usage statistics
    Query params: workspace_id, date_range
    Response: { "stats": {query_count, user_count, data_accessed, llm_tokens_used} }
    """
    # TODO: Implement get usage stats
    pass
