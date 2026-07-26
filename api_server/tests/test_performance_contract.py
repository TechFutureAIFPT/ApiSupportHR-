from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.pagination import decode_cursor, encode_cursor, parse_field_selection
from app.core.config import get_settings
from app.main import api_app
from app.repositories.firestore import page_repository


class FakeSnapshot:
    def __init__(self, document_id: str, payload: dict):
        self.id = document_id
        self._payload = payload

    def to_dict(self):
        return dict(self._payload)


class FakeCollection:
    def __init__(self, rows: list[FakeSnapshot], filters: list[tuple[str, str]] | None = None):
        self.rows = rows
        self.filters = list(filters or [])

    def where(self, field: str, operation: str, value: str):
        if operation != "==":
            raise NotImplementedError
        return FakeCollection(self.rows, [*self.filters, (field, value)])

    def stream(self):
        return [
            row
            for row in self.rows
            if all((row.to_dict() or {}).get(field) == value for field, value in self.filters)
        ]


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

    def test_firestore_page_projects_fields_and_uses_keyset_cursor(self) -> None:
        collection = FakeCollection(
            [
                FakeSnapshot(
                    "doc-2",
                    {
                        "uid": "user-1",
                        "fileName": "two.pdf",
                        "uploadedAt": datetime(2026, 7, 22, 10, tzinfo=timezone.utc),
                    },
                ),
                FakeSnapshot(
                    "doc-1",
                    {
                        "uid": "user-1",
                        "fileName": "one.pdf",
                        "uploadedAt": datetime(2026, 7, 22, 9, tzinfo=timezone.utc),
                    },
                ),
                FakeSnapshot(
                    "other-user",
                    {
                        "uid": "user-2",
                        "fileName": "hidden.pdf",
                        "uploadedAt": datetime(2026, 7, 22, 11, tzinfo=timezone.utc),
                    },
                ),
            ]
        )
        original = page_repository.COLLECTIONS["uploaded_files"]
        page_repository.COLLECTIONS["uploaded_files"] = (
            lambda: collection,
            ("lastAccessedAt", "uploadedAt", "updatedAt"),
        )
        try:
            first = page_repository.paginate_owner_records(
                table_sources=(("uploaded_files", "uploaded"),),
                owner_id="user-1",
                page_size=1,
                fields=["id", "fileName"],
            )
            second = page_repository.paginate_owner_records(
                table_sources=(("uploaded_files", "uploaded"),),
                owner_id="user-1",
                page_size=1,
                fields=["id", "fileName"],
                cursor=decode_cursor(first.next_cursor),
            )
        finally:
            page_repository.COLLECTIONS["uploaded_files"] = original

        self.assertTrue(first.has_more)
        self.assertIsNotNone(first.next_cursor)
        self.assertEqual(first.items, [{"id": "doc-2", "fileName": "two.pdf"}])
        self.assertFalse(second.has_more)
        self.assertEqual(second.items, [{"id": "doc-1", "fileName": "one.pdf"}])

    def test_compression_firebase_and_async_job_contracts_are_enabled(self) -> None:
        settings = get_settings()
        self.assertTrue(hasattr(settings, "firebase_project_id"))
        self.assertFalse(hasattr(settings, "database_url"))

        routes = {(route.path, tuple(sorted(route.methods or []))): route for route in api_app.routes}
        async_route = next(route for route in api_app.routes if getattr(route, "path", "") == "/api/analysis/jobs")
        self.assertEqual(getattr(async_route, "status_code", None), 202)
        vector_rebuild_route = next(
            route
            for route in api_app.routes
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
