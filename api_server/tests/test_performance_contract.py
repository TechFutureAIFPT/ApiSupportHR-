from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.pagination import decode_cursor, encode_cursor, parse_field_selection
from app.core.config import get_settings
from app.main import api_app
from app.repositories.postgres import page_repository


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.parameters = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, parameters):
        self.query = str(query)
        self.parameters = list(parameters)
        self.assert_placeholder_count = self.query.count("%s") == len(self.parameters)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


class FakePool:
    def __init__(self, cursor):
        self._cursor = cursor

    def connection(self):
        return FakeConnection(self._cursor)


class PerformanceContractTests(unittest.TestCase):
    def test_cursor_round_trip_and_field_validation(self) -> None:
        token = encode_cursor("2026-07-22T10:00:00+00:00", "doc-1")
        decoded = decode_cursor(token)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(decoded.document_id, "doc-1")
        fields = parse_field_selection(
            "id,name,name",
            allowed_fields={"id", "name"},
            default_fields={"id"},
        )
        self.assertEqual(fields, ["id", "name"])

    def test_page_query_projects_json_fields_and_uses_keyset_cursor(self) -> None:
        rows = [
            ("doc-2", {"fileName": "two.pdf"}, "uploaded", datetime(2026, 7, 22, 10, tzinfo=timezone.utc)),
            ("doc-1", {"fileName": "one.pdf"}, "uploaded", datetime(2026, 7, 22, 9, tzinfo=timezone.utc)),
        ]
        fake_cursor = FakeCursor(rows)
        original_pool = page_repository.get_postgres_pool
        page_repository.get_postgres_pool = lambda: FakePool(fake_cursor)  # type: ignore[assignment]
        try:
            page = page_repository.paginate_owner_records(
                table_sources=(("uploaded_files", "uploaded"),),
                owner_id="00000000-0000-0000-0000-000000000001",
                page_size=1,
                fields=["id", "fileName"],
            )
        finally:
            page_repository.get_postgres_pool = original_pool  # type: ignore[assignment]

        self.assertNotIn("select *", fake_cursor.query.lower())
        self.assertTrue(fake_cursor.assert_placeholder_count)
        self.assertIn("jsonb_build_object", fake_cursor.query)
        self.assertIn("%s::text, payload -> %s::text", fake_cursor.query)
        self.assertIn("order by sort_at desc, id desc", fake_cursor.query.lower())
        self.assertTrue(page.has_more)
        self.assertIsNotNone(page.next_cursor)
        self.assertEqual(page.items, [{"id": "doc-2", "fileName": "two.pdf"}])

    def test_compression_pool_and_async_job_contracts_are_enabled(self) -> None:
        settings = get_settings()
        self.assertLessEqual(settings.postgres_pool_min_size, settings.postgres_pool_max_size)
        self.assertGreater(settings.postgres_pool_max_waiting, 0)
        self.assertLessEqual(settings.postgres_pool_timeout_seconds, 5.0)

        routes = {(route.path, tuple(sorted(route.methods or []))): route for route in api_app.routes}
        async_route = next(route for route in api_app.routes if getattr(route, "path", "") == "/api/analysis/jobs")
        self.assertEqual(getattr(async_route, "status_code", None), 202)
        vector_rebuild_route = next(
            route for route in api_app.routes
            if getattr(route, "path", "") == "/api/account/uploaded-files/vector-index/rebuild"
        )
        self.assertEqual(getattr(vector_rebuild_route, "status_code", None), 202)
        for path in ("/api/account/history/page", "/api/account/uploaded-files/page", "/api/account/jd-templates/page"):
            self.assertTrue(any(getattr(route, "path", "") == path for route in routes.values()))

        with TestClient(api_app) as client:
            response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        self.assertIn("accept-encoding", response.headers.get("vary", "").lower())


if __name__ == "__main__":
    unittest.main()
