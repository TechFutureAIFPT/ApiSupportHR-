from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.account import AuthenticatedUser
from app.services.account import notification_service


router = APIRouter()


@router.get("/notifications")
def list_notifications(
    limit_count: int = Query(default=20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return notification_service.list_notifications(current_user, limit_count=limit_count)


@router.post("/notifications/read-all")
def mark_all_read(current_user: AuthenticatedUser = Depends(get_current_user)):
    notification_service.mark_all_read(current_user)
    return {"ok": True}


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    notification_service.mark_read(current_user, notification_id)
    return {"ok": True}
