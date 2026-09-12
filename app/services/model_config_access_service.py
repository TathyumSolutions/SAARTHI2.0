"""
Model Configuration access and budget enforcement.

"Configured Models" (AI & Models > Configure New Model, backed by
ModelConfiguration - see app/routes/model_config_routes.py) is the one
place LLM provider/model/API-key settings are registered in this app.
Access to another user's configuration is granted the same way access to
a DatabaseConnection/ApiConnector/FileResource is granted: an admin-curated
Resource Mapping row (resource_type='llm', resource_id=ModelConfiguration.id)
- see app/routes/resource_mapping_routes.py. A grant may also carry a
daily_budget; once today's spend against that configuration (summed from
LLMCallLog) reaches it, the configuration is treated as unavailable to that
user until the next day.

This module is additive: it does not change how any existing LLM call site
resolves its model/credentials today (see app/services/llm_service.py,
model_selection_service.py). Callers that want budget-enforced, per-user
configuration selection should call resolve_configuration_for_user() before
building their LLM client, and pass the returned configuration's id as
model_configuration_id into record_llm_call()/tracked_invoke() so usage is
attributed back to it.
"""
from datetime import datetime, timedelta

from app import db
from app.models.model_config import ModelConfiguration
from app.models.resource_mapping import ResourceMapping
from app.models.llm_call_log import LLMCallLog

# Bookkeeping rows ModelConfiguration uses internally (the per-user default
# pointer, seeded open-source defaults) aren't real user-registered
# configurations and should never show up as grantable/allocatable.
_INTERNAL_CONFIG_NAMES = ('global_default',)


def get_user_model_configurations(user_id, company_code=None):
    """Every ModelConfiguration this user may use: their own, plus any
    granted to them via Resource Mapping. Same own+granted+dedupe pattern
    as database_routes.get_databases()."""
    own = ModelConfiguration.query.filter(
        ModelConfiguration.user_id == user_id,
        ~ModelConfiguration.name.in_(_INTERNAL_CONFIG_NAMES),
    ).all()

    granted_ids = [
        m.resource_id for m in ResourceMapping.query.filter_by(
            resource_type='llm', user_id=user_id
        ).all()
    ]
    granted = ModelConfiguration.query.filter(
        ModelConfiguration.id.in_(granted_ids)
    ).all() if granted_ids else []

    seen_ids = set()
    configs = []
    for cfg in own + granted:
        if cfg.id not in seen_ids:
            seen_ids.add(cfg.id)
            configs.append(cfg)
    return configs


def get_allocation(user_id, model_configuration_id):
    """The ResourceMapping grant (with its daily_budget, if any) tying this
    user to this configuration - None if the configuration is the user's
    own (unlimited, no grant row exists) or not allocated to them at all."""
    return ResourceMapping.query.filter_by(
        resource_type='llm', resource_id=model_configuration_id, user_id=user_id
    ).first()


def get_daily_usage(user_id, model_configuration_id, on_date=None):
    """Sum of LLMCallLog.cost for this user+configuration since the start
    of on_date (default: today, UTC)."""
    day_start = datetime.combine((on_date or datetime.utcnow()).date(), datetime.min.time())
    day_end = day_start + timedelta(days=1)
    total = db.session.query(db.func.coalesce(db.func.sum(LLMCallLog.cost), 0.0)).filter(
        LLMCallLog.user_id == user_id,
        LLMCallLog.model_configuration_id == model_configuration_id,
        LLMCallLog.created_at >= day_start,
        LLMCallLog.created_at < day_end,
    ).scalar()
    return float(total or 0.0)


def get_budget_status(user_id, model_configuration_id):
    """{'daily_budget', 'budget_currency', 'used_today', 'remaining', 'exceeded'}
    for this user's allocation of this configuration. daily_budget/remaining
    are None when the grant has no cap (or the user owns the configuration
    outright, i.e. there is no grant row)."""
    allocation = get_allocation(user_id, model_configuration_id)
    used_today = get_daily_usage(user_id, model_configuration_id)
    daily_budget = float(allocation.daily_budget) if allocation and allocation.daily_budget is not None else None
    remaining = (daily_budget - used_today) if daily_budget is not None else None
    return {
        'daily_budget': daily_budget,
        'budget_currency': allocation.budget_currency if allocation else 'USD',
        'used_today': used_today,
        'remaining': remaining,
        'exceeded': remaining is not None and remaining <= 0,
    }


def resolve_configuration_for_user(user_id, company_code=None, provider=None, model=None):
    """Picks the best active, in-budget ModelConfiguration this user may
    use, preferring one matching `provider`/`model` when given. Returns the
    ModelConfiguration, or None if nothing usable is allocated - callers
    should fall back to their existing model-resolution behavior (e.g.
    model_selection_service.get_model_for_step) in that case."""
    candidates = get_user_model_configurations(user_id, company_code)

    def _matches(c):
        if provider and (c.provider or '').lower() != provider.lower():
            return False
        if model and c.model != model:
            return False
        return True

    for predicate in (lambda c: _matches(c), lambda c: not provider and not model):
        for cfg in candidates:
            if predicate(cfg):
                if not get_budget_status(user_id, cfg.id)['exceeded']:
                    return cfg
    return None
