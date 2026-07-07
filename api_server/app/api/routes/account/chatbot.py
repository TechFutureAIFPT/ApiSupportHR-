from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.account import (
    AuthenticatedUser,
    ChatbotMessagesRequest,
    ChatbotReplyRequest,
    ChatbotReplyResponse,
    ChatbotSessionCreateRequest,
)
from app.services.account import chatbot_copilot_service, chatbot_service


router = APIRouter()


@router.post("/chatbot/sessions")
def create_chatbot_session(payload: ChatbotSessionCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {
        "id": chatbot_service.create_chatbot_session(
            current_user,
            payload.jobPosition,
            payload.totalCandidates,
            analysis_context=payload.analysisContext.model_dump() if payload.analysisContext else None,
            candidate_briefs=[item.model_dump() for item in payload.candidateBriefs],
        )
    }


@router.post("/chatbot/sessions/{session_id}/messages")
def add_chatbot_messages(
    session_id: str,
    payload: ChatbotMessagesRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return {"ok": chatbot_service.add_chatbot_messages(current_user, session_id, [item.model_dump() for item in payload.messages])}


@router.post("/chatbot/sessions/{session_id}/reply", response_model=ChatbotReplyResponse)
def reply_chatbot_session(
    session_id: str,
    payload: ChatbotReplyRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return chatbot_copilot_service.reply_to_chatbot_session(
        current_user,
        session_id,
        payload.message,
        selected_candidate_ids=payload.selectedCandidateIds,
        focus_candidate_id=payload.focusCandidateId,
        candidate_briefs=[item.model_dump() for item in payload.candidateBriefs],
    )


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
