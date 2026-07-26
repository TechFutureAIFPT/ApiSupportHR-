from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import api_app
from app.services import security_service


class SecurityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.original_redis_increment = security_service.redis_cache.increment
        security_service._fallback_windows.clear()

    def tearDown(self) -> None:
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

    def test_mobile_inbox_does_not_require_a_provider_specific_header(self) -> None:
        response = self.client.get(
            "/api/account/mobile-inbox",
            headers={"Origin": "https://www.supporthr-tf.com.vn"},
        )

        self.assertEqual(response.status_code, 401, response.text)
        self.assertIn("Bearer token", response.text)


if __name__ == "__main__":
    unittest.main()
