from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings
from app.integrations.auth_provider import verify_access_token
from app.schemas.account import AuthenticatedUser
from app.services.security_service import verify_app_check_if_required


def _cached_user_from_request(request: Request) -> AuthenticatedUser | None:
    uid = getattr(request.state, "auth_uid", None)
    email = getattr(request.state, "auth_email", None)
    if not uid and not email:
        return None
    return AuthenticatedUser(
        uid=str(uid or ""),
        email=str(email or ""),
        display_name=getattr(request.state, "auth_display_name", None),
        photo_url=getattr(request.state, "auth_photo_url", None),
    )


def _persist_user_on_request(request: Request, user: AuthenticatedUser) -> None:
    request.state.auth_uid = user.uid
    request.state.auth_email = user.email
    request.state.auth_display_name = user.display_name
    request.state.auth_photo_url = user.photo_url


async def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    verify_app_check_if_required(request)
    cached = _cached_user_from_request(request)
    if cached is not None and cached.uid:
        return cached

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Thiếu Bearer token.")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token không hợp lệ.")

    try:
        decoded = verify_access_token(token)
    except Exception as error:  # pragma: no cover - depends on Firebase runtime
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Không thể xác thực {get_settings().auth_provider} token: {error}",
        ) from error

    user = AuthenticatedUser(
        uid=str(decoded.get("uid") or decoded.get("user_id") or ""),
        email=str(decoded.get("email") or ""),
        display_name=decoded.get("name"),
        photo_url=decoded.get("picture"),
    )
    _persist_user_on_request(request, user)
    return user


async def get_optional_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser | None:
    verify_app_check_if_required(request)
    cached = _cached_user_from_request(request)
    if cached is not None:
        return cached

    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    try:
        decoded = verify_access_token(token)
    except Exception:
        return None

    user = AuthenticatedUser(
        uid=str(decoded.get("uid") or decoded.get("user_id") or ""),
        email=str(decoded.get("email") or ""),
        display_name=decoded.get("name"),
        photo_url=decoded.get("picture"),
    )
    _persist_user_on_request(request, user)
    return user
