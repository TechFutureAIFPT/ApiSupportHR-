from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.schemas.account import (
    AnalysisRunDataRequest,
    AnalysisFeedbackRequest,
    AnalysisFeedbackResponse,
    AnalysisFeedbackStatsResponse,
    AuthenticatedUser,
    CacheSyncRequest,
    ChatbotMessagesRequest,
    ChatbotSessionCreateRequest,
    GoogleDriveConnectionStatusResponse,
    GoogleDriveFilesResponse,
    GoogleDriveImportRequest,
    GoogleDriveImportResponse,
    GoogleDriveOAuthExchangeRequest,
    GoogleDriveOAuthUrlRequest,
    GoogleDriveOAuthUrlResponse,
    HistorySaveRequest,
    LocalDataMigrationRequest,
    UploadedFileCreateRequest,
    UploadedFilesBatchRequest,
    UserAvatarUpdateRequest,
    UserCvHistoryCreateRequest,
    UserJDTemplateCreateRequest,
    UserProfileUpsertRequest,
)
from app.services.account import (
    cache_service,
    chatbot_service,
    feedback_service,
    google_drive_service,
    history_service,
    profile_service,
    template_service,
    uploaded_file_service,
)


router = APIRouter(prefix="/api/account", tags=["account"])


def _raise_google_drive_http_error(error: Exception) -> None:
    if isinstance(error, google_drive_service.GoogleDriveConfigError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
    if isinstance(error, google_drive_service.GoogleDriveValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    if isinstance(error, google_drive_service.GoogleDriveProviderError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error


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


@router.post("/sync/cache")
def sync_cache_entry(payload: CacheSyncRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    cache_service.sync_cache_entry(
        current_user,
        cache_key=payload.cacheKey,
        candidate_data=payload.candidateData,
        jd_hash=payload.jdHash,
        weights_hash=payload.weightsHash,
        filters_hash=payload.filtersHash,
        file_info=payload.fileInfo.model_dump(),
    )
    return {"ok": True}


@router.get("/sync/cache/{cache_key}")
def get_cache_entry(cache_key: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return cache_service.get_cache_entry(current_user, cache_key)


@router.get("/sync/cache")
def get_all_cache_entries(current_user: AuthenticatedUser = Depends(get_current_user)):
    return cache_service.get_all_user_cache(current_user)


@router.delete("/sync/cache")
def clear_all_cache_entries(current_user: AuthenticatedUser = Depends(get_current_user)):
    cache_service.clear_user_cache(current_user)
    return {"ok": True}


@router.post("/sync/history")
def sync_history_entry(payload: AnalysisRunDataRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": history_service.sync_history_entry(current_user, payload.model_dump())}


@router.get("/sync/history")
def get_synced_history(
    limit_count: int = Query(default=20, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return history_service.get_synced_history(current_user, limit_count=limit_count)


@router.get("/sync/stats")
def get_sync_stats(current_user: AuthenticatedUser = Depends(get_current_user)):
    return history_service.get_sync_stats(current_user)


@router.post("/history")
def save_history_session(payload: HistorySaveRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": history_service.save_history_session(current_user, payload.model_dump())}


@router.get("/history")
def fetch_recent_history(
    limit_count: int = Query(default=20, ge=1, le=200),
    user_email: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return history_service.fetch_recent_history(current_user, limit_count=limit_count, user_email=user_email)


@router.post("/history/manual-snapshot")
def save_manual_history_snapshot(payload: HistorySaveRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": history_service.save_manual_history_snapshot(current_user, payload.model_dump())}


@router.get("/history/manual")
def fetch_manual_history(
    user_email: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return history_service.fetch_manual_history(current_user, user_email=user_email)


@router.post("/history/feedback", response_model=AnalysisFeedbackResponse)
def save_analysis_feedback(payload: AnalysisFeedbackRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    feedback_id = feedback_service.save_feedback(current_user, payload.model_dump())
    matching = feedback_service.get_feedback_by_id(current_user, feedback_id)
    if matching:
        return matching
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Khong the doc lai feedback vua luu.")


@router.get("/history/feedback", response_model=list[AnalysisFeedbackResponse])
def list_analysis_feedback(
    limit_count: int = Query(default=50, ge=1, le=500),
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
    candidate_id: str | None = None,
    action: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return feedback_service.list_feedback(
        current_user,
        limit_count=limit_count,
        session_id=session_id,
        history_id=history_id,
        sync_history_id=sync_history_id,
        candidate_id=candidate_id,
        action=action,
    )


@router.get("/history/feedback/stats", response_model=AnalysisFeedbackStatsResponse)
def get_analysis_feedback_stats(
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return feedback_service.get_feedback_stats(
        current_user,
        session_id=session_id,
        history_id=history_id,
        sync_history_id=sync_history_id,
    )


@router.delete("/history/feedback/{feedback_id}")
def delete_analysis_feedback(feedback_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": feedback_service.delete_feedback(current_user, feedback_id)}


@router.post("/uploaded-files")
def save_uploaded_file(payload: UploadedFileCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": uploaded_file_service.save_uploaded_file(current_user, payload.model_dump())}


@router.post("/uploaded-files/batch")
def save_uploaded_files(payload: UploadedFilesBatchRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ids": uploaded_file_service.save_uploaded_files(current_user, [item.model_dump() for item in payload.files])}


@router.get("/uploaded-files")
def list_uploaded_files(
    limit_count: int = Query(default=50, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return uploaded_file_service.get_user_files(current_user, limit_count=limit_count)


@router.get("/uploaded-files/by-type/{file_type}")
def list_uploaded_files_by_type(
    file_type: str,
    limit_count: int = Query(default=50, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return uploaded_file_service.get_user_files_by_type(current_user, file_type=file_type, limit_count=limit_count)


@router.get("/uploaded-files/by-session/{session_id}")
def list_uploaded_files_by_session(session_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return uploaded_file_service.get_files_by_session(current_user, session_id=session_id)


@router.delete("/uploaded-files/{file_id}")
def delete_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": uploaded_file_service.delete_file(current_user, file_id)}


@router.post("/uploaded-files/{file_id}/touch")
def touch_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": uploaded_file_service.touch_file(current_user, file_id)}


@router.get("/uploaded-files/stats")
def get_uploaded_file_stats(current_user: AuthenticatedUser = Depends(get_current_user)):
    return uploaded_file_service.get_file_stats(current_user)


@router.get("/jd-templates")
def get_jd_templates(current_user: AuthenticatedUser = Depends(get_current_user)):
    return template_service.get_user_templates(current_user)


@router.post("/jd-templates")
def create_jd_template(payload: UserJDTemplateCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return template_service.create_template(current_user, payload.model_dump())


@router.patch("/jd-templates/{template_id}")
def update_jd_template(
    template_id: str,
    payload: UserJDTemplateCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return {"ok": template_service.update_template(current_user, template_id, payload.model_dump())}


@router.delete("/jd-templates/{template_id}")
def delete_jd_template(template_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": template_service.delete_template(current_user, template_id)}


@router.post("/jd-templates/seed-defaults")
def seed_jd_templates(current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"created": template_service.seed_default_templates_if_empty(current_user)}


@router.post("/chatbot/sessions")
def create_chatbot_session(payload: ChatbotSessionCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": chatbot_service.create_chatbot_session(current_user, payload.jobPosition, payload.totalCandidates)}


@router.post("/chatbot/sessions/{session_id}/messages")
def add_chatbot_messages(
    session_id: str,
    payload: ChatbotMessagesRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return {"ok": chatbot_service.add_chatbot_messages(current_user, session_id, [item.model_dump() for item in payload.messages])}


@router.get("/chatbot/sessions")
def list_chatbot_sessions(
    limit_count: int = Query(default=20, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return chatbot_service.get_user_chatbot_sessions(current_user, limit_count=limit_count)


@router.get("/chatbot/sessions/{session_id}")
def get_chatbot_session(session_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return chatbot_service.get_chatbot_session(current_user, session_id)


@router.get("/chatbot/recent")
def find_recent_chatbot_session(job_position: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return chatbot_service.find_recent_chatbot_session(current_user, job_position)


@router.delete("/chatbot/sessions/{session_id}")
def delete_chatbot_session(session_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": chatbot_service.delete_chatbot_session(current_user, session_id)}


@router.get("/chatbot/stats")
def get_chatbot_stats(current_user: AuthenticatedUser = Depends(get_current_user)):
    return chatbot_service.get_chatbot_session_stats(current_user)


@router.get("/google-drive/status", response_model=GoogleDriveConnectionStatusResponse)
def get_google_drive_status(current_user: AuthenticatedUser = Depends(get_current_user)):
    try:
        return google_drive_service.get_connection_status(current_user)
    except Exception as error:
        _raise_google_drive_http_error(error)


@router.post("/google-drive/oauth-url", response_model=GoogleDriveOAuthUrlResponse)
def create_google_drive_oauth_url(
    payload: GoogleDriveOAuthUrlRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return google_drive_service.create_oauth_url(current_user, payload.redirectUri)
    except Exception as error:
        _raise_google_drive_http_error(error)


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
        _raise_google_drive_http_error(error)


@router.delete("/google-drive/connection")
def disconnect_google_drive(current_user: AuthenticatedUser = Depends(get_current_user)):
    try:
        return {"ok": google_drive_service.disconnect(current_user)}
    except Exception as error:
        _raise_google_drive_http_error(error)


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
        _raise_google_drive_http_error(error)


@router.post("/google-drive/import", response_model=GoogleDriveImportResponse)
def import_google_drive_file(
    payload: GoogleDriveImportRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return google_drive_service.import_file_from_drive(current_user, payload.model_dump())
    except Exception as error:
        _raise_google_drive_http_error(error)
