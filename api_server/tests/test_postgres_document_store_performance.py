from __future__ import annotations

import unittest

from app.repositories.postgres import document_store


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, parameters=()) -> None:
        sql = str(query)
        values = tuple(parameters)
        if sql.count("%s") != len(values):
            raise AssertionError(f"Placeholder mismatch: {sql.count('%s')} != {len(values)}")
        self.calls.append((sql, values))

    def fetchall(self):
        return [("accepted", 4), ("rejected", 2)]


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor

    def commit(self) -> None:
        self.commits += 1


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connection(self):
        return self._connection


class PostgresDocumentStorePerformanceTests(unittest.TestCase):
    def test_merge_upsert_is_one_atomic_database_statement(self) -> None:
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        original_pool = document_store.get_postgres_pool
        document_store.get_postgres_pool = lambda: FakePool(connection)  # type: ignore[assignment]
        try:
            document_store.PostgresDocumentDatabase().collection("userSettings").document(
                "00000000-0000-0000-0000-000000000001"
            ).set(
                {
                    "uid": "00000000-0000-0000-0000-000000000001",
                    "settings": {"autoSaveSession": True},
                },
                merge=True,
            )
        finally:
            document_store.get_postgres_pool = original_pool  # type: ignore[assignment]

        self.assertEqual(len(cursor.calls), 1)
        self.assertEqual(connection.commits, 1)
        sql = cursor.calls[0][0].lower()
        self.assertIn("on conflict (id) do update", sql)
        self.assertIn("payload = public.user_settings.payload || excluded.payload", sql)
        self.assertNotIn("select ", sql)

    def test_group_count_uses_one_grouped_query(self) -> None:
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        original_pool = document_store.get_postgres_pool
        document_store.get_postgres_pool = lambda: FakePool(connection)  # type: ignore[assignment]
        try:
            result = (
                document_store.PostgresDocumentDatabase()
                .collection("analysisFeedback")
                .where("uid", "==", "00000000-0000-0000-0000-000000000001")
                .group_count("action")
            )
        finally:
            document_store.get_postgres_pool = original_pool  # type: ignore[assignment]

        self.assertEqual(result, {"accepted": 4, "rejected": 2})
        self.assertEqual(len(cursor.calls), 1)
        self.assertIn("group by", cursor.calls[0][0].lower())


if __name__ == "__main__":
    unittest.main()
