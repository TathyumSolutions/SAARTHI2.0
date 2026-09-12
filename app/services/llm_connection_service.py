"""
LLM Connection resolution and budget enforcement.

Mirrors how DatabaseConnection access works (see app/routes/database_routes.py
get_databases): a user can use an LLMConnection they created themselves, plus
any LLMConnection an admin has explicitly granted them via Resource Mapping
(resource_type='llm') - nothing is auto-shared just for belonging to the same
company. A grant may also carry a daily_budget; once today's spend on that
connection (summed from LLMCallLog) reaches it, the connection is treated as
unavailable to that user until the next day.

This module is additive: it does not change how any existing LLM call site
builds its client today (see app/services/llm_providers.py /
app/services/llm_service.py). Callers that want budget-enforced, per-user
connection selection should call resolve_connection_for_user() before
building their LLM client, and pass the returned connection's id as
llm_connection_id into record_llm_call()/tracked_invoke() so usage is
attributed back to it.
"""
from datetime import datetime, timedelta

from app import db
from app.models.llm_connection import LLMConnection
from app.models.resource_mapping import ResourceMapping
from app.models.llm_call_log import LLMCallLog
from app.utils.crypto import decrypt


def get_user_llm_connections(user_id, company_code=None):
    """Every LLMConnection this user may use: their own, plus any granted to
    them via Resource Mapping. Same own+granted+dedupe pattern as
    database_routes.get_databases()."""
    own = LLMConnection.query.filter_by(created_by_user_id=user_id).all()

    granted_ids = [
        m.resource_id for m in ResourceMapping.query.filter_by(
            resource_type='llm', user_id=user_id
        ).all()
    ]
    granted = LLMConnection.query.filter(LLMConnection.id.in_(granted_ids)).all() if granted_ids else []

    seen_ids = set()
    connections = []
    for conn in own + granted:
        if conn.id not in seen_ids:
            seen_ids.add(conn.id)
            connections.append(conn)
    return connections


def get_allocation(user_id, llm_connection_id):
    """The ResourceMapping grant (with its daily_budget, if any) tying this
    user to this connection - None if the connection is the user's own
    (unlimited, no grant row exists) or not allocated to them at all."""
    return ResourceMapping.query.filter_by(
        resource_type='llm', resource_id=llm_connection_id, user_id=user_id
    ).first()


def get_daily_usage(user_id, llm_connection_id, on_date=None):
    """Sum of LLMCallLog.cost for this user+connection since the start of
    on_date (default: today, UTC)."""
    day_start = datetime.combine((on_date or datetime.utcnow()).date(), datetime.min.time())
    day_end = day_start + timedelta(days=1)
    total = db.session.query(db.func.coalesce(db.func.sum(LLMCallLog.cost), 0.0)).filter(
        LLMCallLog.user_id == user_id,
        LLMCallLog.llm_connection_id == llm_connection_id,
        LLMCallLog.created_at >= day_start,
        LLMCallLog.created_at < day_end,
    ).scalar()
    return float(total or 0.0)


def get_budget_status(user_id, llm_connection_id):
    """{'daily_budget', 'budget_currency', 'used_today', 'remaining', 'exceeded'}
    for this user's allocation of this connection. daily_budget/remaining are
    None when the grant has no cap (or the user owns the connection outright,
    i.e. there is no grant row)."""
    allocation = get_allocation(user_id, llm_connection_id)
    used_today = get_daily_usage(user_id, llm_connection_id)
    daily_budget = float(allocation.daily_budget) if allocation and allocation.daily_budget is not None else None
    remaining = (daily_budget - used_today) if daily_budget is not None else None
    return {
        'daily_budget': daily_budget,
        'budget_currency': allocation.budget_currency if allocation else 'USD',
        'used_today': used_today,
        'remaining': remaining,
        'exceeded': remaining is not None and remaining <= 0,
    }


def resolve_connection_for_user(user_id, company_code=None, provider=None, model=None):
    """Picks the best active, in-budget LLMConnection this user may use,
    preferring one matching `provider`/`model` when given. Returns
    (connection, decrypted_api_key) or (None, None) if nothing usable is
    allocated - callers should fall back to their existing env-var-based
    client construction in that case, exactly as they do today."""
    candidates = [c for c in get_user_llm_connections(user_id, company_code) if c.status == 'active']

    def _matches(c):
        if provider and c.provider != provider:
            return False
        if model and c.model != model:
            return False
        return True

    for predicate in (lambda c: _matches(c), lambda c: not provider and not model):
        for conn in candidates:
            if predicate(conn):
                if not get_budget_status(user_id, conn.id)['exceeded']:
                    return conn, decrypt(conn.api_key)
    return None, None
