from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs


MAX_SESSIONS_PER_USER = 100
MAX_MESSAGES_PER_SESSION = 200


def cleanup_chatbot_sessions(user: AuthenticatedUser, keep_count: int = MAX_SESSIONS_PER_USER) -> None:
    docs = list(repo.chatbot_sessions().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "updatedAt")
    for doc in ordered[keep_count:]:
        doc.reference.delete()


def get_owned_chatbot_session_snapshot(user: AuthenticatedUser, session_id: str):
    snapshot = repo.chatbot_sessions().document(session_id).get()
    if not snapshot.exists:
        return None

    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return None
    return snapshot


def create_chatbot_session(
    user: AuthenticatedUser,
    job_position: str,
    total_candidates: int,
    *,
    analysis_context: dict[str, Any] | None = None,
    candidate_briefs: list[dict[str, Any]] | None = None,
) -> str:
    doc_ref = repo.create_document(repo.chatbot_sessions())
    doc_ref.set(
        {
            "uid": user.uid,
            "email": user.email,
            "jobPosition": job_position,
            "totalCandidates": int(total_candidates or 0),
            "sessionTitle": f"{job_position} - {int(total_candidates or 0)} ứng viên",
            "messages": [],
            "messageCount": 0,
            "analysisContext": analysis_context or {},
            "candidateBriefs": list(candidate_briefs or []),
            "lastSuggestedCandidateIds": [],
            "lastFocusCandidateId": "",
            "createdAt": repo.server_timestamp(),
            "updatedAt": repo.server_timestamp(),
            "lastMessageAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
    )
    cleanup_chatbot_sessions(user, MAX_SESSIONS_PER_USER)
    return doc_ref.id


def add_chatbot_messages(user: AuthenticatedUser, session_id: str, messages: list[dict[str, object]]) -> bool:
    snapshot = get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        return False

    data = snapshot.to_dict() or {}
    current_messages = list(data.get("messages") or [])
    current_messages.extend(messages)
    if len(current_messages) > MAX_MESSAGES_PER_SESSION:
        current_messages = current_messages[-MAX_MESSAGES_PER_SESSION:]

    last_message_at = (
        current_messages[-1]["timestamp"]
        if current_messages
        else int(datetime.now(timezone.utc).timestamp() * 1000)
    )
    snapshot.reference.set(
        {
            "messages": current_messages,
            "messageCount": len(current_messages),
            "updatedAt": repo.server_timestamp(),
            "lastMessageAt": last_message_at,
        },
        merge=True,
    )
    return True


def update_chatbot_session_state(user: AuthenticatedUser, session_id: str, payload: dict[str, Any]) -> bool:
    snapshot = get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        return False

    next_payload = dict(payload)
    next_payload["updatedAt"] = repo.server_timestamp()
    snapshot.reference.set(next_payload, merge=True)
    return True


def get_user_chatbot_sessions(user: AuthenticatedUser, limit_count: int = 20) -> list[dict[str, object]]:
    docs = list(repo.chatbot_sessions().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "updatedAt")[:limit_count]
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in ordered]


def get_chatbot_session(user: AuthenticatedUser, session_id: str) -> dict[str, object] | None:
    snapshot = get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        return None
    data = snapshot.to_dict() or {}
    return {"id": snapshot.id, **serialize(data)}


def find_recent_chatbot_session(user: AuthenticatedUser, job_position: str) -> dict[str, object] | None:
    sessions = [session for session in get_user_chatbot_sessions(user, 100) if session.get("jobPosition") == job_position]
    return sessions[0] if sessions else None


def delete_chatbot_session(user: AuthenticatedUser, session_id: str) -> bool:
    snapshot = get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        return False
    snapshot.reference.delete()
    return True


def get_chatbot_session_stats(user: AuthenticatedUser) -> dict[str, object]:
    sessions = get_user_chatbot_sessions(user, 100)
    total_messages = sum(int(item.get("messageCount") or 0) for item in sessions)
    last_session = sessions[0] if sessions else None
    return {
        "totalSessions": len(sessions),
        "totalMessages": total_messages,
        "lastSessionTitle": (last_session or {}).get("sessionTitle"),
        "lastSessionDate": (last_session or {}).get("updatedAt"),
    }
