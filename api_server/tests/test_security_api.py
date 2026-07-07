from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import api_app
from app.services import security_service


class SecurityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.original_get_settings = security_service.get_settings
        self.original_redis_increment = security_service.redis_cache.increment
        security_service._fallback_windows.clear()

    def tearDown(self) -> None:
        security_service.get_settings = self.original_get_settings  # type: ignore[assignment]
        security_service.redis_cache.increment = self.original_redis_increment  # type: ignore[assignment]
        security_service._fallback_windows.clear()
        api_app.dependency_overrides.clear()
        self.client.close()

    def test_health_rate_limit_returns_429_after_threshold(self) -> None:
        security_service.redis_cache.increment = lambda *args, **kwargs: None  # type: ignore[assignment]

        for _ in range(30):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200, response.text)

        blocked = self.client.get("/health")
        self.assertEqual(blocked.status_code, 429, blocked.text)

    def test_mobile_inbox_rejects_missing_app_check_when_enforced(self) -> None:
        security_service.get_settings = lambda: SimpleNamespace(firebase_appcheck_enforce=True)  # type: ignore[assignment]

        response = self.client.get(
            "/api/account/mobile-inbox",
            headers={
                "Authorization": "Bearer fake-token",
                "Origin": "https://www.supporthr-tf.com.vn",
            },
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("X-Firebase-AppCheck", response.text)


if __name__ == "__main__":
    unittest.main()
