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
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
import psycopg2.errors
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# pg_advisory_lock key held while one process synchronises the schema.
# Any fixed number works; it only has to be the same in every process.
SCHEMA_BOOTSTRAP_LOCK_KEY = 72_401_311


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
            try:
                cursor.execute(f'CREATE DATABASE "{db_name}"')
            except (psycopg2.errors.DuplicateDatabase, psycopg2.errors.UniqueViolation):
                # Another process starting at the same moment (web and
                # scheduler on a first `docker compose up`) created it
                # between the check and the CREATE - the outcome we wanted.
                print(f"[DB Bootstrap] Database '{db_name}' was just created by another process.")
        else:
            print(f"[DB Bootstrap] Database '{db_name}' already exists.")
    finally:
        cursor.close()
        conn.close()


def _maintenance_dsn(database_url):
    parsed = urlparse(database_url)
    return (f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:"
            f"{parsed.port or 5432}/postgres")


@contextmanager
def schema_bootstrap_lock(database_url):
    """
    Serialises schema synchronisation across processes sharing one Postgres
    server. Without it, web and scheduler starting together both ran
    db.create_all() on an empty database: one created the tables, the other
    failed with "duplicate key value violates unique constraint
    pg_type_typname_nsp_index" and skipped the rest of its sync. The second
    process now waits, then finds every table already there.

    The lock lives on the 'postgres' maintenance database, so every process
    contends for the same one whichever app database it targets. It is a
    session lock: released when the connection closes, even if the process
    dies mid-sync. No-op for SQLite. If the lock cannot be taken, the sync
    still runs unlocked - the old behaviour - rather than blocking startup.
    """
    if not urlparse(database_url).scheme.startswith('postgres'):
        yield
        return
    conn = None
    try:
        conn = psycopg2.connect(_maintenance_dsn(database_url), connect_timeout=10)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (SCHEMA_BOOTSTRAP_LOCK_KEY,))
            if not cursor.fetchone()[0]:
                print("[DB Bootstrap] Another process is synchronizing the schema - waiting for it...")
                cursor.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_BOOTSTRAP_LOCK_KEY,))
    except Exception as e:
        print(f"[DB Bootstrap] Could not take the schema lock ({e}); continuing without it.")
        if conn is not None:
            conn.close()
        conn = None
    try:
        yield
    finally:
        if conn is not None:
            conn.close()  # releases the advisory lock


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


def sync_missing_columns(db):
    """
    db.create_all() only creates tables that don't exist yet - it never
    ALTERs a table that's already there to add a column a model gained
    later. Without this, adding a column to a model (e.g. FileResource
    gaining `description`/`status`) breaks every INSERT/UPDATE against
    that table on any database that already had it from an earlier
    deploy, with a "column ... does not exist" error - the schema-lives-
    in-the-models approach documented at the top of this file only holds
    if new columns actually get added to tables that already exist.

    Purely additive: only ADDs a column that's missing from the live
    table, never drops, renames, or alters an existing one. Columns with
    a NOT NULL model default (e.g. FileResource.status) are added with a
    matching SQL DEFAULT so existing rows backfill instead of failing;
    everything else is added nullable regardless of the model, since a
    NOT NULL column with no way to backfill existing rows would fail the
    ALTER TABLE outright.
    """
    from sqlalchemy import inspect, text

    for bind_key, metadata in db.metadatas.items():
        engine = db.engines[bind_key]
        try:
            inspector = inspect(engine)
            existing_tables = set(inspector.get_table_names())
        except Exception as e:
            print(f"[DB Bootstrap] Could not inspect bind '{bind_key}': {e}")
            continue

        for table in metadata.tables.values():
            if table.name not in existing_tables:
                continue  # create_all() creates this one fresh, with every column

            try:
                existing_columns = {col['name'] for col in inspector.get_columns(table.name)}
            except Exception as e:
                print(f"[DB Bootstrap] Could not inspect columns of '{table.name}': {e}")
                continue

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                default_value = None
                if column.default is not None and getattr(column.default, 'is_scalar', False):
                    default_value = column.default.arg

                ddl_type = column.type.compile(dialect=engine.dialect)
                parts = [f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}']
                if isinstance(default_value, str):
                    parts.append("DEFAULT '{}'".format(default_value.replace("'", "''")))
                elif isinstance(default_value, bool):
                    parts.append(f"DEFAULT {'TRUE' if default_value else 'FALSE'}")
                elif isinstance(default_value, (int, float)):
                    parts.append(f"DEFAULT {default_value}")
                if default_value is not None and not column.nullable:
                    parts.append("NOT NULL")

                try:
                    with engine.begin() as conn:
                        conn.execute(text(" ".join(parts)))
                    print(f"[DB Bootstrap] Added missing column: {table.name}.{column.name}")
                except Exception as e:
                    print(f"[DB Bootstrap] Could not add column {table.name}.{column.name}: {e}")
                    continue

                # A column the model marks index=True (e.g. the scope/
                # chat_session_id pair every resource table filters on - see
                # app/models/resource_scope.py) gets its index too, the same
                # one create_all() would have built on a fresh table.
                if column.index:
                    index_name = f"ix_{table.name}_{column.name}"
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(
                                f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table.name}" ("{column.name}")'
                            ))
                    except Exception as e:
                        print(f"[DB Bootstrap] Could not index {table.name}.{column.name}: {e}")


def drop_removed_tables(db, table_names):
    """
    Explicit, named cleanup for tables whose model was deleted outright
    (as opposed to a column being removed from a model that's still
    around, which this deliberately does NOT do - see sync_missing_columns'
    docstring on why column drops are never automatic). db.create_all()
    only ever adds tables; a table dropped from the models otherwise sits
    there forever as dead weight. Tries every bind's engine for each name
    since a given table only exists in one of them - a DROP against a
    bind that never had it is just a harmless no-op.

    router_configs is the first (and so far only) use of this: it was a
    per-user cache of the AI router's config, replaced by computing that
    config live on every request straight from DatabaseConnection/
    ApiConnector/FileResource - see automated_metamind.generate_router_
    config(). Those tables are the single source of truth for MetaMind
    data now; nothing should live in a separate cache table again.
    """
    from sqlalchemy import text

    for bind_key, engine in db.engines.items():
        for table_name in table_names:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
            except Exception as e:
                print(f"[DB Bootstrap] Could not drop '{table_name}' on bind '{bind_key}': {e}")
