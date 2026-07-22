from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone
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

    @property
    def exists(self) -> bool:
        return self.id in self._collection.store

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._collection.store.get(self.id, {}))


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


class FakeCollection:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def document(self, doc_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self, doc_id)


class SettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.fake_user_settings = FakeCollection()
        self.original_user_settings = repo.user_settings
        self.original_server_timestamp = repo.server_timestamp

        repo.user_settings = lambda: self.fake_user_settings  # type: ignore[assignment]
        repo.server_timestamp = lambda: datetime.now(timezone.utc)  # type: ignore[assignment]
        api_app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            uid="user-123",
            email="hr@example.com",
            display_name="HR Tester",
            photo_url="https://example.com/avatar.png",
        )

    def tearDown(self) -> None:
        repo.user_settings = self.original_user_settings  # type: ignore[assignment]
        repo.server_timestamp = self.original_server_timestamp  # type: ignore[assignment]
        api_app.dependency_overrides.clear()
        self.client.close()

    def test_get_settings_returns_default_when_missing(self) -> None:
        response = self.client.get("/api/account/settings")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["ui"]["theme"], "light")
        self.assertEqual(payload["ui"]["language"], "vi-VN")
        self.assertEqual(payload["account"]["email"], "hr@example.com")
        self.assertEqual(payload["account"]["displayName"], "HR Tester")
        self.assertIn("user-123", self.fake_user_settings.store)
        self.assertEqual(self.fake_user_settings.store["user-123"]["settings"]["ui"]["theme"], "light")

    def test_patch_settings_persists_and_locks_readonly_fields(self) -> None:
        response = self.client.patch(
            "/api/account/settings",
            json={
                "ui": {
                    "sidebarDensity": "cozy",
                    "theme": "dark",
                    "language": "en-US",
                },
                "notifications": {
                    "historySaved": False,
                    "inAppOnly": False,
                },
                "sync": {
                    "historyRetention": 200,
                },
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["ui"]["sidebarDensity"], "cozy")
        self.assertEqual(payload["ui"]["theme"], "light")
        self.assertEqual(payload["ui"]["language"], "vi-VN")
        self.assertFalse(payload["notifications"]["historySaved"])
        self.assertTrue(payload["notifications"]["inAppOnly"])
        self.assertEqual(payload["sync"]["historyRetention"], 200)
        self.assertIsInstance(payload["sync"]["lastSyncedAt"], int)

        stored = self.fake_user_settings.store["user-123"]
        self.assertEqual(stored["uid"], "user-123")
        self.assertEqual(stored["settings"]["ui"]["theme"], "light")

    def test_patch_settings_persists_fixed_jd_workflow_config(self) -> None:
        response = self.client.patch(
            "/api/account/settings",
            json={
                "workflow": {
                    "newSessionMode": "keep-config",
                    "autoFillHardFiltersOnContinue": True,
                    "fixedJD": {
                        "enabled": True,
                        "name": "Backend Developer",
                        "jdText": "Python, FastAPI, PostgreSQL",
                        "savedAt": 1782466563564,
                        "scoringEnabled": True,
                        "weights": {
                            "jdFit": {
                                "children": [
                                    {"key": "overallFit", "weight": 20}
                                ]
                            }
                        },
                        "hardFilters": {
                            "location": "Hà Nội",
                            "locationMandatory": True,
                        },
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["workflow"]["newSessionMode"], "keep-config")
        self.assertTrue(payload["workflow"]["autoFillHardFiltersOnContinue"])
        self.assertEqual(payload["workflow"]["fixedJD"]["name"], "Backend Developer")
        self.assertEqual(payload["workflow"]["fixedJD"]["jdText"], "Python, FastAPI, PostgreSQL")
        self.assertTrue(payload["workflow"]["fixedJD"]["enabled"])
        self.assertTrue(payload["workflow"]["fixedJD"]["scoringEnabled"])
        self.assertEqual(payload["workflow"]["fixedJD"]["weights"]["jdFit"]["children"][0]["weight"], 20)
        self.assertEqual(payload["workflow"]["fixedJD"]["hardFilters"]["location"], "Hà Nội")

        stored = self.fake_user_settings.store["user-123"]["settings"]["workflow"]["fixedJD"]
        self.assertTrue(self.fake_user_settings.store["user-123"]["settings"]["workflow"]["autoFillHardFiltersOnContinue"])
        self.assertTrue(stored["enabled"])
        self.assertEqual(stored["name"], "Backend Developer")
        self.assertEqual(stored["jdText"], "Python, FastAPI, PostgreSQL")
        self.assertEqual(stored["hardFilters"]["location"], "Hà Nội")

    def test_reset_settings_restores_defaults_and_keeps_account_seed(self) -> None:
        self.client.patch(
            "/api/account/settings",
            json={"workflow": {"autoSaveDraft": False}, "sync": {"historyRetention": 200}},
        )

        response = self.client.post("/api/account/settings/reset")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["workflow"]["autoSaveDraft"])
        self.assertEqual(payload["sync"]["historyRetention"], 50)
        self.assertEqual(payload["account"]["email"], "hr@example.com")
        self.assertEqual(payload["account"]["avatar"], "https://example.com/avatar.png")


if __name__ == "__main__":
    unittest.main()
