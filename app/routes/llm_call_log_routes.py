"""
LLM Call Log API Routes
Powers the "LLM Calls" page: a user-readable log of every LLM invocation
across the app, with token counts and cost, grouped into sub-menus by
"purpose" (which part of the app made the call).
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from app import db
from app.models.llm_call_log import LLMCallLog
from app.services.llm_call_logger import is_logging_enabled
from app.utils.auth_helpers import get_current_user

bp = Blueprint('llm_call_log', __name__, url_prefix='/api/llm-calls')


def _scoped_query(current_user):
    query = LLMCallLog.query
    if current_user.company_code:
        query = query.filter(LLMCallLog.company_code == current_user.company_code)
    else:
        query = query.filter(LLMCallLog.user_id == current_user.id)
    return query


@bp.route('/', methods=['GET'])
@jwt_required()
def list_llm_calls():
    """
    Query params:
      purpose  - filter to one purpose/sub-menu (default: all)
      model    - substring match against the model name
      provider - filter by provider (openai | anthropic | google | ollama | deepseek | ...)
      status   - success | error | all (default all)
      q        - free-text search over prompt/response preview and call code
      limit    - max rows to return (default 100, capped at 300)
    Response: { "calls": [...], "count": N }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required', 'calls': []}), 401

    query = _scoped_query(current_user)

    purpose = (request.args.get('purpose') or '').strip()
    if purpose and purpose.lower() != 'all':
        query = query.filter(LLMCallLog.purpose == purpose)

    model = (request.args.get('model') or '').strip()
    if model:
        query = query.filter(LLMCallLog.model.ilike(f"%{model}%"))

    provider = (request.args.get('provider') or '').strip()
    if provider and provider.lower() != 'all':
        query = query.filter(LLMCallLog.provider == provider)

    status = (request.args.get('status') or 'all').strip().lower()
    if status in ('success', 'error'):
        query = query.filter(LLMCallLog.status == status)

    search = (request.args.get('q') or '').strip()
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            LLMCallLog.prompt_preview.ilike(like),
            LLMCallLog.response_preview.ilike(like),
            LLMCallLog.call_code.ilike(like),
        ))

    limit = 100
    try:
        limit = min(int(request.args.get('limit', 100)), 300)
    except (TypeError, ValueError):
        pass

    rows = query.order_by(LLMCallLog.created_at.desc()).limit(limit).all()
    return jsonify({'calls': [r.to_dict() for r in rows], 'count': len(rows)}), 200


@bp.route('/summary', methods=['GET'])
@jwt_required()
def llm_calls_summary():
    """
    Aggregate totals plus a per-purpose breakdown - the data behind the
    page's headline cost/call-count numbers and its sub-menu list.
    Response: {
      "logging_enabled": bool,
      "totals": {"calls": N, "cost": X, "prompt_tokens": N, "completion_tokens": N, "total_tokens": N, "errors": N},
      "by_purpose": [{"purpose": "...", "calls": N, "cost": X, "total_tokens": N, "errors": N}, ...]
    }
    """
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    base = _scoped_query(current_user)

    totals_row = base.with_entities(
        func.count(LLMCallLog.id),
        func.coalesce(func.sum(LLMCallLog.cost), 0.0),
        func.coalesce(func.sum(LLMCallLog.prompt_tokens), 0),
        func.coalesce(func.sum(LLMCallLog.completion_tokens), 0),
        func.coalesce(func.sum(LLMCallLog.total_tokens), 0),
        func.sum(db.case((LLMCallLog.status == 'error', 1), else_=0)),
    ).first()

    totals = {
        'calls': totals_row[0] or 0,
        'cost': round(totals_row[1] or 0.0, 6),
        'prompt_tokens': totals_row[2] or 0,
        'completion_tokens': totals_row[3] or 0,
        'total_tokens': totals_row[4] or 0,
        'errors': totals_row[5] or 0,
    }

    by_purpose_rows = base.with_entities(
        LLMCallLog.purpose,
        func.count(LLMCallLog.id),
        func.coalesce(func.sum(LLMCallLog.cost), 0.0),
        func.coalesce(func.sum(LLMCallLog.total_tokens), 0),
        func.sum(db.case((LLMCallLog.status == 'error', 1), else_=0)),
    ).group_by(LLMCallLog.purpose).order_by(func.count(LLMCallLog.id).desc()).all()

    by_purpose = [
        {
            'purpose': row[0],
            'calls': row[1] or 0,
            'cost': round(row[2] or 0.0, 6),
            'total_tokens': row[3] or 0,
            'errors': row[4] or 0,
        }
        for row in by_purpose_rows
    ]

    return jsonify({
        'logging_enabled': is_logging_enabled(),
        'totals': totals,
        'by_purpose': by_purpose,
    }), 200
