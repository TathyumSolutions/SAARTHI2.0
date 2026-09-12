"""
One-time backfill for the LLM Connections feature.

Before this feature, every LLM call in the app authenticated with the
global OPENAI_API_KEY / ANTHROPIC_API_KEY / AZURE_OPENAI_KEY env vars
(see config/config.py). Now that access is admin-granted per user (like
DatabaseConnection/ApiConnector via Resource Mapping), existing users need
an equivalent LLMConnection + grant so nothing regresses on cutover:

  1. For each configured provider env var, create one shared LLMConnection
     per company (company_code set, created_by_user_id = that company's
     first admin) - or one private LLMConnection per individual account
     (company_code IS NULL).
  2. Grant every existing user in a company a Resource Mapping
     (resource_type='llm') to that company's legacy connection(s), with
     daily_budget=NULL (unlimited) so existing usage isn't newly capped.

Safe to re-run: every insert is skipped if an equivalent row already
exists (matched by name, which is fixed per provider - see LEGACY_NAME).

Usage:
    python scripts/backfill_llm_connections.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.company import Company
from app.models.user import User, ROLE_ADMIN
from app.models.llm_connection import LLMConnection
from app.models.resource_mapping import ResourceMapping
from app.utils.crypto import encrypt

# provider -> (display name, env vars needed -> LLMConnection kwargs)
LEGACY_PROVIDERS = [
    {
        'name': 'Legacy OpenAI (env)',
        'provider': 'openai',
        'model': 'gpt-4o-mini',
        'api_key_env': 'OPENAI_API_KEY',
    },
    {
        'name': 'Legacy Anthropic (env)',
        'provider': 'anthropic',
        'model': 'claude-sonnet-5',
        'api_key_env': 'ANTHROPIC_API_KEY',
    },
    {
        'name': 'Legacy Azure OpenAI (env)',
        'provider': 'azure_openai',
        'model': 'gpt-4o',
        'api_key_env': 'AZURE_OPENAI_KEY',
        'base_url_env': 'AZURE_OPENAI_ENDPOINT',
    },
]


def _get_or_create_connection(name, provider, model, api_key, base_url, company_code, created_by_user_id):
    # Individual accounts all have company_code=None, so a shared company
    # connection is matched by (name, company_code) but a private one must
    # also be scoped to its owner - otherwise every individual user would
    # be matched to the first one ever created.
    query = LLMConnection.query.filter_by(name=name, company_code=company_code)
    if company_code is None:
        query = query.filter_by(created_by_user_id=created_by_user_id)
    existing = query.first()
    if existing:
        return existing, False
    connection = LLMConnection(
        name=name,
        provider=provider,
        model=model,
        api_key=encrypt(api_key) if api_key else None,
        api_base_url=base_url or None,
        description='Auto-created by scripts/backfill_llm_connections.py to preserve pre-existing env-var-based LLM access.',
        company_code=company_code,
        created_by_user_id=created_by_user_id,
        status='active',
    )
    db.session.add(connection)
    db.session.flush()
    return connection, True


def _get_or_create_grant(company_code, connection_id, user_id, granted_by_user_id):
    existing = ResourceMapping.query.filter_by(
        resource_type='llm', resource_id=connection_id, user_id=user_id
    ).first()
    if existing:
        return False
    db.session.add(ResourceMapping(
        company_code=company_code,
        resource_type='llm',
        resource_id=connection_id,
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

    connections_created = 0
    grants_created = 0

    # Companies: one shared connection per provider, owned by the company's
    # first admin, granted to every active user of that company.
    for company in Company.query.all():
        admin = User.query.filter_by(company_code=company.company_code, role=ROLE_ADMIN).order_by(User.id).first()
        if not admin:
            print(f"Skipping company {company.company_code}: no admin user found.")
            continue

        users = User.query.filter_by(company_code=company.company_code, status='active').all()
        if not users:
            continue

        for cfg in configured_providers:
            connection, created = _get_or_create_connection(
                name=cfg['name'], provider=cfg['provider'], model=cfg['model'],
                api_key=cfg['api_key'], base_url=cfg.get('base_url'),
                company_code=company.company_code, created_by_user_id=admin.id,
            )
            connections_created += int(created)

            for user in users:
                grants_created += int(_get_or_create_grant(
                    company_code=company.company_code, connection_id=connection.id,
                    user_id=user.id, granted_by_user_id=admin.id,
                ))

    # Individual accounts (company_code IS NULL): one private connection per
    # user per provider - no grant needed, they own it outright.
    for user in User.query.filter_by(company_code=None, status='active').all():
        for cfg in configured_providers:
            _, created = _get_or_create_connection(
                name=cfg['name'], provider=cfg['provider'], model=cfg['model'],
                api_key=cfg['api_key'], base_url=cfg.get('base_url'),
                company_code=None, created_by_user_id=user.id,
            )
            connections_created += int(created)

    db.session.commit()
    print(f"Backfill complete: {connections_created} LLM connection(s) created, "
          f"{grants_created} Resource Mapping grant(s) created.")


if __name__ == '__main__':
    app = create_app(os.getenv('FLASK_ENV', 'development'))
    with app.app_context():
        backfill()
