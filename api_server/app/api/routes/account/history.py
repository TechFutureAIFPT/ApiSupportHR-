from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.response_utils import cached_json_response
from app.api.pagination import CursorPageResponse, decode_cursor, parse_field_selection
from app.api.deps import get_current_user
from app.repositories.postgres.page_repository import paginate_owner_records
from app.schemas.account import (
    AnalysisFeedbackRequest,
    AnalysisFeedbackResponse,
    AnalysisFeedbackStatsResponse,
    AuthenticatedUser,
    HistorySaveRequest,
)
from app.services.account import feedback_service, history_service
from app.services.account import response_cache_service
from app.core.config import get_settings


router = APIRouter()
settings = get_settings()

HISTORY_PAGE_FIELDS = {
    "id", "source", "timestamp", "createdAt", "updatedAt", "jobPosition",
    "locationRequirement", "jdTextSnippet", "totalCandidates", "grades",
    "gradesCount", "topCandidates", "userEmail", "email", "analysisData",
    "fullPayload",
}
HISTORY_PAGE_DEFAULT_FIELDS = (
    "id", "source", "timestamp", "jobPosition", "locationRequirement",
    "jdTextSnippet", "totalCandidates", "grades", "gradesCount",
    "topCandidates", "userEmail", "email",
)


@router.post("/history")
def save_history_session(payload: HistorySaveRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": history_service.save_history_session(current_user, payload.model_dump())}


@router.get("/history")
def fetch_recent_history(
    request: Request,
    limit_count: int = Query(default=20, ge=1, le=200),
    user_email: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    normalized_email = (user_email or current_user.email or "").strip().lower() or "self"
    cache_key = response_cache_service.account_cache_key("history", current_user.uid, str(limit_count), normalized_email)
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key,
        "history",
        lambda: history_service.fetch_recent_history(current_user, limit_count=limit_count, user_email=user_email),
    )
    return cached_json_response(request, cached)


@router.get("/history/page", response_model=CursorPageResponse, response_model_by_alias=True)
def fetch_history_page(
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(default=None),
    fields: str | None = Query(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    selected_fields = parse_field_selection(
        fields,
        allowed_fields=HISTORY_PAGE_FIELDS,
        default_fields=HISTORY_PAGE_DEFAULT_FIELDS,
    )
    return paginate_owner_records(
        table_sources=(("cv_history", "cv"), ("synced_analysis_history", "sync")),
        owner_id=current_user.uid,
        page_size=page_size,
        fields=selected_fields,
        cursor=decode_cursor(cursor),
    )


@router.get("/mobile-inbox")
def fetch_mobile_inbox(
    request: Request,
    history_limit: int = Query(default=12, ge=1, le=50),
    candidate_limit: int = Query(default=60, ge=1, le=200),
    user_email: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    payload = history_service.fetch_mobile_inbox(
        current_user,
        history_limit=history_limit,
        candidate_limit=candidate_limit,
        user_email=user_email,
    )
    return cached_json_response(request, payload)


@router.post("/history/manual-snapshot")
def save_manual_history_snapshot(payload: HistorySaveRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": history_service.save_manual_history_snapshot(current_user, payload.model_dump())}


@router.get("/history/manual")
def fetch_manual_history(
    limit_count: int = Query(default=20, ge=1, le=100),
    user_email: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return history_service.fetch_manual_history(current_user, user_email=user_email, limit_count=limit_count)


@router.post("/history/feedback", response_model=AnalysisFeedbackResponse)
def save_analysis_feedback(payload: AnalysisFeedbackRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return feedback_service.save_feedback_record(current_user, payload.model_dump())


@router.get("/history/feedback", response_model=list[AnalysisFeedbackResponse])
def list_analysis_feedback(
    request: Request,
    limit_count: int = Query(default=50, ge=1, le=200),
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
    candidate_id: str | None = None,
    action: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    cache_key = response_cache_service.account_cache_key(
        "feedback", current_user.uid, "list", str(limit_count),
        session_id or "", history_id or "", sync_history_id or "", candidate_id or "", action or "",
    )
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key,
        "feedback",
        lambda: feedback_service.list_feedback(
            current_user,
            limit_count=limit_count,
            session_id=session_id,
            history_id=history_id,
            sync_history_id=sync_history_id,
            candidate_id=candidate_id,
            action=action,
        ),
    )
    return cached_json_response(request, cached)


@router.get("/history/feedback/stats", response_model=AnalysisFeedbackStatsResponse)
def get_analysis_feedback_stats(
    request: Request,
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    cache_key = response_cache_service.account_cache_key(
        "feedback", current_user.uid, "stats", session_id or "", history_id or "", sync_history_id or "",
    )
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key,
        "feedback",
        lambda: feedback_service.get_feedback_stats(
            current_user,
            session_id=session_id,
            history_id=history_id,
            sync_history_id=sync_history_id,
        ),
    )
    return cached_json_response(request, cached)


@router.delete("/history/feedback/{feedback_id}")
def delete_analysis_feedback(feedback_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": feedback_service.delete_feedback(current_user, feedback_id)}
