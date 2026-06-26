from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.account.chatbot import router as chatbot_router
from app.api.routes.account.email import router as email_router
from app.api.routes.account.google_drive import router as google_drive_router
from app.api.routes.account.history import router as history_router
from app.api.routes.account.notifications import router as notifications_router
from app.api.routes.account.profile import router as profile_router
from app.api.routes.account.settings import router as settings_router
from app.api.routes.account.sync import router as sync_router
from app.api.routes.account.templates import router as templates_router
from app.api.routes.account.uploaded_files import router as uploaded_files_router


router = APIRouter(prefix="/api/account", tags=["account"])
router.include_router(profile_router)
router.include_router(settings_router)
router.include_router(sync_router)
router.include_router(history_router)
router.include_router(notifications_router)
router.include_router(uploaded_files_router)
router.include_router(templates_router)
router.include_router(chatbot_router)
router.include_router(google_drive_router)
router.include_router(email_router)

__all__ = ["router"]
