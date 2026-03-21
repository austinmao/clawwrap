"""Connection manager for clawwrap Postgres access with pooling."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

import psycopg
import psycopg_pool

SCHEMA_NAME = "clawwrap"

_pool: psycopg_pool.ConnectionPool | None = None
_pool_lock = threading.Lock()

# Pool sizing constants
_MIN_SIZE = 1
_MAX_SIZE = 10


def _ensure_schema(conn: psycopg.Connection) -> None:
    """Create the clawwrap schema if it does not already exist."""
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")
    conn.commit()


def get_pool(db_url: str) -> psycopg_pool.ConnectionPool:
    """Return the singleton connection pool, creating it on first call.

    Thread-safe via a module-level lock.
    """
    global _pool  # noqa: PLW0603
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg_pool.ConnectionPool(
                conninfo=db_url,
                min_size=_MIN_SIZE,
                max_size=_MAX_SIZE,
                open=True,
            )
            # Initialise schema on first pool creation
            with _pool.connection() as conn:
                _ensure_schema(conn)
    return _pool


def close_pool() -> None:
    """Close and reset the singleton pool (used in tests and shutdown)."""
    global _pool  # noqa: PLW0603
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def get_connection(db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Context manager that yields a pooled psycopg connection.

    The schema search path is set to ``clawwrap`` on each borrowed connection
    so all queries can reference tables without the schema prefix.

    Usage::

        with get_connection(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    pool = get_pool(db_url)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {SCHEMA_NAME}")
        yield conn
