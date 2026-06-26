from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.account import (
    AuthenticatedUser,
    LocalDataMigrationRequest,
    UserAvatarUpdateRequest,
    UserCvHistoryCreateRequest,
    UserProfileUpsertRequest,
)
from app.services.account import profile_service


router = APIRouter()


@router.get("/profile")
def get_profile(current_user: AuthenticatedUser = Depends(get_current_user)):
    return profile_service.get_user_profile(current_user)


@router.put("/profile")
def upsert_profile(payload: UserProfileUpsertRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return profile_service.upsert_user_profile(
        current_user,
        email=payload.email,
        display_name=payload.displayName,
        avatar=payload.avatar,
        provider=payload.provider,
        recruiter_title=payload.recruiterTitle,
        recruiter_company=payload.recruiterCompany,
        recruiter_department=payload.recruiterDepartment,
        recruiter_phone=payload.recruiterPhone,
        email_signature=payload.emailSignature,
    )


@router.patch("/profile/avatar")
def update_profile_avatar(payload: UserAvatarUpdateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return profile_service.update_user_avatar(current_user, payload.avatar)


@router.post("/profile/cv-history")
def create_profile_cv_history(payload: UserCvHistoryCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {
        "id": profile_service.save_cv_history(
            current_user,
            email=payload.email or current_user.email,
            jd_text=payload.jdText,
            jd_title=payload.jdTitle,
            cv_count=payload.cvCount,
            results=payload.results,
        )
    }


@router.get("/profile/cv-history")
def list_profile_cv_history(
    limit_count: int = Query(default=50, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return profile_service.get_user_cv_history(current_user, limit_count=limit_count)


@router.post("/profile/cv-history/cleanup")
def cleanup_profile_cv_history(
    keep_count: int = Query(default=100, ge=1, le=1000),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    profile_service.cleanup_profile_cv_history(current_user, keep_count=keep_count)
    return {"ok": True}


@router.post("/profile/migrate-local")
def migrate_local_profile_data(payload: LocalDataMigrationRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return profile_service.migrate_local_data(
        current_user,
        avatar=payload.avatar,
        history=[item.model_dump() for item in payload.history],
    )
