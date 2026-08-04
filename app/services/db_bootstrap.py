"""
Database Bootstrap
Creates the app's logical Postgres databases (if missing) and their tables.

Replaces the old api_db__init__.py / chat_db__init__.py / auth_db__init__.py,
which each hand-rolled CREATE DATABASE + CREATE TABLE SQL for one database
apiece (with inconsistent defaults and no shared code). Table creation is now
driven entirely by the SQLAlchemy models via db.create_all(bind_key=...), so
schema lives in one place - the models - instead of being duplicated as raw
SQL strings here.
"""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from urllib.parse import urlparse


def _create_postgres_database_if_missing(database_url):
    """
    Connects to the 'postgres' maintenance database on the same server and
    creates the target database if it doesn't exist yet. No-op for SQLite
    URLs (the file is created automatically on first connection).
    """
    parsed = urlparse(database_url)
    if not parsed.scheme.startswith('postgres'):
        return

    db_name = parsed.path.lstrip('/')
    maintenance_dsn = f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"

    conn = psycopg2.connect(maintenance_dsn)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if not cursor.fetchone():
            print(f"[DB Bootstrap] Database '{db_name}' not found - creating it.")
            cursor.execute(f'CREATE DATABASE "{db_name}"')
        else:
            print(f"[DB Bootstrap] Database '{db_name}' already exists.")
    finally:
        cursor.close()
        conn.close()


def bootstrap_databases(bind_urls):
    """
    bind_urls: dict of {bind_key: database_url} - e.g. app.config['SQLALCHEMY_BINDS'].
    Creates every Postgres database referenced that doesn't exist yet.
    Table creation happens separately via db.create_all(), once all models
    are registered with SQLAlchemy (see create_app() in app/__init__.py).
    """
    for bind_key, url in bind_urls.items():
        try:
            _create_postgres_database_if_missing(url)
        except Exception as e:
            print(f"[DB Bootstrap] Error creating database for bind '{bind_key}': {e}")
