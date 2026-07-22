from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import api_app
from app.repositories.postgres import account_repository as repo
from app.schemas.account import AuthenticatedUser


class FakeDocumentSnapshot:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._collection.store.get(self.id, {}))

    @property
    def exists(self) -> bool:
        return self.id in self._collection.store


class FakeDocumentReference:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def get(self) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self._collection, self.id)

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        current = self._collection.store.get(self.id, {}) if merge else {}
        self._collection.store[self.id] = {**current, **deepcopy(payload)}


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

    def document(self, doc_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self, doc_id)


class MobileInboxApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.fake_cv_history = FakeCollection()
        self.fake_synced_history = FakeCollection()
        self.fake_mobile_inbox_views = FakeCollection()
        self.original_cv_history = repo.cv_history
        self.original_synced_history = repo.synced_history
        self.original_mobile_inbox_views = repo.mobile_inbox_views

        repo.cv_history = lambda: self.fake_cv_history  # type: ignore[assignment]
        repo.synced_history = lambda: self.fake_synced_history  # type: ignore[assignment]
        repo.mobile_inbox_views = lambda: self.fake_mobile_inbox_views  # type: ignore[assignment]

    def tearDown(self) -> None:
        repo.cv_history = self.original_cv_history  # type: ignore[assignment]
        repo.synced_history = self.original_synced_history  # type: ignore[assignment]
        repo.mobile_inbox_views = self.original_mobile_inbox_views  # type: ignore[assignment]
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
                        "stageDecision": {"status": "hold", "label": "Loại tự động"},
                        "autoRejectReasons": ["Sai địa điểm bắt buộc"],
                        "candidateProfile": {
                            "age": 29,
                            "currentLocation": "TP. Hồ Chí Minh",
                            "educationLevel": "Bachelor",
                            "educationMajors": ["business-administration"],
                            "totalExperienceMonths": 48,
                            "relevantExperienceMonths": 48,
                        },
                        "screeningSummary": {
                            "location": {
                                "status": "fail",
                                "mandatory": True,
                                "expected": "Hà Nội",
                                "observed": "TP. Hồ Chí Minh",
                                "reason": "Địa điểm không khớp.",
                            }
                        },
                        "hrSummary": {
                            "tong_diem_phu_hop": 77,
                            "nhan_xet_tong_quan": "Ứng viên mạnh về kinh nghiệm nhưng sai địa điểm bắt buộc.",
                            "canh_bao_red_flag": ["Sai địa điểm bắt buộc"],
                            "kinh_nghiem": {
                                "so_nam_yeu_cau": "3 năm",
                                "so_nam_thuc_te": "4 năm",
                                "ket_luan": "Vượt mức",
                            },
                            "danh_gia_ky_nang": [
                                {
                                    "ten_ky_nang": "Python",
                                    "muc_do_dap_ung": "Đạt",
                                    "bang_chung_tu_cv": "Ứng viên dùng Python trong dự án backend.",
                                }
                            ],
                        },
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
        self.assertEqual(candidate["screeningOutcome"]["status"], "hold")
        self.assertEqual(candidate["autoRejectReasons"], ["Sai địa điểm bắt buộc"])
        self.assertEqual(candidate["screeningSummary"]["location"]["status"], "fail")
        self.assertEqual(candidate["candidateProfile"]["age"], 29)
        self.assertEqual(candidate["hrSummary"]["tong_diem_phu_hop"], 77)
        self.assertEqual(history["autoRejectCount"], 1)
        self.assertEqual(history["screeningStats"]["failFactors"]["location"], 1)
        self.assertEqual(history["topHrSummaries"][0]["score"], 77)

    def test_mobile_inbox_returns_304_when_revision_matches_if_none_match(self) -> None:
        api_app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            uid="user-304",
            email="etag@example.com",
            display_name="HR Tester",
            photo_url=None,
        )
        self.fake_cv_history.store["history-1"] = {
            "uid": "user-304",
            "userEmail": "etag@example.com",
            "jobPosition": "Backend Developer",
            "timestamp": 2000,
            "totalCandidates": 1,
            "fullPayload": {
                "candidates": [
                    {
                        "id": "cand-1",
                        "candidateName": "Nguyen Van A",
                        "status": "SUCCESS",
                        "analysis": {"Tổng điểm": 88, "Hạng": "A", "Chi tiết": []},
                    }
                ]
            },
        }

        first = self.client.get("/api/account/mobile-inbox")
        self.assertEqual(first.status_code, 200, first.text)
        etag = first.headers.get("etag")
        self.assertTrue(etag)

        second = self.client.get("/api/account/mobile-inbox", headers={"If-None-Match": str(etag)})
        self.assertEqual(second.status_code, 304, second.text)
        self.assertEqual(second.headers.get("etag"), etag)
        self.assertEqual(second.headers.get("x-data-revision"), first.headers.get("x-data-revision"))


if __name__ == "__main__":
    unittest.main()
