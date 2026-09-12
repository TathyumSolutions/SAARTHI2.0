"""
One-time backfill for admin-granted LLM access.

Before this feature, every LLM call in the app authenticated with the
global OPENAI_API_KEY / ANTHROPIC_API_KEY / AZURE_OPENAI_KEY env vars
(see config/config.py). Now that access to a "Configured Model"
(ModelConfiguration - the same entity behind the AI & Models > Configure
New Model modal) can be admin-granted per user via Resource Mapping
(resource_type='llm', with an optional daily_budget), existing users need
an equivalent configuration + grant so nothing regresses on cutover:

  1. For each configured provider env var, create one shared
     ModelConfiguration per company (company_code set, owned by that
     company's first admin) - or one private ModelConfiguration per
     individual account (company_code IS NULL).
  2. Grant every existing user in a company a Resource Mapping
     (resource_type='llm') to that company's legacy configuration(s), with
     daily_budget=NULL (unlimited) so existing usage isn't newly capped.

Safe to re-run: every insert is skipped if an equivalent row already
exists (matched by name, which is fixed per provider - see LEGACY_NAME).

Usage:
    python scripts/backfill_llm_model_access.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.company import Company
from app.models.user import User, ROLE_ADMIN
from app.models.model_config import ModelConfiguration
from app.models.resource_mapping import ResourceMapping

# provider -> (display name, env vars needed -> ModelConfiguration kwargs).
# settings.custom_key/base_url matches the shape saveModel() in index.html
# already writes for a manually-configured model.
LEGACY_PROVIDERS = [
    {
        'name': 'Legacy OpenAI (env)',
        'provider': 'OpenAI',
        'model': 'api://gpt-4o-mini',
        'api_key_env': 'OPENAI_API_KEY',
    },
    {
        'name': 'Legacy Anthropic (env)',
        'provider': 'Anthropic',
        'model': 'api://claude-sonnet-5',
        'api_key_env': 'ANTHROPIC_API_KEY',
    },
    {
        'name': 'Legacy Azure OpenAI (env)',
        'provider': 'Azure OpenAI',
        'model': 'api://gpt-4o',
        'api_key_env': 'AZURE_OPENAI_KEY',
        'base_url_env': 'AZURE_OPENAI_ENDPOINT',
    },
]


def _get_or_create_configuration(name, provider, model, api_key, base_url, company_code, owner_user_id):
    # Individual accounts all have company_code=None, so a shared company
    # configuration is matched by (name, company_code) but a private one
    # must also be scoped to its owner - otherwise every individual user
    # would be matched to the first one ever created.
    query = ModelConfiguration.query.filter_by(name=name, company_code=company_code)
    if company_code is None:
        query = query.filter_by(user_id=owner_user_id)
    existing = query.first()
    if existing:
        return existing, False

    config = ModelConfiguration(
        name=name,
        provider=provider,
        model=model,
        user_id=owner_user_id,
        company_code=company_code,
        settings={
            'custom_key': api_key or None,
            'base_url': base_url or None,
            'company_code': company_code,
            'seeded_legacy_env': True,
        },
    )
    db.session.add(config)
    db.session.flush()
    return config, True


def _get_or_create_grant(company_code, model_configuration_id, user_id, granted_by_user_id):
    existing = ResourceMapping.query.filter_by(
        resource_type='llm', resource_id=model_configuration_id, user_id=user_id
    ).first()
    if existing:
        return False
    db.session.add(ResourceMapping(
        company_code=company_code,
        resource_type='llm',
        resource_id=model_configuration_id,
        user_id=user_id,
        granted_by_user_id=granted_by_user_id,
        daily_budget=None,  # unlimited - matches today's uncapped env-var behavior
    ))
    return True


def backfill():
    configured_providers = []
    for cfg in LEGACY_PROVIDERS:
        api_key = os.getenv(cfg['api_key_env'])
        base_url = os.getenv(cfg.get('base_url_env', '')) if cfg.get('base_url_env') else None
        if api_key:
            configured_providers.append({**cfg, 'api_key': api_key, 'base_url': base_url})

    if not configured_providers:
        print('No legacy provider env vars are set (OPENAI_API_KEY / ANTHROPIC_API_KEY / '
              'AZURE_OPENAI_KEY) - nothing to backfill.')
        return

    configs_created = 0
    grants_created = 0

    # Companies: one shared configuration per provider, owned by the
    # company's first admin, granted to every active user of that company.
    for company in Company.query.all():
        admin = User.query.filter_by(company_code=company.company_code, role=ROLE_ADMIN).order_by(User.id).first()
        if not admin:
            print(f"Skipping company {company.company_code}: no admin user found.")
            continue

        users = User.query.filter_by(company_code=company.company_code, status='active').all()
        if not users:
            continue

        for cfg in configured_providers:
            config, created = _get_or_create_configuration(
                name=cfg['name'], provider=cfg['provider'], model=cfg['model'],
                api_key=cfg['api_key'], base_url=cfg.get('base_url'),
                company_code=company.company_code, owner_user_id=admin.id,
            )
            configs_created += int(created)

            for user in users:
                grants_created += int(_get_or_create_grant(
                    company_code=company.company_code, model_configuration_id=config.id,
                    user_id=user.id, granted_by_user_id=admin.id,
                ))

    # Individual accounts (company_code IS NULL): one private configuration
    # per user per provider - no grant needed, they own it outright.
    for user in User.query.filter_by(company_code=None, status='active').all():
        for cfg in configured_providers:
            _, created = _get_or_create_configuration(
                name=cfg['name'], provider=cfg['provider'], model=cfg['model'],
                api_key=cfg['api_key'], base_url=cfg.get('base_url'),
                company_code=None, owner_user_id=user.id,
            )
            configs_created += int(created)

    db.session.commit()
    print(f"Backfill complete: {configs_created} Model Configuration(s) created, "
          f"{grants_created} Resource Mapping grant(s) created.")


if __name__ == '__main__':
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    with app.app_context():
        backfill()
