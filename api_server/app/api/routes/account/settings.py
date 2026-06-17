from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.account import AuthenticatedUser, UserSettingsPatchRequest
from app.services.account import settings_service


router = APIRouter()


@router.get("/settings")
def get_user_settings(current_user: AuthenticatedUser = Depends(get_current_user)):
    return settings_service.get_user_settings(current_user)


@router.patch("/settings")
def patch_user_settings(
    payload: UserSettingsPatchRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return settings_service.save_user_settings(
        current_user,
        payload.model_dump(exclude_none=True),
    )


@router.post("/settings/reset")
def reset_user_settings(current_user: AuthenticatedUser = Depends(get_current_user)):
    return settings_service.reset_user_settings(current_user)
