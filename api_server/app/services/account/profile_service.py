from __future__ import annotations

from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import fast_cleanup, optimized_docs, serialize, sorted_docs


MAX_HISTORY_ENTRIES_PER_USER = 100


def cleanup_profile_cv_history(user: AuthenticatedUser, keep_count: int = MAX_HISTORY_ENTRIES_PER_USER) -> None:
    scan_limit = keep_count + 30
    docs = optimized_docs(repo.cv_history(), user.uid, scan_limit)
    excess = docs[keep_count:]
    if not excess:
        return
    for doc in excess:
        data = doc.to_dict() or {}
        if "jdText" not in data and "jdTitle" not in data:
            continue
        doc.reference.delete()
    if len(docs) == scan_limit:
        keep_ids = {doc.id for doc in docs[:keep_count]}
        for doc in repo.cv_history().where("uid", "==", user.uid).stream():
            if doc.id not in keep_ids:
                data = doc.to_dict() or {}
                if "jdText" not in data and "jdTitle" not in data:
                    continue
                doc.reference.delete()


def upsert_user_profile(
    user: AuthenticatedUser,
    email: str | None = None,
    display_name: str | None = None,
    avatar: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    profile_ref = repo.users().document(user.uid)
    snapshot = profile_ref.get()
    current = snapshot.to_dict() if snapshot.exists else {}
    merged_email = email or user.email or current.get("email") or ""
    merged_name = display_name or user.display_name or current.get("displayName") or ""
    merged_avatar = avatar or user.photo_url or current.get("avatar") or ""

    payload = {
        "uid": user.uid,
        "email": merged_email,
        "displayName": merged_name,
        "avatar": merged_avatar,
        "provider": provider or current.get("provider") or "",
        "updatedAt": repo.server_timestamp(),
    }

    if snapshot.exists:
        profile_ref.set(payload, merge=True)
    else:
        payload["createdAt"] = repo.server_timestamp()
        profile_ref.set(payload)

    return get_user_profile(user) or {}


def get_user_profile(user: AuthenticatedUser) -> dict[str, Any] | None:
    snapshot = repo.users().document(user.uid).get()
    if not snapshot.exists:
        return None
    return serialize(snapshot.to_dict())


def update_user_avatar(user: AuthenticatedUser, avatar: str) -> dict[str, Any]:
    repo.users().document(user.uid).set({"avatar": avatar, "updatedAt": repo.server_timestamp()}, merge=True)
    return get_user_profile(user) or {}


def save_cv_history(user: AuthenticatedUser, email: str, jd_text: str, jd_title: str, cv_count: int, results: list[Any]) -> str:
    doc_ref = repo.create_document(repo.cv_history())
    doc_ref.set(
        {
            "uid": user.uid,
            "email": email or user.email,
            "jdText": jd_text or "",
            "jdTitle": jd_title or "Vị trí tuyển dụng",
            "cvCount": int(cv_count or 0),
            "results": [item for item in results if item is not None],
            "timestamp": repo.server_timestamp(),
        }
    )
    cleanup_profile_cv_history(user, MAX_HISTORY_ENTRIES_PER_USER)
    return doc_ref.id


def get_user_cv_history(user: AuthenticatedUser, limit_count: int = 50) -> list[dict[str, Any]]:
    docs = optimized_docs(repo.cv_history(), user.uid, limit_count + 20)
    items: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if "jdText" not in data and "jdTitle" not in data:
            continue
        items.append({"id": doc.id, **serialize(data)})
        if len(items) >= limit_count:
            break
    return items


def migrate_local_data(user: AuthenticatedUser, avatar: str | None, history: list[dict[str, Any]]) -> dict[str, Any]:
    if avatar:
        update_user_avatar(user, avatar)

    migrated = 0
    for entry in history:
        save_cv_history(
            user=user,
            email=user.email,
            jd_text=str(entry.get("jdText") or ""),
            jd_title=str(entry.get("jdTitle") or "Vị trí tuyển dụng"),
            cv_count=int(entry.get("cvCount") or 0),
            results=list(entry.get("results") or []),
        )
        migrated += 1

    return {"migratedHistoryCount": migrated, "avatarUpdated": bool(avatar)}
