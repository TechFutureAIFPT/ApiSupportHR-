from __future__ import annotations

from typing import Any

from app.integrations.firebase_admin import verify_firebase_token


def verify_access_token(token: str) -> dict[str, Any]:
    return verify_firebase_token(token)
