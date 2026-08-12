"""
Query Log API Routes
Powers the "Queries" section of the Knowledge Base page: every logged chat
query with its strategy/sources/main query, self-learning feedback remarks,
and fresh-vs-reused execution flag - searchable and filterable by
accepted/rejected feedback, execution type, and data source.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app import db
from app.models.query_log import QueryLog
from app.utils.auth_helpers import get_current_user

bp = Blueprint('query_log', __name__, url_prefix='/api/query-logs')


@bp.route('/', methods=['GET'])
@jwt_required()
def list_query_logs():
    """
    Query params:
      q          - free-text search over the question, main query, and query code
      source     - filter by data source used: DB | API | FILES | SPREADSHEET | GENERAL | MULTI | all (default all)
      data_source - free-text match against the specific tables/tools listed in "sources"
      feedback   - accepted | rejected | unrated | all (default all)
      execution  - fresh | reused | all (default all)
      user_id    - restrict to a specific user's queries (defaults to everyone visible to the caller)
      limit      - max rows to return (default 100, capped at 300)
    Response: { "queries": [...], "count": N }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'queries': []}), 401

    query = QueryLog.query
    # Company-scoped, same visibility boundary as everything else in the
    # Knowledge Base - falls back to "just this user" when there's no
    # company_code to scope by at all.
    if current_user.company_code:
        query = query.filter(QueryLog.company_code == current_user.company_code)
    else:
        query = query.filter(QueryLog.user_id == current_user.id)

    user_id_filter = request.args.get('user_id')
    if user_id_filter:
        try:
            query = query.filter(QueryLog.user_id == int(user_id_filter))
        except ValueError:
            pass

    feedback = (request.args.get('feedback') or 'all').strip().lower()
    if feedback == 'accepted':
        query = query.filter(QueryLog.feedback_type == 'like')
    elif feedback == 'rejected':
        query = query.filter(QueryLog.feedback_type == 'dislike')
    elif feedback == 'unrated':
        query = query.filter(QueryLog.feedback_type.is_(None))

    execution = (request.args.get('execution') or 'all').strip().lower()
    if execution in ('fresh', 'reused'):
        query = query.filter(QueryLog.execution_type == execution)

    source = (request.args.get('source') or 'all').strip().upper()
    if source != 'ALL':
        query = query.filter(QueryLog.router_decision == source)

    search = (request.args.get('q') or '').strip()
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            QueryLog.question.ilike(like),
            QueryLog.main_query.ilike(like),
            QueryLog.query_code.ilike(like),
        ))

    limit = 100
    try:
        limit = min(int(request.args.get('limit', 100)), 300)
    except (TypeError, ValueError):
        pass

    rows = query.order_by(QueryLog.created_at.desc()).limit(limit).all()

    # "sources" is a JSON list column - matched in Python rather than at
    # the SQL level, since JSON containment operators differ across the
    # SQLite (dev) / Postgres (prod) bind targets this app runs against.
    data_source_filter = (request.args.get('data_source') or '').strip().lower()
    if data_source_filter:
        rows = [
            r for r in rows
            if any(data_source_filter in str(s).lower() for s in (r.sources or []))
        ]

    return jsonify({'queries': [r.to_dict() for r in rows], 'count': len(rows)}), 200
