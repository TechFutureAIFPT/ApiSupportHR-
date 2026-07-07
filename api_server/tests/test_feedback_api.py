from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.account.history import router as history_router
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser


api_app = FastAPI()
api_app.include_router(history_router, prefix="/api/account")


class FakeDocumentSnapshot:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id
        self.reference = FakeDocumentReference(collection, doc_id)

    @property
    def exists(self) -> bool:
        return self.id in self._collection.store

    def to_dict(self) -> dict[str, Any]:
        data = self._collection.store.get(self.id)
        return deepcopy(data) if data is not None else {}


class FakeDocumentReference:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def get(self) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self._collection, self.id)

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
        snapshots: list[FakeDocumentSnapshot] = []
        for doc_id, payload in self._collection.store.items():
            if payload.get(self._field_name) == self._expected_value:
                snapshots.append(FakeDocumentSnapshot(self._collection, doc_id))
        return snapshots


class FakeCollection:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def document(self, doc_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self, doc_id)

    def where(self, field_name: str, op: str, expected_value: Any) -> FakeQuery:
        if op != "==":
            raise NotImplementedError("FakeCollection only supports equality filters.")
        return FakeQuery(self, field_name, expected_value)


class FeedbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.fake_feedback = FakeCollection()
        self.original_analysis_feedback = repo.analysis_feedback
        self.original_server_timestamp = repo.server_timestamp

        repo.analysis_feedback = lambda: self.fake_feedback  # type: ignore[assignment]
        repo.server_timestamp = lambda: datetime.now(timezone.utc)  # type: ignore[assignment]
        api_app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            uid="user-123",
            email="hr@example.com",
            display_name="HR Tester",
            photo_url=None,
        )

    def tearDown(self) -> None:
        repo.analysis_feedback = self.original_analysis_feedback  # type: ignore[assignment]
        repo.server_timestamp = self.original_server_timestamp  # type: ignore[assignment]
        api_app.dependency_overrides.clear()
        self.client.close()

    def test_feedback_crud_and_stats(self) -> None:
        payload = {
            "syncHistoryId": "sync-001",
            "candidateId": "cand-001",
            "candidateName": "Nguyen Van A",
            "fileName": "nguyen-van-a.pdf",
            "jobPosition": "Backend Developer",
            "action": "shortlist",
            "aiScore": 81,
            "finalScore": 61,
            "isReusableGuidance": True,
            "rank": "A",
            "reason": "Phu hop JD",
            "notes": "Moi phong van",
            "promptKey": "cv_analysis/analyze_entries",
            "promptVersion": "v1",
            "modelVersion": "gemini-flash-latest",
            "metadata": {"source": "ui-results"},
        }

        create_response = self.client.post("/api/account/history/feedback", json=payload)
        self.assertEqual(create_response.status_code, 200, create_response.text)
        created = create_response.json()
        self.assertEqual(created["uid"], "user-123")
        self.assertEqual(created["action"], "shortlist")
        self.assertEqual(created["candidateId"], "cand-001")
        self.assertEqual(created["promptVersion"], "v1")
        self.assertTrue(created["isReusableGuidance"])
        self.assertEqual(created["severity"], "high")
        feedback_id = created["id"]
        stored = self.fake_feedback.store[feedback_id]
        self.assertEqual(stored["id"], feedback_id)
        self.assertEqual(stored["uid"], "user-123")
        self.assertEqual(stored["metadata"]["feedbackScope"], "reusable-guidance")
        self.assertEqual(stored["metadata"]["scoreDifference"], -20.0)

        list_response = self.client.get("/api/account/history/feedback", params={"sync_history_id": "sync-001"})
        self.assertEqual(list_response.status_code, 200, list_response.text)
        listed = list_response.json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], feedback_id)

        update_response = self.client.post(
            "/api/account/history/feedback",
            json={
                **payload,
                "action": "hire",
                "isReusableGuidance": False,
                "finalScore": 72,
                "notes": "Da duoc nhan",
            },
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        updated = update_response.json()
        self.assertEqual(updated["id"], feedback_id)
        self.assertEqual(updated["action"], "hire")
        self.assertEqual(updated["notes"], "Da duoc nhan")
        self.assertFalse(updated["isReusableGuidance"])
        self.assertEqual(updated["severity"], "medium")

        stats_response = self.client.get("/api/account/history/feedback/stats", params={"sync_history_id": "sync-001"})
        self.assertEqual(stats_response.status_code, 200, stats_response.text)
        stats = stats_response.json()
        self.assertEqual(stats["totalFeedback"], 1)
        self.assertEqual(stats["actionsCount"]["hire"], 1)
        self.assertEqual(stats["positiveCount"], 1)
        self.assertEqual(stats["negativeCount"], 0)

        delete_response = self.client.delete(f"/api/account/history/feedback/{feedback_id}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        self.assertTrue(delete_response.json()["ok"])

        list_after_delete = self.client.get("/api/account/history/feedback", params={"sync_history_id": "sync-001"})
        self.assertEqual(list_after_delete.status_code, 200, list_after_delete.text)
        self.assertEqual(list_after_delete.json(), [])


if __name__ == "__main__":
    unittest.main()
