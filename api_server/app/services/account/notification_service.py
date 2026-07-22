from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.postgres import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import optimized_docs, serialize, to_millis


_MAX_READ_IDS = 200


def _now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _notification_id(source: str, doc_id: str) -> str:
    return f"{source}-{doc_id}"


def _format_notification(
    entry: dict[str, Any],
    read_ids: set[str],
    read_all_before: int,
) -> dict[str, Any]:
    created_at = to_millis(entry.get("timestamp") or entry.get("createdAt") or 0)
    job_position = str(entry.get("jobPosition") or "Phiên lọc CV")
    total = int(entry.get("totalCandidates") or 0)
    notif_id = _notification_id(str(entry.get("source", "cv")), str(entry.get("id", "")))
    is_read = created_at <= read_all_before or notif_id in read_ids
    return {
        "id": notif_id,
        "title": "Đã lọc hồ sơ thành công",
        "message": f"{job_position}{f' · {total} hồ sơ' if total else ''}",
        "type": "success",
        "read": is_read,
        "createdAt": created_at,
        "actionUrl": "/dashboard",
    }


def _load_read_state(user: AuthenticatedUser) -> tuple[set[str], int]:
    snapshot = repo.user_settings().document(user.uid).get()
    if not getattr(snapshot, "exists", False):
        return set(), 0
    data = snapshot.to_dict() or {}
    return (
        set(data.get("_readNotificationIds") or []),
        int(data.get("_readAllNotificationsBefore") or 0),
    )


def list_notifications(user: AuthenticatedUser, limit_count: int = 20) -> dict[str, Any]:
    per_col = min(limit_count * 2, 100)
    cv_docs = optimized_docs(repo.cv_history(), user.uid, per_col)
    sync_docs = optimized_docs(repo.synced_history(), user.uid, per_col)

    entries: list[dict[str, Any]] = []
    for source, docs in (("cv", cv_docs), ("sync", sync_docs)):
        for doc in docs:
            entries.append({"id": doc.id, "source": source, **serialize(doc.to_dict() or {})})

    entries.sort(key=lambda e: to_millis(e.get("timestamp")), reverse=True)
    read_ids, read_all_before = _load_read_state(user)
    return {
        "notifications": [
            _format_notification(entry, read_ids, read_all_before)
            for entry in entries[:limit_count]
        ]
    }


def mark_read(user: AuthenticatedUser, notification_id: str) -> None:
    doc_ref = repo.user_settings().document(user.uid)
    snapshot = doc_ref.get()
    data = (snapshot.to_dict() or {}) if getattr(snapshot, "exists", False) else {}
    read_ids = list(set(data.get("_readNotificationIds") or []) | {notification_id})
    if len(read_ids) > _MAX_READ_IDS:
        read_ids = read_ids[-_MAX_READ_IDS:]
    doc_ref.set({"_readNotificationIds": read_ids}, merge=True)


def mark_all_read(user: AuthenticatedUser) -> None:
    repo.user_settings().document(user.uid).set(
        {"_readAllNotificationsBefore": _now_millis(), "_readNotificationIds": []},
        merge=True,
    )
