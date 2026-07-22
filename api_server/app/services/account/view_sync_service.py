from __future__ import annotations

from app.integrations import redis_cache
from app.repositories.postgres import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import response_cache_service, sync_state_service


MOBILE_INBOX_REBUILD_DEBOUNCE_SECONDS = 4


def refresh_user_views(
    user: AuthenticatedUser,
    source: sync_state_service.SyncSource,
    *,
    rebuild_mobile_inbox: bool = False,
) -> str:
    response_cache_service.invalidate_user_account_cache(user.uid)
    revision: str | None = None

    if rebuild_mobile_inbox:
        # Debounce: nếu user vừa trigger rebuild trong vài giây gần đây (vd nhiều candidate
        # sync liên tiếp từ 1 batch phân tích), chỉ rebuild 1 lần — các lần khác chỉ invalidate
        # cache đọc ở trên; fetch_mobile_inbox tự fallback build trực tiếp khi cache miss.
        lock_key = f"mobile_inbox_rebuild_lock:{user.uid}"
        if redis_cache.acquire_lock(lock_key, MOBILE_INBOX_REBUILD_DEBOUNCE_SECONDS):
            try:
                from app.services.account import history_service

                view_document = history_service.build_mobile_inbox_view_document(user)
                repo.mobile_inbox_views().document(history_service.mobile_inbox_view_doc_id(user)).set(view_document)
                revision = str(view_document.get("revision") or "").strip() or None
            except Exception:
                revision = None

    try:
        return sync_state_service.touch_user_sync_state(user, source, latest_revision=revision)
    except Exception:
        return revision or ""
