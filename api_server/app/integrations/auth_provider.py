from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.firebase_admin import verify_firebase_token
from app.integrations.supabase_auth import verify_supabase_token


def verify_access_token(token: str) -> dict[str, Any]:
    if get_settings().auth_provider == "supabase":
        return verify_supabase_token(token)
    return verify_firebase_token(token)
