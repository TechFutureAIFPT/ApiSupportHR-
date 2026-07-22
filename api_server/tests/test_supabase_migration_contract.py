from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import Settings
from app.integrations.data_crypto import decrypt_secret_payload, encrypt_secret_payload
from app.repositories.postgres.document_store import COLLECTION_TABLES as RUNTIME_TABLES
from scripts.firebase_supabase_migration import COLLECTION_TABLES as MIGRATION_TABLES, _target_collisions


class SupabaseMigrationContractTests(unittest.TestCase):
    def test_runtime_and_migration_collection_maps_match(self) -> None:
        self.assertEqual(MIGRATION_TABLES, RUNTIME_TABLES)
        migration_sql = (
            Path(__file__).resolve().parents[2]
            / "supabase"
            / "migrations"
            / "202607220001_firebase_to_supabase.sql"
        ).read_text(encoding="utf-8")
        for table in set(MIGRATION_TABLES.values()):
            self.assertIn(f"'{table}'", migration_sql)

    def test_target_collision_is_rejected(self) -> None:
        source = {
            "analysisFeedback": [{"id": "same"}],
            "analysisFeedback.  Document ID": [{"id": "same"}],
        }
        self.assertEqual(_target_collisions(source), ["analysis_feedback/same"])

    def test_google_drive_secret_round_trip_uses_ciphertext(self) -> None:
        key = base64.b64encode(bytes(range(32))).decode("ascii")
        secret = {"accessToken": "plain-access", "refreshToken": "plain-refresh"}
        with patch.dict(os.environ, {"DATA_ENCRYPTION_KEY": key}, clear=False):
            encrypted = encrypt_secret_payload(secret)
            self.assertNotIn(b"plain-access", encrypted)
            self.assertEqual(decrypt_secret_payload(encrypted), secret)

    def test_supabase_provider_requires_runtime_coordinates(self) -> None:
        with patch.dict(
            os.environ,
            {"AUTH_PROVIDER": "supabase", "DATA_PROVIDER": "supabase", "SUPABASE_URL": "", "DATABASE_URL": ""},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                Settings()


if __name__ == "__main__":
    unittest.main()
