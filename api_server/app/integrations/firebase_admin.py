from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from typing import Any

try:
    import firebase_admin
    from firebase_admin import app_check
    from firebase_admin import auth as firebase_auth
    from firebase_admin import credentials, firestore
except ModuleNotFoundError:  # pragma: no cover - isolated tests can mock this integration.
    firebase_admin = None  # type: ignore[assignment]
    app_check = None  # type: ignore[assignment]
    firebase_auth = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]
    firestore = None  # type: ignore[assignment]


_readiness_checked_at = 0.0
_readiness_result = False


def _service_account_payload() -> dict[str, Any] | None:
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        if raw.startswith("{"):
            return json.loads(raw)
        with open(raw, "r", encoding="utf-8") as handle:
            return json.load(handle)

    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL", "").strip()
    private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    if not (project_id and client_email and private_key):
        return None
    return {
        "type": "service_account",
        "project_id": project_id,
        "client_email": client_email,
        "private_key": private_key,
        "token_uri": os.getenv("FIREBASE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
    }


@lru_cache
def get_firebase_app() -> Any:
    if firebase_admin is None or credentials is None:
        raise RuntimeError("Firebase Admin SDK chưa được cài đặt.")
    if firebase_admin._apps:
        return firebase_admin.get_app()

    payload = _service_account_payload()
    project_id = (
        (payload or {}).get("project_id")
        or os.getenv("FIREBASE_PROJECT_ID", "").strip()
    )
    options: dict[str, str] = {}
    if project_id:
        options["projectId"] = str(project_id)
    database_url = os.getenv("FIREBASE_DATABASE_URL", "").strip()
    storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if database_url:
        options["databaseURL"] = database_url
    if storage_bucket:
        options["storageBucket"] = storage_bucket

    credential = credentials.Certificate(payload) if payload else credentials.ApplicationDefault()
    return firebase_admin.initialize_app(credential, options=options or None)


def get_firestore_client() -> Any:
    if firestore is None:
        raise RuntimeError("Firebase Firestore client chưa sẵn sàng.")
    return firestore.client(get_firebase_app())


def verify_firebase_token(id_token: str) -> dict[str, Any]:
    if firebase_auth is None:
        raise RuntimeError("Firebase Auth Admin SDK chưa sẵn sàng.")
    return firebase_auth.verify_id_token(id_token, app=get_firebase_app(), check_revoked=True)


def verify_app_check_token(token: str) -> dict[str, Any]:
    if app_check is None:
        raise RuntimeError("Firebase App Check Admin SDK chưa sẵn sàng.")
    return app_check.verify_token(token, app=get_firebase_app())


def firestore_ready(*, cache_seconds: float = 15.0) -> bool:
    global _readiness_checked_at, _readiness_result
    now = time.monotonic()
    if now - _readiness_checked_at < cache_seconds:
        return _readiness_result
    try:
        get_firestore_client().collection("users").limit(1).get()
        _readiness_result = True
    except Exception:
        _readiness_result = False
    _readiness_checked_at = now
    return _readiness_result
