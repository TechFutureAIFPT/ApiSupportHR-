from __future__ import annotations

from fastapi import HTTPException, status

from app.services.account import google_drive_service


def raise_google_drive_http_error(error: Exception) -> None:
    if isinstance(error, google_drive_service.GoogleDriveConfigError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
    if isinstance(error, google_drive_service.GoogleDriveValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if isinstance(error, google_drive_service.GoogleDriveProviderError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
