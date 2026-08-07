from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.schemas.account import AuthenticatedUser
from app.services.account.email_service import GmailSendError, send_bulk
from app.services.account import google_drive_service
from app.api.routes.account.google_drive import raise_google_drive_http_error


router = APIRouter()


class EmailItem(BaseModel):
    to: str
    subject: str = "Thông báo tuyển dụng"
    body: str


class EmailSendRequest(BaseModel):
    emails: list[EmailItem] = Field(..., min_length=1, max_length=50)


class EmailSendResult(BaseModel):
    to: str
    status: str
    id: str | None = None
    error: str | None = None


class EmailSendResponse(BaseModel):
    sent: int
    failed: int
    results: list[EmailSendResult]


@router.post("/email/send", response_model=EmailSendResponse)
def send_emails(
    payload: EmailSendRequest,
    x_google_access_token: str | None = Header(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    google_access_token = x_google_access_token
    if not google_access_token:
        try:
            google_access_token = google_drive_service.get_valid_access_token(current_user)
        except Exception as error:
            raise_google_drive_http_error(error)

    try:
        raw_results = send_bulk(
            google_access_token=google_access_token,
            emails=[item.model_dump() for item in payload.emails],
        )
    except GmailSendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    results = [EmailSendResult(**r) for r in raw_results]
    sent = sum(1 for r in results if r.status == "sent")
    failed = len(results) - sent

    return EmailSendResponse(sent=sent, failed=failed, results=results)
