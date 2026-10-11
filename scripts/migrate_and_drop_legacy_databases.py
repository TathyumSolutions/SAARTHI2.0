"""
One-time cleanup of the legacy Postgres databases.

The app now uses only three databases (saarthi_core_db,
saarthi_resources_db, saarthi_workspace_db - see config/config.py) plus the
`postgres` maintenance database for bootstrapping. Older deploys left four
more behind on the server:

  saarthi_auth_db   users              -> saarthi_core_db.users
  saarthi_chats_db  chat_sessions      -> saarthi_workspace_db.chat_sessions
  saarthi_api_db    registered_tools   -> saarthi_resources_db.api_connectors
  saarthi_db        (no app tables)    -> nothing to move

This script copies any legacy rows that are not already in the active
tables, then (with --drop) drops the legacy databases. `postgres` is never
touched.

  * users are matched by email (case-insensitive); existing core users are
    never modified. Copied users keep their password hash, name, role and
    email-verification state. company_code is kept only if that company
    exists in saarthi_core_db.companies, otherwise the user becomes an
    individual account (company_code NULL).
  * chat_sessions and registered_tools had no owner in the legacy schema,
    but the active tables require one - pass --owner-email to assign them
    to an existing core user (and that user's company). Without it they
    are reported and left uncopied.

Default is a dry run that only reports what it would do.

Usage:
    python scripts/migrate_and_drop_legacy_databases.py                 # dry run
    python scripts/migrate_and_drop_legacy_databases.py --migrate       # copy rows
    python scripts/migrate_and_drop_legacy_databases.py --migrate --owner-email admin@acme.com --drop
"""
import argparse
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import RealDictCursor

from app import create_app, db
from app.models.company import Company
from app.models.user import User, ROLE_USER, STATUS_ACTIVE
from app.models.chat import ChatSession
from app.models.api_connector import ApiConnector

LEGACY_DATABASES = ['saarthi_auth_db', 'saarthi_chats_db', 'saarthi_api_db', 'saarthi_db']


def _dsn(base_url, db_name):
    p = urlparse(base_url)
    return f"postgresql://{p.username}:{p.password}@{p.hostname}:{p.port or 5432}/{db_name}"


def _database_exists(base_url, db_name):
    conn = psycopg2.connect(_dsn(base_url, 'postgres'))
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def _read_table(base_url, db_name, table):
    """Rows of `table` in `db_name`, or [] if the database/table is missing."""
    if not _database_exists(base_url, db_name):
        return []
    conn = psycopg2.connect(_dsn(base_url, db_name))
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (f'public.{table}',))
        if not cur.fetchone()['present']:
            return []
        cur.execute(f'SELECT * FROM "{table}"')
        return cur.fetchall()
    finally:
        conn.close()


def migrate_users(base_url, apply):
    rows = _read_table(base_url, 'saarthi_auth_db', 'users')
    existing = {e.lower() for (e,) in db.session.query(User.email).all()}
    known_companies = {c for (c,) in db.session.query(Company.company_code).all()}
    copied = 0
    for row in rows:
        email = str(row.get('email') or '').strip()
        if not email or email.lower() in existing or not row.get('password_hash'):
            continue
        company_code = row.get('company_code') or None
        if company_code not in known_companies:
            company_code = None
        role = str(row.get('role') or ROLE_USER).strip().lower()
        if company_code is None:
            role = 'admin'  # individual accounts are always admin over themselves
        if apply:
            db.session.add(User(
                name=row.get('name') or email,
                email=email,
                password_hash=row['password_hash'],
                company_code=company_code,
                role=role,
                status=STATUS_ACTIVE,
                email_verified=bool(row.get('email_verified', True)),
                created_at=row.get('created_at'),
            ))
        existing.add(email.lower())
        copied += 1
    print(f"[users] legacy rows: {len(rows)}, to copy into saarthi_core_db.users: {copied}")
    return copied


def migrate_chat_sessions(base_url, owner, apply):
    """Returns how many legacy rows were left uncopied (no owner given)."""
    rows = _read_table(base_url, 'saarthi_chats_db', 'chat_sessions')
    existing = {s for (s,) in db.session.query(ChatSession.session_id).all()}
    pending = [r for r in rows if r.get('session_id') and r['session_id'] not in existing]
    print(f"[chat_sessions] legacy rows: {len(rows)}, not yet in saarthi_workspace_db: {len(pending)}")
    if pending and owner is None:
        print("  skipped - pass --owner-email to assign them to a user")
        return len(pending)
    if apply:
        for r in pending:
            db.session.add(ChatSession(
                session_id=r['session_id'],
                title=r.get('title') or 'Untitled',
                chat_history=r.get('chat_history') or '',
                user_id=owner.id,
                company_code=owner.company_code,
                updated_at=r.get('updated_at'),
            ))
    return 0


def migrate_registered_tools(base_url, owner, apply):
    """Returns how many legacy rows were left uncopied (no owner given)."""
    rows = _read_table(base_url, 'saarthi_api_db', 'registered_tools')
    existing = {n for (n,) in db.session.query(ApiConnector.integration_name).all()}
    pending = [r for r in rows if r.get('integration_name') and r['integration_name'] not in existing]
    print(f"[registered_tools] legacy rows: {len(rows)}, not yet in saarthi_resources_db.api_connectors: {len(pending)}")
    if pending and owner is None:
        print("  skipped - pass --owner-email to assign them to a user")
        return len(pending)
    if apply:
        for r in pending:
            db.session.add(ApiConnector(
                integration_name=r['integration_name'],
                base_url=r['base_url'],
                endpoint=r['endpoint'],
                method=r.get('method') or 'GET',
                auth_type=r.get('auth_type') or 'No Auth',
                api_token=r.get('api_token'),
                api_description=r.get('api_description') or '',
                status=r.get('status') or 'Active',
                created_by_user_id=owner.id,
                company_code=owner.company_code,
                created_at=r.get('created_at'),
            ))
    return 0


def drop_legacy_databases(base_url):
    conn = psycopg2.connect(_dsn(base_url, 'postgres'))
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        cur = conn.cursor()
        for name in LEGACY_DATABASES:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if not cur.fetchone():
                print(f"[drop] {name}: not present")
                continue
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
            cur.execute(f'DROP DATABASE "{name}"')
            print(f"[drop] {name}: dropped")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--migrate', action='store_true', help='copy legacy rows into the active databases')
    parser.add_argument('--owner-email', help='core user who will own copied chat sessions / API connectors')
    parser.add_argument('--drop', action='store_true', help='drop the legacy databases after migrating')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        base_url = app.config['SQLALCHEMY_DATABASE_URI']
        if not urlparse(base_url).scheme.startswith('postgres'):
            print("Not a Postgres deployment - no legacy databases to clean up.")
            return

        owner = None
        if args.owner_email:
            owner = User.query.filter(db.func.lower(User.email) == args.owner_email.lower()).first()
            if owner is None:
                sys.exit(f"No user with email {args.owner_email} in saarthi_core_db.users")

        migrate_users(base_url, args.migrate)
        uncopied = migrate_chat_sessions(base_url, owner, args.migrate)
        uncopied += migrate_registered_tools(base_url, owner, args.migrate)

        if args.migrate:
            db.session.commit()
            print("Migration committed.")
        else:
            print("Dry run - nothing written. Re-run with --migrate to copy rows.")

        if args.drop:
            if not args.migrate:
                sys.exit("--drop requires --migrate so no legacy data is lost.")
            if uncopied:
                sys.exit(f"Not dropping: {uncopied} legacy row(s) were left uncopied - pass --owner-email.")
            drop_legacy_databases(base_url)


if __name__ == '__main__':
    main()
