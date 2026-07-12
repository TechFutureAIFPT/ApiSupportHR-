from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.integrations import redis_cache
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import view_sync_service
from app.services.account.shared import serialize, sorted_docs


logger = logging.getLogger("app.firestore.feedback")

POSITIVE_ACTIONS = {"like", "shortlist", "interview", "hire"}
NEGATIVE_ACTIONS = {"dislike", "reject"}
ALL_KNOWN_ACTIONS = sorted(POSITIVE_ACTIONS | NEGATIVE_ACTIONS)
HIGH_SEVERITY_SCORE_DELTA = 15.0
MEDIUM_SEVERITY_SCORE_DELTA = 8.0


def _invalidate_feedback_cache(uid: str) -> None:
    redis_cache.delete_prefix(f"feedback:{uid}:")


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_feedback_metadata(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    current_metadata = current.get("metadata")
    payload_metadata = payload.get("metadata")
    if isinstance(current_metadata, dict):
        normalized.update(current_metadata)
    if isinstance(payload_metadata, dict):
        normalized.update(payload_metadata)
    return normalized


def _derive_feedback_severity(ai_score: Any, final_score: Any, existing: Any = None) -> str:
    ai_score_value = _to_float(ai_score)
    final_score_value = _to_float(final_score)

    if ai_score_value is None or final_score_value is None:
        existing_value = str(existing or "").strip().lower()
        if existing_value in {"low", "medium", "high"}:
            return existing_value
        return "low"

    delta = abs(final_score_value - ai_score_value)
    if delta >= HIGH_SEVERITY_SCORE_DELTA:
        return "high"
    if delta >= MEDIUM_SEVERITY_SCORE_DELTA:
        return "medium"
    return "low"


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
    current_metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
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
        raise ValueError("Cần ít nhất một phạm vi để gắn feedback: syncHistoryId, historyId, sessionId hoặc jdHash.")
    if not candidate_key:
        raise ValueError("Cần ít nhất một định danh ứng viên: candidateId, fileName hoặc candidateName.")

    ai_score = payload.get("aiScore", current.get("aiScore"))
    final_score = payload.get("finalScore", current.get("finalScore"))
    is_reusable_guidance = _coerce_bool(
        payload.get("isReusableGuidance", payload_metadata.get("isReusableGuidance")),
        default=_coerce_bool(
            current.get("isReusableGuidance", current_metadata.get("isReusableGuidance")),
            default=False,
        ),
    )
    metadata = _normalize_feedback_metadata(payload, current)
    metadata["feedbackScope"] = "reusable-guidance" if is_reusable_guidance else "single-candidate"
    if metadata.get("scoreDifference") is None:
        ai_score_value = _to_float(ai_score)
        final_score_value = _to_float(final_score)
        if ai_score_value is not None and final_score_value is not None:
            metadata["scoreDifference"] = final_score_value - ai_score_value

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
        "aiScore": ai_score,
        "finalScore": final_score,
        "isReusableGuidance": is_reusable_guidance,
        "severity": _derive_feedback_severity(ai_score, final_score, current.get("severity")),
        "rank": _first_non_empty(payload.get("rank"), current.get("rank")),
        "reason": _first_non_empty(payload.get("reason"), current.get("reason")),
        "notes": _first_non_empty(payload.get("notes"), current.get("notes")),
        "metadata": metadata,
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
    view_sync_service.refresh_user_views(user, "feedback", rebuild_mobile_inbox=True)
    _invalidate_feedback_cache(user.uid)
    return doc_id


def _build_feedback_query(
    user: AuthenticatedUser,
    *,
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
    candidate_id: str | None = None,
    action: str | None = None,
) -> Any:
    query = repo.analysis_feedback().where("uid", "==", user.uid)
    if sync_history_id:
        query = query.where("syncHistoryId", "==", sync_history_id)
    if history_id:
        query = query.where("historyId", "==", history_id)
    if session_id:
        query = query.where("sessionId", "==", session_id)
    if candidate_id:
        query = query.where("candidateId", "==", candidate_id)
    normalized_action = (action or "").strip().lower()
    if normalized_action:
        query = query.where("action", "==", normalized_action)
    return query


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
    query = _build_feedback_query(
        user,
        session_id=session_id,
        history_id=history_id,
        sync_history_id=sync_history_id,
        candidate_id=candidate_id,
        action=action,
    )
    try:
        docs = list(query.order_by("updatedAt", direction="DESCENDING").limit(limit_count).stream())
    except Exception as exc:
        logger.warning("feedback fallback to full-scan uid=%s error=%s", user.uid, exc)
        docs = sorted_docs(list(query.stream()), "updatedAt")[:limit_count]

    return [{**serialize(doc.to_dict() or {}), "id": doc.id} for doc in docs]


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
    view_sync_service.refresh_user_views(user, "feedback", rebuild_mobile_inbox=True)
    _invalidate_feedback_cache(user.uid)
    return True


def get_feedback_stats(
    user: AuthenticatedUser,
    *,
    session_id: str | None = None,
    history_id: str | None = None,
    sync_history_id: str | None = None,
) -> dict[str, Any]:
    base_query = _build_feedback_query(
        user, session_id=session_id, history_id=history_id, sync_history_id=sync_history_id,
    )
    total = int(base_query.count().get()[0][0].value)
    actions_count: dict[str, int] = {}
    for action in ALL_KNOWN_ACTIONS:
        count = int(base_query.where("action", "==", action).count().get()[0][0].value)
        if count > 0:
            actions_count[action] = count
    positive_count = sum(actions_count.get(action, 0) for action in POSITIVE_ACTIONS)
    negative_count = sum(actions_count.get(action, 0) for action in NEGATIVE_ACTIONS)

    recent_entries = list_feedback(
        user, limit_count=5, session_id=session_id, history_id=history_id, sync_history_id=sync_history_id,
    )

    return {
        "totalFeedback": total,
        "actionsCount": actions_count,
        "positiveCount": positive_count,
        "negativeCount": negative_count,
        "latestFeedbackAt": recent_entries[0].get("updatedAt") if recent_entries else None,
        "recentEntries": recent_entries,
    }
