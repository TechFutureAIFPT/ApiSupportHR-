from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs


MAX_CACHE_ENTRIES_PER_USER = 50
CACHE_EXPIRY_DAYS = 30


def sync_cache_entry(
    user: AuthenticatedUser,
    cache_key: str,
    candidate_data: dict[str, Any],
    jd_hash: str,
    weights_hash: str,
    filters_hash: str,
    file_info: dict[str, Any],
) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(days=CACHE_EXPIRY_DAYS)
    doc_id = f"{user.uid}_{cache_key}"
    repo.synced_cache().document(doc_id).set(
        {
            "uid": user.uid,
            "email": user.email,
            "displayName": user.display_name or "",
            "photoURL": user.photo_url or "",
            "cacheKey": cache_key,
            "candidateData": candidate_data,
            "timestamp": repo.server_timestamp(),
            "jdHash": jd_hash,
            "weightsHash": weights_hash,
            "filtersHash": filters_hash,
            "fileInfo": {
                "name": str(file_info.get("name") or ""),
                "size": int(file_info.get("size") or 0),
                "lastModified": int(file_info.get("lastModified") or 0),
            },
            "expiresAt": expires_at,
            "lastValidatedAt": repo.server_timestamp(),
        }
    )
    cleanup_user_cache(user, MAX_CACHE_ENTRIES_PER_USER)


def get_cache_entry(user: AuthenticatedUser, cache_key: str) -> dict[str, Any] | None:
    snapshot = repo.synced_cache().document(f"{user.uid}_{cache_key}").get()
    if not snapshot.exists:
        return None

    data = snapshot.to_dict() or {}
    expires_at = data.get("expiresAt")
    if isinstance(expires_at, datetime) and datetime.now(timezone.utc) > expires_at:
        snapshot.reference.delete()
        return None

    return serialize(data.get("candidateData"))


def get_all_user_cache(user: AuthenticatedUser) -> dict[str, Any]:
    docs = list(repo.synced_cache().where("uid", "==", user.uid).stream())
    now = datetime.now(timezone.utc)
    cache_map: dict[str, Any] = {}
    for doc in docs:
        data = doc.to_dict() or {}
        expires_at = data.get("expiresAt")
        if isinstance(expires_at, datetime) and now > expires_at:
            doc.reference.delete()
            continue
        cache_map[str(data.get("cacheKey") or doc.id)] = serialize(data.get("candidateData"))
    return cache_map


def clear_user_cache(user: AuthenticatedUser) -> None:
    docs = list(repo.synced_cache().where("uid", "==", user.uid).stream())
    for doc in docs:
        doc.reference.delete()


def cleanup_user_cache(user: AuthenticatedUser, keep_count: int = MAX_CACHE_ENTRIES_PER_USER) -> None:
    docs = list(repo.synced_cache().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "timestamp")
    for doc in ordered[keep_count:]:
        doc.reference.delete()
