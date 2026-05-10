from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.schemas.account import AuthenticatedUser
from app.integrations.firebase_admin import verify_firebase_token


async def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Thiếu Bearer token.")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token không hợp lệ.")

    try:
        decoded = verify_firebase_token(token)
    except Exception as error:  # pragma: no cover - depends on Firebase runtime
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Không thể xác thực Firebase token: {error}",
        ) from error

    return AuthenticatedUser(
        uid=str(decoded.get("uid") or decoded.get("user_id") or ""),
        email=str(decoded.get("email") or ""),
        display_name=decoded.get("name"),
        photo_url=decoded.get("picture"),
    )
