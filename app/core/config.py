from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv


load_dotenv()

DEFAULT_WEB_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://www.supporthr-tf.com.vn",
    "https://supporthr-tf.com.vn",
]


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "SupportHR Backend")
        self.frontend_origin = os.getenv("FRONTEND_ORIGIN", "https://www.supporthr-tf.com.vn")
        self.gemini_default_model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        raw_embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL", "").strip()
        if raw_embedding_model in {"", "text-embedding-004", "models/text-embedding-004"}:
            # Migrate legacy/default values to the current supported Gemini embedding model.
            self.gemini_embedding_model = "gemini-embedding-001"
        else:
            self.gemini_embedding_model = raw_embedding_model
        self.firebase_project_id = os.getenv("FIREBASE_PROJECT_ID", "")
        self.firebase_client_email = os.getenv("FIREBASE_CLIENT_EMAIL", "")
        self.firebase_private_key = os.getenv("FIREBASE_PRIVATE_KEY", "")
        self.firebase_service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
        self.firebase_web_api_key = os.getenv("FIREBASE_WEB_API_KEY", "")
        self.firebase_auth_domain = os.getenv("FIREBASE_AUTH_DOMAIN", "")
        self.firebase_database_url = os.getenv("FIREBASE_DATABASE_URL", "")
        self.firebase_storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "")
        self.firebase_messaging_sender_id = os.getenv("FIREBASE_MESSAGING_SENDER_ID", "")
        self.firebase_app_id = os.getenv("FIREBASE_APP_ID", "")
        self.firebase_measurement_id = os.getenv("FIREBASE_MEASUREMENT_ID", "")
        self.firebase_appcheck_site_key = os.getenv("FIREBASE_APPCHECK_SITE_KEY", "")
        self.google_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.google_picker_api_key = os.getenv("GOOGLE_PICKER_API_KEY", "")
        self.google_cloud_vision_api_key = os.getenv("GOOGLE_CLOUD_VISION_API_KEY", "")
        self.google_oauth_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
        self.google_oauth_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
        self.google_oauth_redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "")
        raw_drive_origins = os.getenv("GOOGLE_DRIVE_ALLOWED_ORIGINS", "").strip()
        self.vector_store_provider = os.getenv("VECTOR_STORE_PROVIDER", "json").strip().lower() or "json"
        self.vector_store_json_dir = os.getenv(
            "VECTOR_STORE_JSON_DIR",
            str(Path(__file__).resolve().parents[2] / "data" / "vector-library"),
        )
        self.vector_store_firestore_collection = (
            os.getenv("VECTOR_STORE_FIRESTORE_COLLECTION", "vectorLibraryRecords").strip()
            or "vectorLibraryRecords"
        )
        default_drive_origins = list(dict.fromkeys([self.frontend_origin, *DEFAULT_WEB_ORIGINS]))
        if raw_drive_origins:
            self.google_drive_allowed_origins = list(
                dict.fromkeys(
                    value.strip()
                    for value in raw_drive_origins.split(",")
                    if value.strip()
                )
            )
        else:
            self.google_drive_allowed_origins = default_drive_origins

    @property
    def gemini_api_keys(self) -> List[str]:
        raw = [
            os.getenv("GEMINI_API_KEY_1"),
            os.getenv("GEMINI_API_KEY_2"),
            os.getenv("GEMINI_API_KEY"),
        ]
        keys = [value.strip() for value in raw if isinstance(value, str) and value.strip()]
        seen: set[str] = set()
        unique: List[str] = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique


@lru_cache
def get_settings() -> Settings:
    return Settings()
