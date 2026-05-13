from __future__ import annotations

import hashlib
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs


POSITIVE_ACTIONS = {"like", "shortlist", "interview", "hire"}
NEGATIVE_ACTIONS = {"dislike", "reject"}


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _feedback_doc_id(user: AuthenticatedUser, payload: dict[str, Any]) -> str:
    scope_key = _first_non_empty(
        payload.get("syncHistoryId"),
        payload.get("historyId"),
        payload.get("sessionId"),
        payload.get("jdHash"),
        "global",
    )
    candidate_key = _first_non_empty(
        payload.get("candidateId"),
        payload.get("fileName"),
        payload.get("candidateName"),
        "unknown-candidate",
    )
    digest = hashlib.sha1(f"{user.uid}|{scope_key}|{candidate_key}".encode("utf-8")).hexdigest()[:24]
    return f"fb_{digest}"


def _normalize_feedback_payload(
    user: AuthenticatedUser,
    payload: dict[str, Any],
    *,
    doc_id: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = existing or {}
    action = str(payload.get("action") or current.get("action") or "").strip().lower()
    if not action:
        raise ValueError("Thiếu action feedback.")

    scope_key = _first_non_empty(
        payload.get("syncHistoryId"),
        payload.get("historyId"),
        payload.get("sessionId"),
        payload.get("jdHash"),
    )
    candidate_key = _first_non_empty(
        payload.get("candidateId"),
        payload.get("fileName"),
        payload.get("candidateName"),
    )
    if not scope_key:
        raise ValueError("Cần ít nhất một scope để gắn feedback: syncHistoryId, historyId, sessionId hoặc jdHash.")
    if not candidate_key:
        raise ValueError("Cần ít nhất một định danh ứng viên: candidateId, fileName hoặc candidateName.")

    return {
        "id": doc_id,
        "uid": user.uid,
        "userEmail": user.email,
        "displayName": user.display_name or "",
        "photoUrl": user.photo_url or "",
        "sessionId": _first_non_empty(payload.get("sessionId"), current.get("sessionId")),
        "historyId": _first_non_empty(payload.get("historyId"), current.get("historyId")),
        "syncHistoryId": _first_non_empty(payload.get("syncHistoryId"), current.get("syncHistoryId")),
        "candidateId": _first_non_empty(payload.get("candidateId"), current.get("candidateId")),
        "candidateName": _first_non_empty(payload.get("candidateName"), current.get("candidateName")),
        "fileName": _first_non_empty(payload.get("fileName"), current.get("fileName")),
        "jobPosition": _first_non_empty(payload.get("jobPosition"), current.get("jobPosition")),
        "jdHash": _first_non_empty(payload.get("jdHash"), current.get("jdHash")),
        "promptKey": _first_non_empty(payload.get("promptKey"), current.get("promptKey")),
        "promptVersion": _first_non_empty(payload.get("promptVersion"), current.get("promptVersion")),
        "modelVersion": _first_non_empty(payload.get("modelVersion"), current.get("modelVersion")),
        "action": action,
        "aiScore": payload.get("aiScore", current.get("aiScore")),
        "finalScore": payload.get("finalScore", current.get("finalScore")),
        "rank": _first_non_empty(payload.get("rank"), current.get("rank")),
        "reason": _first_non_empty(payload.get("reason"), current.get("reason")),
        "notes": _first_non_empty(payload.get("notes"), current.get("notes")),
        "metadata": payload.get("metadata") or current.get("metadata") or {},
        "createdAt": current.get("createdAt") or repo.server_timestamp(),
        "updatedAt": repo.server_timestamp(),
    }


def save_feedback(user: AuthenticatedUser, payload: dict[str, Any]) -> str:
    doc_id = _feedback_doc_id(user, payload)
    doc_ref = repo.analysis_feedback().document(doc_id)
    snapshot = doc_ref.get()
    current = snapshot.to_dict() or {}
    normalized = _normalize_feedback_payload(user, payload, doc_id=doc_id, existing=current)
    doc_ref.set(normalized, merge=True)
    return doc_id


def list_feedback(
    user: AuthenticatedUser,
    *,
    limit_count: int = 50,
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
    candidate_id: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    docs = list(repo.analysis_feedback().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "updatedAt")
    normalized_action = (action or "").strip().lower()
    items: list[dict[str, Any]] = []
    for doc in ordered:
        data = serialize(doc.to_dict() or {})
        if session_id and data.get("sessionId") != session_id:
            continue
        if history_id and data.get("historyId") != history_id:
            continue
        if sync_history_id and data.get("syncHistoryId") != sync_history_id:
            continue
        if candidate_id and data.get("candidateId") != candidate_id:
            continue
        if normalized_action and str(data.get("action") or "").lower() != normalized_action:
            continue
        items.append({**data, "id": doc.id})
        if len(items) >= limit_count:
            break
    return items


def get_feedback_by_id(user: AuthenticatedUser, feedback_id: str) -> dict[str, Any] | None:
    snapshot = repo.analysis_feedback().document(feedback_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return None
    return {**serialize(data), "id": snapshot.id}


def delete_feedback(user: AuthenticatedUser, feedback_id: str) -> bool:
    snapshot = repo.analysis_feedback().document(feedback_id).get()
    if not snapshot.exists:
        return False
    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return False
    snapshot.reference.delete()
    return True


def get_feedback_stats(
    user: AuthenticatedUser,
    *,
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
) -> dict[str, Any]:
    entries = list_feedback(
        user,
        limit_count=1000,
        session_id=session_id,
        history_id=history_id,
        sync_history_id=sync_history_id,
    )
    actions_count: dict[str, int] = {}
    for item in entries:
        action = str(item.get("action") or "").lower() or "unknown"
        actions_count[action] = actions_count.get(action, 0) + 1

    positive_count = sum(actions_count.get(action, 0) for action in POSITIVE_ACTIONS)
    negative_count = sum(actions_count.get(action, 0) for action in NEGATIVE_ACTIONS)

    return {
        "totalFeedback": len(entries),
        "actionsCount": actions_count,
        "positiveCount": positive_count,
        "negativeCount": negative_count,
        "latestFeedbackAt": entries[0].get("updatedAt") if entries else None,
        "recentEntries": entries[:5],
    }
