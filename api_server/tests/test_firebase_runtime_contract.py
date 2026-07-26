from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.integrations import auth_provider


class FirebaseRuntimeContractTests(unittest.TestCase):
    def test_settings_are_firebase_only(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FIREBASE_PROJECT_ID": "supporthr-test",
                "FIREBASE_SERVICE_ACCOUNT_JSON": "",
            },
            clear=False,
        ):
            settings = Settings()
        self.assertEqual(settings.firebase_project_id, "supporthr-test")
        self.assertFalse(hasattr(settings, "database_url"))

    def test_auth_provider_delegates_to_firebase(self) -> None:
        original = auth_provider.verify_firebase_token
        try:
            auth_provider.verify_firebase_token = lambda token: {"uid": "firebase-user", "token": token}
            result = auth_provider.verify_access_token("id-token")
        finally:
            auth_provider.verify_firebase_token = original
        self.assertEqual(result["uid"], "firebase-user")
        self.assertEqual(result["token"], "id-token")


if __name__ == "__main__":
    unittest.main()
