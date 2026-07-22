from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_postgres_pool() -> Any:
    """Return the shared Supavisor-compatible psycopg connection pool."""
    try:
        from psycopg_pool import ConnectionPool
    except ModuleNotFoundError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("psycopg-pool is required for the Supabase runtime.") from error

    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the Supabase runtime.")
    return ConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=10,
        timeout=10,
        kwargs={"autocommit": False, "prepare_threshold": None},
        open=True,
    )


def postgres_ready() -> bool:
    try:
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                return cursor.fetchone() == (1,)
    except Exception:
        return False
