from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user
from app.schemas.account import (
    AnalysisFeedbackRequest,
    AnalysisFeedbackResponse,
    AnalysisFeedbackStatsResponse,
    AuthenticatedUser,
    HistorySaveRequest,
)
from app.services.account import feedback_service, history_service


router = APIRouter()


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
