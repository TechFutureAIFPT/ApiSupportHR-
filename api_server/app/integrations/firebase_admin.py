from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

try:
    import firebase_admin
    from firebase_admin import app_check, auth as firebase_auth
    from firebase_admin import credentials, firestore
except ModuleNotFoundError:  # pragma: no cover - test environments may not install Firebase Admin.
    firebase_admin = None  # type: ignore[assignment]
    app_check = None  # type: ignore[assignment]
    firebase_auth = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]
    firestore = None  # type: ignore[assignment]


def _build_credential_payload() -> dict[str, Any]:
    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if service_account_json:
        if service_account_json.startswith("{"):
            return json.loads(service_account_json)
        with open(service_account_json, "r", encoding="utf-8") as handle:
            return json.load(handle)

    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL", "").strip()
    private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n").strip()

    if not project_id or not client_email or not private_key:
        raise RuntimeError(
            "Firebase Admin chưa được cấu hình. Hãy set FIREBASE_SERVICE_ACCOUNT_JSON hoặc "
            "FIREBASE_PROJECT_ID/FIREBASE_CLIENT_EMAIL/FIREBASE_PRIVATE_KEY."
        )

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
        raise RuntimeError("Firebase Admin SDK chua duoc cai dat trong moi truong hien tai.")

    if firebase_admin._apps:
        return firebase_admin.get_app()

    credential_payload = _build_credential_payload()
    credential = credentials.Certificate(credential_payload)
    project_id = credential_payload.get("project_id") or os.getenv("FIREBASE_PROJECT_ID", "").strip()
    options = {"projectId": project_id} if project_id else None
    return firebase_admin.initialize_app(credential, options=options)


def get_firestore_client() -> Any:
    if firestore is None:
        raise RuntimeError("Firebase Firestore client chua san sang trong moi truong hien tai.")
    return firestore.client(get_firebase_app())


def verify_firebase_token(id_token: str) -> dict[str, Any]:
    if firebase_auth is None:
        raise RuntimeError("Firebase Admin SDK chua duoc cai dat trong moi truong hien tai.")
    return firebase_auth.verify_id_token(id_token, app=get_firebase_app())


def verify_app_check_token(token: str) -> dict[str, Any]:
    if app_check is None:
        raise RuntimeError("Firebase App Check SDK chua duoc cai dat trong moi truong hien tai.")
    return app_check.verify_token(token, app=get_firebase_app())
