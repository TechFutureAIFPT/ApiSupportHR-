from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.api.deps import get_current_user
from app.api.response_utils import cached_json_response
from app.schemas.account import AuthenticatedUser, UserSettingsPatchRequest
from app.services.account import settings_service


router = APIRouter()


@router.get("/settings")
def get_user_settings(request: Request, current_user: AuthenticatedUser = Depends(get_current_user)):
    return cached_json_response(request, settings_service.get_user_settings_response(current_user))


@router.patch("/settings")
def patch_user_settings(
    request: Request,
    payload: UserSettingsPatchRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        saved = settings_service.save_user_settings_response(
            current_user,
            payload.model_dump(exclude_none=True),
            expected_revision=if_match,
        )
    except settings_service.SettingsWriteConflict as error:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(error)) from error
    except settings_service.SettingsWriteBusy as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error), headers={"Retry-After": "1"}) from error
    return cached_json_response(request, saved)


@router.post("/settings/reset")
def reset_user_settings(
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        saved = settings_service.reset_user_settings_response(current_user, expected_revision=if_match)
    except settings_service.SettingsWriteConflict as error:
        raise HTTPException(status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(error)) from error
    except settings_service.SettingsWriteBusy as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error), headers={"Retry-After": "1"}) from error
    return cached_json_response(request, saved)
