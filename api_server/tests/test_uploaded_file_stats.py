from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import uploaded_file_service


class FakeDocument:
    def __init__(self, doc_id: str, payload: dict[str, Any]) -> None:
        self.id = doc_id
        self._payload = payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self._payload)


class FakeAggregation:
    def __init__(self, value: int) -> None:
        self.value = value

    def get(self):
        return [[SimpleNamespace(value=self.value)]]


class FakeQuery:
    def __init__(self, items: list[tuple[str, dict[str, Any]]]) -> None:
        self.items = items

    def where(self, field: str, op: str, value: Any):
        if op != "==":
            raise NotImplementedError
        return FakeQuery([(doc_id, payload) for doc_id, payload in self.items if payload.get(field) == value])

    def count(self):
        return FakeAggregation(len(self.items))

    def sum(self, field: str):
        return FakeAggregation(sum(int(payload.get(field) or 0) for _, payload in self.items))

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, count: int):
        return FakeQuery(self.items[:count])

    def stream(self):
        return [FakeDocument(doc_id, payload) for doc_id, payload in self.items]


class FakeCollection(FakeQuery):
    pass


class UploadedFileStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_uploaded_files = repo.uploaded_files
        self.user = AuthenticatedUser(uid="test-user", email="tester@example.com")

    def tearDown(self) -> None:
        repo.uploaded_files = self.original_uploaded_files  # type: ignore[assignment]

    def test_empty_collection_returns_zeroes(self) -> None:
        repo.uploaded_files = lambda: FakeCollection([])  # type: ignore[assignment]
        stats = uploaded_file_service.get_file_stats(self.user)

        self.assertEqual(stats["totalFiles"], 0)
        self.assertEqual(stats["totalCVs"], 0)
        self.assertEqual(stats["totalJDs"], 0)
        self.assertEqual(stats["totalSizeBytes"], 0)
        self.assertEqual(stats["recentFiles"], [])

    def test_aggregates_file_types_and_size(self) -> None:
        repo.uploaded_files = lambda: FakeCollection(
            [
                ("cv-1", {"uid": "test-user", "fileType": "cv", "fileSize": 120}),
                ("cv-2", {"uid": "test-user", "fileType": "cv", "fileSize": 80}),
                ("jd-1", {"uid": "test-user", "fileType": "jd", "fileSize": 50}),
                ("other", {"uid": "other-user", "fileType": "cv", "fileSize": 999}),
            ]
        )  # type: ignore[assignment]
        stats = uploaded_file_service.get_file_stats(self.user)

        self.assertEqual(stats["totalFiles"], 3)
        self.assertEqual(stats["totalCVs"], 2)
        self.assertEqual(stats["totalJDs"], 1)
        self.assertEqual(stats["totalSizeBytes"], 250)


if __name__ == "__main__":
    unittest.main()
