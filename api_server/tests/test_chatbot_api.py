from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.account.chatbot import router as chatbot_router
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import chatbot_copilot_service


api_app = FastAPI()
api_app.include_router(chatbot_router, prefix="/api/account")


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
        self._counter = 0

    def document(self, doc_id: str | None = None) -> FakeDocumentReference:
        if doc_id is None:
            self._counter += 1
            doc_id = f"doc-{self._counter}"
        return FakeDocumentReference(self, doc_id)

    def where(self, field_name: str, op: str, expected_value: Any) -> FakeQuery:
        if op != "==":
            raise NotImplementedError("FakeCollection only supports equality filters.")
        return FakeQuery(self, field_name, expected_value)


class ChatbotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.fake_chatbot_sessions = FakeCollection()
        self.original_chatbot_sessions = repo.chatbot_sessions
        self.original_create_document = repo.create_document
        self.original_server_timestamp = repo.server_timestamp
        self.original_generate_content = chatbot_copilot_service.gemini_service.generate_content

        repo.chatbot_sessions = lambda: self.fake_chatbot_sessions  # type: ignore[assignment]
        repo.create_document = lambda collection_ref: collection_ref.document()  # type: ignore[assignment]
        repo.server_timestamp = lambda: datetime.now(timezone.utc)  # type: ignore[assignment]
        api_app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            uid="user-123",
            email="hr@example.com",
            display_name="HR Tester",
            photo_url=None,
        )

    def tearDown(self) -> None:
        repo.chatbot_sessions = self.original_chatbot_sessions  # type: ignore[assignment]
        repo.create_document = self.original_create_document  # type: ignore[assignment]
        repo.server_timestamp = self.original_server_timestamp  # type: ignore[assignment]
        chatbot_copilot_service.gemini_service.generate_content = self.original_generate_content  # type: ignore[assignment]
        api_app.dependency_overrides.clear()
        self.client.close()

    def _candidate_briefs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "cand-001",
                "candidateName": "Nguyen Van A",
                "score": 84,
                "rank": "A",
                "headlineVerdict": "Ứng viên rất sát JD backend.",
                "topStrengths": ["Python backend", "Thiết kế API", "Kinh nghiệm production"],
                "topRisks": ["Cần xác minh English"],
                "matchedRequirements": ["FastAPI", "REST API"],
                "missingRequirements": ["Kubernetes"],
                "redFlags": [],
                "stageDecision": {
                    "status": "ready_to_advance",
                    "label": "Sẵn sàng chuyển vòng",
                    "reason": "Điểm cao và không có blocker lớn.",
                    "blockingReasons": [],
                },
                "interviewQuestions": ["Kể về hệ thống FastAPI lớn nhất bạn từng làm."],
            },
            {
                "id": "cand-002",
                "candidateName": "Tran Thi B",
                "score": 68,
                "rank": "B",
                "headlineVerdict": "Có nền tảng ổn nhưng còn thiếu một số yêu cầu.",
                "topStrengths": ["SQL tốt", "Tư duy hệ thống"],
                "topRisks": ["Thiếu FastAPI thực chiến"],
                "matchedRequirements": ["SQL"],
                "missingRequirements": ["FastAPI"],
                "redFlags": ["Thiếu dẫn chứng production"],
                "stageDecision": {
                    "status": "review",
                    "label": "Cần review thêm",
                    "reason": "Còn một vài khoảng trống kỹ thuật.",
                    "blockingReasons": ["Thiếu FastAPI thực chiến"],
                },
                "interviewQuestions": ["Bạn đã tối ưu truy vấn SQL như thế nào?"],
            },
        ]

    def _create_session(self) -> str:
        response = self.client.post(
            "/api/account/chatbot/sessions",
            json={
                "jobPosition": "Backend Developer",
                "totalCandidates": 2,
                "analysisContext": {
                    "analysisSessionId": "analysis-001",
                    "historyId": "history-001",
                    "syncHistoryId": "sync-001",
                    "jdHash": "jd-001",
                    "jobPosition": "Backend Developer",
                },
                "candidateBriefs": self._candidate_briefs(),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def test_create_session_and_reply_with_structured_payload(self) -> None:
        chatbot_copilot_service.gemini_service.generate_content = lambda *args, **kwargs: """{
          "responseText":"- Kết luận nhanh: Nguyen Van A nên được mời phỏng vấn.\\n- Bằng chứng: khớp FastAPI và API backend.\\n- Rủi ro: cần xác minh English.\\n- Bước tiếp theo: phỏng vấn xác minh kỹ thuật.",
          "suggestedCandidateIds":["cand-001"],
          "focusCandidateId":"cand-001",
          "candidateCards":[
            {
              "id":"cand-001",
              "candidateName":"Nguyen Van A",
              "score":84,
              "rank":"A",
              "headlineVerdict":"Ứng viên rất sát JD backend.",
              "topStrengths":["Python backend","Thiết kế API"],
              "topRisks":["Cần xác minh English"],
              "matchedRequirements":["FastAPI","REST API"],
              "missingRequirements":["Kubernetes"],
              "redFlags":[],
              "interviewQuestions":["Kể về hệ thống FastAPI lớn nhất bạn từng làm."],
              "recommendedAction":"Ưu tiên mời phỏng vấn",
              "focusLabel":"Ứng viên đang đào sâu",
              "stageDecision":{"status":"ready_to_advance","label":"Sẵn sàng chuyển vòng","reason":"Điểm cao và không có blocker lớn.","blockingReasons":[]}
            }
          ],
          "followUpQuestions":["Bạn muốn tôi tạo bộ câu hỏi phỏng vấn không?"],
          "suggestedActions":["Ưu tiên mời phỏng vấn"]
        }"""  # type: ignore[assignment]

        session_id = self._create_session()
        reply_response = self.client.post(
            f"/api/account/chatbot/sessions/{session_id}/reply",
            json={
                "message": "Ứng viên Nguyễn Văn A có nên phỏng vấn không?",
                "focusCandidateId": "cand-001",
                "selectedCandidateIds": ["cand-001"],
            },
        )
        self.assertEqual(reply_response.status_code, 200, reply_response.text)
        payload = reply_response.json()
        self.assertEqual(payload["sessionId"], session_id)
        self.assertEqual(payload["focusCandidateId"], "cand-001")
        self.assertEqual(payload["suggestedCandidateIds"], ["cand-001"])
        self.assertEqual(payload["assistantMessage"]["metadata"]["candidateCards"][0]["candidateName"], "Nguyen Van A")
        self.assertEqual(payload["assistantMessage"]["metadata"]["followUpQuestions"][0], "Bạn muốn tôi tạo bộ câu hỏi phỏng vấn không?")

        stored_session = self.fake_chatbot_sessions.store[session_id]
        self.assertEqual(stored_session["analysisContext"]["analysisSessionId"], "analysis-001")
        self.assertEqual(stored_session["lastFocusCandidateId"], "cand-001")
        self.assertEqual(stored_session["lastSuggestedCandidateIds"], ["cand-001"])
        self.assertEqual(len(stored_session["messages"]), 2)

    def test_reply_falls_back_when_model_output_is_not_json(self) -> None:
        chatbot_copilot_service.gemini_service.generate_content = lambda *args, **kwargs: "không phải json"  # type: ignore[assignment]

        session_id = self._create_session()
        reply_response = self.client.post(
            f"/api/account/chatbot/sessions/{session_id}/reply",
            json={
                "message": "So sánh nhanh top ứng viên backend",
                "selectedCandidateIds": ["cand-001", "cand-002"],
            },
        )
        self.assertEqual(reply_response.status_code, 200, reply_response.text)
        payload = reply_response.json()
        self.assertGreaterEqual(len(payload["candidateCards"]), 1)
        self.assertTrue(payload["responseText"].startswith("- Kết luận nhanh:"))
        self.assertGreaterEqual(len(payload["followUpQuestions"]), 1)

    def test_reply_returns_404_for_missing_or_foreign_session(self) -> None:
        self.fake_chatbot_sessions.store["foreign-session"] = {
            "uid": "other-user",
            "email": "other@example.com",
            "jobPosition": "Backend Developer",
            "totalCandidates": 1,
            "sessionTitle": "Foreign",
            "messages": [],
            "messageCount": 0,
            "candidateBriefs": self._candidate_briefs(),
        }

        missing = self.client.post(
            "/api/account/chatbot/sessions/missing/reply",
            json={"message": "test"},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

        foreign = self.client.post(
            "/api/account/chatbot/sessions/foreign-session/reply",
            json={"message": "test"},
        )
        self.assertEqual(foreign.status_code, 404, foreign.text)


if __name__ == "__main__":
    unittest.main()
