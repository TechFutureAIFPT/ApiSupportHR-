from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import view_sync_service
from app.services.account.shared import fast_cleanup, optimized_docs, serialize, sorted_docs


MAX_CACHE_ENTRIES_PER_USER = 50
CACHE_EXPIRY_DAYS = 30


def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip()
    else:
        normalized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_cv_jd_cache_key(cv_id: str, jd_text: str) -> str:
    normalized_cv_id = str(cv_id or "").strip()
    normalized_jd = str(jd_text or "").strip()
    return stable_hash(f"{normalized_cv_id}::{normalized_jd}")


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
    view_sync_service.refresh_user_views(user, "cache", rebuild_mobile_inbox=False)


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


async def get_cache_entry_async(user: AuthenticatedUser, cache_key: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(get_cache_entry, user, cache_key)


async def sync_cache_entry_async(
    user: AuthenticatedUser,
    cache_key: str,
    candidate_data: dict[str, Any],
    jd_hash: str,
    weights_hash: str,
    filters_hash: str,
    file_info: dict[str, Any],
) -> None:
    await asyncio.to_thread(
        sync_cache_entry,
        user,
        cache_key,
        candidate_data,
        jd_hash,
        weights_hash,
        filters_hash,
        file_info,
    )


def get_all_user_cache(user: AuthenticatedUser) -> dict[str, Any]:
    docs = optimized_docs(repo.synced_cache(), user.uid, MAX_CACHE_ENTRIES_PER_USER + 10)
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
    while True:
        docs = list(repo.synced_cache().where("uid", "==", user.uid).limit(100).stream())
        if not docs:
            break
        for doc in docs:
            doc.reference.delete()
    view_sync_service.refresh_user_views(user, "cache", rebuild_mobile_inbox=False)


def cleanup_user_cache(user: AuthenticatedUser, keep_count: int = MAX_CACHE_ENTRIES_PER_USER) -> None:
    fast_cleanup(repo.synced_cache(), user.uid, keep_count)
