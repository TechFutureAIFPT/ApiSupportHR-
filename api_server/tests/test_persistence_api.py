from __future__ import annotations

import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.deps import get_optional_current_user
from app.main import api_app
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser


class FakeDocumentSnapshot:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id
        self.reference = FakeDocumentReference(collection, doc_id)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._collection.store.get(self.id, {}))


class FakeDocumentReference:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        current = deepcopy(self._collection.store.get(self.id, {})) if merge else {}
        current.update(deepcopy(payload))
        self._collection.store[self.id] = current

    def delete(self) -> None:
        self._collection.store.pop(self.id, None)


class FakeQuery:
    def __init__(self, collection: "FakeCollection", field_name: str, expected_value: Any):
        self._collection = collection
        self._field_name = field_name
        self._expected_value = expected_value

    def stream(self) -> list[FakeDocumentSnapshot]:
        return [
            FakeDocumentSnapshot(self._collection, doc_id)
            for doc_id, payload in self._collection.store.items()
            if payload.get(self._field_name) == self._expected_value
        ]


class FakeCollection:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self.next_id = 1

    def document(self, doc_id: str | None = None) -> FakeDocumentReference:
        if doc_id is None:
            doc_id = f"doc-{self.next_id}"
            self.next_id += 1
        return FakeDocumentReference(self, doc_id)

    def where(self, field_name: str, op: str, expected_value: Any) -> FakeQuery:
        if op != "==":
            raise NotImplementedError("FakeCollection only supports equality filters.")
        return FakeQuery(self, field_name, expected_value)


class PersistenceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.fake_mobile_jd_history = FakeCollection()
        self.original_mobile_jd_history = repo.mobile_jd_history
        self.original_server_timestamp = repo.server_timestamp

        repo.mobile_jd_history = lambda: self.fake_mobile_jd_history  # type: ignore[assignment]
        repo.server_timestamp = lambda: datetime.now(timezone.utc)  # type: ignore[assignment]
        api_app.dependency_overrides[get_optional_current_user] = lambda: AuthenticatedUser(
            uid="user-123",
            email="hr@example.com",
            display_name="HR Tester",
            photo_url=None,
        )

    def tearDown(self) -> None:
        repo.mobile_jd_history = self.original_mobile_jd_history  # type: ignore[assignment]
        repo.server_timestamp = self.original_server_timestamp  # type: ignore[assignment]
        api_app.dependency_overrides.clear()
        self.client.close()

    def test_mobile_jd_standardize_persists_for_authenticated_user(self) -> None:
        ai_payload = {
            "score": 88,
            "missingSections": [],
            "weakPoints": [],
            "suggestions": [],
            "normalizedJD": {
                "title": "Backend Developer",
                "responsibilities": ["Build APIs"],
                "requirements": ["Python"],
                "benefits": [],
            },
        }

        with patch("app.services.mobile_jd.standardizer_service.generate_content", return_value=json.dumps(ai_payload)):
            response = self.client.post(
                "/api/mobile/jd/standardize",
                json={
                    "jdText": "Backend Developer\nBuild APIs with Python.",
                    "targetPlatform": "generic",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["savedRecordId"], "doc-1")
        stored = self.fake_mobile_jd_history.store["doc-1"]
        self.assertEqual(stored["uid"], "user-123")
        self.assertEqual(stored["artifactType"], "mobile_jd_standardization")
        self.assertEqual(stored["targetPlatform"], "generic")
        self.assertEqual(stored["response"]["score"], 88)


if __name__ == "__main__":
    unittest.main()
