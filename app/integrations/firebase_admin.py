from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials, firestore


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
def get_firebase_app() -> firebase_admin.App:
    if firebase_admin._apps:
        return firebase_admin.get_app()

    credential_payload = _build_credential_payload()
    credential = credentials.Certificate(credential_payload)
    project_id = credential_payload.get("project_id") or os.getenv("FIREBASE_PROJECT_ID", "").strip()
    options = {"projectId": project_id} if project_id else None
    return firebase_admin.initialize_app(credential, options=options)


def get_firestore_client() -> firestore.Client:
    return firestore.client(get_firebase_app())


def verify_firebase_token(id_token: str) -> dict[str, Any]:
    return firebase_auth.verify_id_token(id_token, app=get_firebase_app())
