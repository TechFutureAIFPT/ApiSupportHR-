from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import api_app
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser


class FakeDocumentSnapshot:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._collection.store.get(self.id, {}))


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

    def where(self, field_name: str, op: str, expected_value: Any) -> FakeQuery:
        if op != "==":
            raise NotImplementedError("FakeCollection only supports equality filters.")
        return FakeQuery(self, field_name, expected_value)


class MobileInboxApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.fake_cv_history = FakeCollection()
        self.fake_synced_history = FakeCollection()
        self.original_cv_history = repo.cv_history
        self.original_synced_history = repo.synced_history

        repo.cv_history = lambda: self.fake_cv_history  # type: ignore[assignment]
        repo.synced_history = lambda: self.fake_synced_history  # type: ignore[assignment]

    def tearDown(self) -> None:
        repo.cv_history = self.original_cv_history  # type: ignore[assignment]
        repo.synced_history = self.original_synced_history  # type: ignore[assignment]
        api_app.dependency_overrides.clear()
        self.client.close()

    def test_mobile_inbox_requires_auth(self) -> None:
        response = self.client.get("/api/account/mobile-inbox")
        self.assertIn(response.status_code, {401, 403})

    def test_mobile_inbox_returns_compact_payload(self) -> None:
        api_app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            uid="user-123",
            email="hr@example.com",
            display_name="HR Tester",
            photo_url=None,
        )
        details = [
            {
                "Tiêu chí": f"Tiêu chí {index}",
                "Điểm": "10/10",
                "Dẫn chứng": "x" * 900,
                "Công thức": "hidden",
            }
            for index in range(10)
        ]
        self.fake_cv_history.store["history-1"] = {
            "uid": "user-123",
            "userEmail": "hr@example.com",
            "jobPosition": "Backend Developer",
            "locationRequirement": "Hà Nội",
            "timestamp": 2000,
            "totalCandidates": 2,
            "analysisData": {"large": "should-not-ship"},
            "fullPayload": {
                "jdText": "JD " + ("long " * 1000),
                "jobPosition": "Backend Developer",
                "hardFilters": {"industry": "IT"},
                "candidates": [
                    {
                        "id": "cand-1",
                        "candidateName": "Nguyen Van A",
                        "fileName": "a.pdf",
                        "jobTitle": "Backend Developer",
                        "industry": "IT",
                        "experienceLevel": "Senior",
                        "detectedLocation": "Hà Nội",
                        "_cvText": "raw cv text",
                        "extractedText": "raw extracted text",
                        "status": "SUCCESS",
                        "analysis": {
                            "Tổng điểm": 88,
                            "Hạng": "A",
                            "Điểm mạnh CV": ["Python", "FastAPI"],
                            "Điểm yếu CV": ["Cần kiểm chứng quản lý team"],
                            "Câu hỏi phỏng vấn": ["Bạn debug production thế nào?"],
                            "Chi tiết": details,
                        },
                    }
                ],
            },
        }

        response = self.client.get("/api/account/mobile-inbox", params={"history_limit": 1, "candidate_limit": 1})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["history"]), 1)
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertIn("stats", payload)
        self.assertIn("revision", payload)
        self.assertIn("generatedAt", payload)

        history = payload["history"][0]
        candidate = payload["candidates"][0]
        self.assertNotIn("analysisData", history)
        self.assertLessEqual(len(history["fullPayload"]["jdText"]), 800)
        self.assertNotIn("_cvText", candidate["raw"])
        self.assertNotIn("extractedText", candidate["raw"])
        self.assertLessEqual(len(candidate["details"]), 6)
        self.assertLessEqual(len(candidate["details"][0]["Dẫn chứng"]), 420)


if __name__ == "__main__":
    unittest.main()
