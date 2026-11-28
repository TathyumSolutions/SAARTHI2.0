"""
Two processes starting together (web and scheduler on a first
`docker compose up`) used to race on an empty Postgres server:
CREATE DATABASE failed with "duplicate key ... pg_database_datname_index"
and db.create_all() with "duplicate key ... pg_type_typname_nsp_index",
which skipped the rest of that process's schema sync.
"""
import os
import sys
import threading
import time

import psycopg2
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.db_bootstrap import schema_bootstrap_lock

PG_URL = os.getenv("TEST_POSTGRES_URL", "postgresql://saarthi:password@localhost:5432/postgres")


def _postgres_available():
    try:
        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


def test_lock_is_a_no_op_for_sqlite():
    with schema_bootstrap_lock("sqlite:///whatever.db"):
        pass


def test_lock_does_not_block_startup_when_postgres_is_unreachable():
    with schema_bootstrap_lock("postgresql://u:p@127.0.0.1:1/x"):
        pass


@pytest.mark.skipif(not _postgres_available(), reason="no Postgres server for the concurrency test")
def test_second_process_waits_for_the_first():
    events = []

    def worker(name, hold):
        with schema_bootstrap_lock(PG_URL):
            events.append(f"{name} in")
            time.sleep(hold)
            events.append(f"{name} out")

    first = threading.Thread(target=worker, args=("a", 1.0))
    first.start()
    time.sleep(0.3)
    second = threading.Thread(target=worker, args=("b", 0))
    second.start()
    first.join()
    second.join()
    assert events == ["a in", "a out", "b in", "b out"]
