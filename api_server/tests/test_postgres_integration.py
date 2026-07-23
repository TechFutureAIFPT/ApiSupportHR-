from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.integrations import postgres


class PostgresIntegrationTests(unittest.TestCase):
    def tearDown(self) -> None:
        postgres.get_postgres_pool.cache_clear()

    def test_pool_uses_runtime_settings(self) -> None:
        settings = SimpleNamespace(
            database_url="postgresql://user:password@db.example.test:5432/postgres",
            postgres_pool_min_size=1,
            postgres_pool_max_size=5,
            postgres_pool_timeout_seconds=5.0,
            postgres_pool_max_waiting=10,
            postgres_pool_max_idle_seconds=300.0,
            postgres_pool_max_lifetime_seconds=1800.0,
            postgres_pool_reconnect_timeout_seconds=60.0,
            postgres_pool_workers=2,
            postgres_statement_timeout_ms=15000,
            postgres_idle_transaction_timeout_ms=30000,
        )

        with (
            patch.object(postgres, "get_settings", return_value=settings),
            patch("psycopg_pool.ConnectionPool") as pool_class,
        ):
            pool = postgres.get_postgres_pool()

        self.assertIs(pool, pool_class.return_value)
        self.assertEqual(
            pool_class.call_args.kwargs["conninfo"],
            settings.database_url,
        )


if __name__ == "__main__":
    unittest.main()
