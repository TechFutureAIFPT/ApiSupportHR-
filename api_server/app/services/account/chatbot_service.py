from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.integrations import redis_cache
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import fast_cleanup, optimized_docs, serialize


MAX_SESSIONS_PER_USER = 100
MAX_MESSAGES_PER_SESSION = 200


def _invalidate_chatbot_sessions_cache(uid: str) -> None:
    redis_cache.delete_prefix(f"chatbot_sessions:{uid}:")


def cleanup_chatbot_sessions(user: AuthenticatedUser, keep_count: int = MAX_SESSIONS_PER_USER) -> None:
    fast_cleanup(repo.chatbot_sessions(), user.uid, keep_count, timestamp_field="updatedAt")


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
    _invalidate_chatbot_sessions_cache(user.uid)
    return doc_ref.id


def build_messages_patch(snapshot: Any, messages: list[dict[str, object]]) -> dict[str, Any]:
    """Tính patch cho việc thêm message vào 1 snapshot đã fetch sẵn, không tự đọc lại document."""
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
    return {
        "messages": current_messages,
        "messageCount": len(current_messages),
        "lastMessageAt": last_message_at,
    }


def apply_session_patch(user: AuthenticatedUser, snapshot: Any, patch: dict[str, Any]) -> None:
    """Ghi 1 patch (đã gộp sẵn) vào snapshot đã fetch sẵn — 1 lệnh set(merge=True) duy nhất."""
    payload = dict(patch)
    payload["updatedAt"] = repo.server_timestamp()
    snapshot.reference.set(payload, merge=True)
    _invalidate_chatbot_sessions_cache(user.uid)


def add_chatbot_messages(user: AuthenticatedUser, session_id: str, messages: list[dict[str, object]]) -> bool:
    snapshot = get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        return False

    patch = build_messages_patch(snapshot, messages)
    apply_session_patch(user, snapshot, patch)
    return True


def update_chatbot_session_state(user: AuthenticatedUser, session_id: str, payload: dict[str, Any]) -> bool:
    snapshot = get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        return False

    apply_session_patch(user, snapshot, payload)
    return True


def get_user_chatbot_sessions(user: AuthenticatedUser, limit_count: int = 20) -> list[dict[str, object]]:
    docs = optimized_docs(repo.chatbot_sessions(), user.uid, limit_count, timestamp_field="updatedAt")
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in docs]


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
    _invalidate_chatbot_sessions_cache(user.uid)
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
