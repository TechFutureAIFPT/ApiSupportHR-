from __future__ import annotations

from typing import Any

from app.integrations.supabase_auth import verify_supabase_token


def verify_access_token(token: str) -> dict[str, Any]:
    return verify_supabase_token(token)
