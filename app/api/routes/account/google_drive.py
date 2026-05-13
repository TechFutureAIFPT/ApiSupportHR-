from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.api.routes.account.shared import raise_google_drive_http_error
from app.schemas.account import (
    AuthenticatedUser,
    GoogleDriveConnectionStatusResponse,
    GoogleDriveFilesResponse,
    GoogleDriveImportRequest,
    GoogleDriveImportResponse,
    GoogleDriveOAuthExchangeRequest,
    GoogleDriveOAuthUrlRequest,
    GoogleDriveOAuthUrlResponse,
)
from app.services.account import google_drive_service


router = APIRouter()


@router.get("/google-drive/status", response_model=GoogleDriveConnectionStatusResponse)
def get_google_drive_status(current_user: AuthenticatedUser = Depends(get_current_user)):
    try:
        return google_drive_service.get_connection_status(current_user)
    except Exception as error:
        raise_google_drive_http_error(error)


@router.post("/google-drive/oauth-url", response_model=GoogleDriveOAuthUrlResponse)
def create_google_drive_oauth_url(
    payload: GoogleDriveOAuthUrlRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return google_drive_service.create_oauth_url(current_user, payload.redirectUri)
    except Exception as error:
        raise_google_drive_http_error(error)


@router.post("/google-drive/exchange-code", response_model=GoogleDriveConnectionStatusResponse)
def exchange_google_drive_code(
    payload: GoogleDriveOAuthExchangeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return google_drive_service.exchange_code(
            current_user,
            code=payload.code,
            state=payload.state,
            redirect_uri=payload.redirectUri,
        )
    except Exception as error:
        raise_google_drive_http_error(error)


@router.delete("/google-drive/connection")
def disconnect_google_drive(current_user: AuthenticatedUser = Depends(get_current_user)):
    try:
        return {"ok": google_drive_service.disconnect(current_user)}
    except Exception as error:
        raise_google_drive_http_error(error)


@router.get("/google-drive/files", response_model=GoogleDriveFilesResponse)
def list_google_drive_files(
    search: str | None = None,
    folder_id: str | None = None,
    page_token: str | None = None,
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return google_drive_service.list_files(
            current_user,
            search=search,
            folder_id=folder_id,
            page_size=page_size,
            page_token=page_token,
        )
    except Exception as error:
        raise_google_drive_http_error(error)


@router.post("/google-drive/import", response_model=GoogleDriveImportResponse)
def import_google_drive_file(
    payload: GoogleDriveImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return google_drive_service.import_file_from_drive(current_user, payload.model_dump())
    except Exception as error:
        raise_google_drive_http_error(error)
