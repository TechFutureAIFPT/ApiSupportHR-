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
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
        timeout=max(0.1, settings.postgres_pool_timeout_seconds),
        max_waiting=settings.postgres_pool_max_waiting,
        max_idle=max(1.0, settings.postgres_pool_max_idle_seconds),
        max_lifetime=max(60.0, settings.postgres_pool_max_lifetime_seconds),
        reconnect_timeout=max(1.0, settings.postgres_pool_reconnect_timeout_seconds),
        num_workers=settings.postgres_pool_workers,
        check=ConnectionPool.check_connection,
        name="supporthr-postgres",
        kwargs={
            "autocommit": False,
            "prepare_threshold": None,
            "application_name": "supporthr-api",
            "options": (
                f"-c statement_timeout={settings.postgres_statement_timeout_ms} "
                f"-c idle_in_transaction_session_timeout={settings.postgres_idle_transaction_timeout_ms}"
            ),
        },
        open=True,
    )


def close_postgres_pool() -> None:
    """Close an initialized pool during graceful shutdown without creating one."""
    if get_postgres_pool.cache_info().currsize:
        get_postgres_pool().close()
        get_postgres_pool.cache_clear()


def postgres_pool_stats() -> dict[str, int]:
    if not get_postgres_pool.cache_info().currsize:
        return {}
    return {key: int(value) for key, value in get_postgres_pool().get_stats().items()}


def postgres_ready() -> bool:
    try:
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
                return cursor.fetchone() == (1,)
    except Exception:
        return False
