from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from app.integrations import redis_cache
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import response_cache_service
from app.services.account.response_cache_service import CachedPayload
from app.services.account.shared import serialize


SETTINGS_VERSION = 1
ALLOWED_HISTORY_RETENTION = {50, 100, 200}


class SettingsWriteConflict(RuntimeError):
    pass


class SettingsWriteBusy(RuntimeError):
    pass


def _now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _history_retention(value: Any, fallback: int = 50) -> int:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return fallback
    return candidate if candidate in ALLOWED_HISTORY_RETENTION else fallback


def _millis(value: Any, fallback: int) -> int:
    if isinstance(value, (int, float)) and isfinite(value):
        return int(value)
    return fallback


def _normalize_fixed_jd(value: Any) -> dict[str, Any] | None:
    fixed_jd = _record(value)
    if not fixed_jd:
        return None

    return {
        "enabled": _bool(fixed_jd.get("enabled"), False),
        "name": str(fixed_jd.get("name") or ""),
        "jdText": str(fixed_jd.get("jdText") or "").strip(),
        "savedAt": _millis(fixed_jd.get("savedAt"), _now_millis()),
        "scoringEnabled": _bool(fixed_jd.get("scoringEnabled"), False),
        "roleKey": str(fixed_jd.get("roleKey") or ""),
        "rubricVersion": str(fixed_jd.get("rubricVersion") or ""),
        "weights": deepcopy(_record(fixed_jd.get("weights"))) if isinstance(fixed_jd.get("weights"), dict) else None,
        "hardFilters": deepcopy(_record(fixed_jd.get("hardFilters"))) if isinstance(fixed_jd.get("hardFilters"), dict) else None,
    }


def default_user_settings(user: AuthenticatedUser) -> dict[str, Any]:
    return {
        "version": SETTINGS_VERSION,
        "ui": {
            "sidebarDensity": "compact",
            "accessibleMode": False,
            "reducedMotion": False,
            "language": "vi-VN",
            "theme": "light",
        },
        "account": {
            "displayName": user.display_name or "",
            "avatar": user.photo_url or None,
            "email": user.email or "",
        },
        "workflow": {
            "autoSaveDraft": True,
            "restoreDraft": True,
            "rememberScoringConfig": True,
            "autoSaveHistory": True,
            "ocrByDefault": False,
            "autoFillHardFiltersOnContinue": False,
            "newSessionMode": "reset",
        },
        "notifications": {
            "analysisComplete": True,
            "syncErrors": True,
            "historySaved": True,
            "sidebarBadge": True,
            "inAppOnly": True,
        },
        "sync": {
            "autoSync": True,
            "historyRetention": 50,
            "lastSyncedAt": None,
        },
    }


def normalize_user_settings(raw: Any, user: AuthenticatedUser) -> dict[str, Any]:
    defaults = default_user_settings(user)
    payload = _record(raw)
    if isinstance(payload.get("settings"), dict):
        payload = _record(payload.get("settings"))

    ui = _record(payload.get("ui"))
    account = _record(payload.get("account"))
    workflow = _record(payload.get("workflow"))
    notifications = _record(payload.get("notifications"))
    sync = _record(payload.get("sync"))

    density = ui.get("sidebarDensity", defaults["ui"]["sidebarDensity"])
    new_session_mode = workflow.get("newSessionMode", defaults["workflow"]["newSessionMode"])
    fixed_jd = _normalize_fixed_jd(workflow.get("fixedJD"))

    normalized = {
        "version": SETTINGS_VERSION,
        "ui": {
            "sidebarDensity": "cozy" if density == "cozy" else "compact",
            "accessibleMode": _bool(ui.get("accessibleMode"), defaults["ui"]["accessibleMode"]),
            "reducedMotion": _bool(ui.get("reducedMotion"), defaults["ui"]["reducedMotion"]),
            # Theme and language are product-level values, not account-editable settings yet.
            "language": defaults["ui"]["language"],
            "theme": defaults["ui"]["theme"],
        },
        "account": {
            "displayName": str(account.get("displayName") or user.display_name or defaults["account"]["displayName"]),
            "avatar": account.get("avatar") if account.get("avatar") is None else str(account.get("avatar") or user.photo_url or "") or None,
            "email": str(account.get("email") or user.email or defaults["account"]["email"]),
        },
        "workflow": {
            "autoSaveDraft": _bool(workflow.get("autoSaveDraft"), defaults["workflow"]["autoSaveDraft"]),
            "restoreDraft": _bool(workflow.get("restoreDraft"), defaults["workflow"]["restoreDraft"]),
            "rememberScoringConfig": _bool(workflow.get("rememberScoringConfig"), defaults["workflow"]["rememberScoringConfig"]),
            "autoSaveHistory": _bool(workflow.get("autoSaveHistory"), defaults["workflow"]["autoSaveHistory"]),
            "ocrByDefault": _bool(workflow.get("ocrByDefault"), defaults["workflow"]["ocrByDefault"]),
            "autoFillHardFiltersOnContinue": _bool(
                workflow.get("autoFillHardFiltersOnContinue"),
                defaults["workflow"]["autoFillHardFiltersOnContinue"],
            ),
            "newSessionMode": "keep-config" if new_session_mode == "keep-config" else "reset",
        },
        "notifications": {
            "analysisComplete": _bool(notifications.get("analysisComplete"), defaults["notifications"]["analysisComplete"]),
            "syncErrors": _bool(notifications.get("syncErrors"), defaults["notifications"]["syncErrors"]),
            "historySaved": _bool(notifications.get("historySaved"), defaults["notifications"]["historySaved"]),
            "sidebarBadge": _bool(notifications.get("sidebarBadge"), defaults["notifications"]["sidebarBadge"]),
            "inAppOnly": True,
        },
        "sync": {
            "autoSync": _bool(sync.get("autoSync"), defaults["sync"]["autoSync"]),
            "historyRetention": _history_retention(sync.get("historyRetention"), defaults["sync"]["historyRetention"]),
            "lastSyncedAt": sync.get("lastSyncedAt") if isinstance(sync.get("lastSyncedAt"), (int, float)) else defaults["sync"]["lastSyncedAt"],
        },
    }

    if fixed_jd is not None:
        normalized["workflow"]["fixedJD"] = fixed_jd

    return normalized


def merge_user_settings(base: dict[str, Any], patch: dict[str, Any], user: AuthenticatedUser) -> dict[str, Any]:
    merged = deepcopy(base)
    payload = _record(patch)
    if isinstance(payload.get("settings"), dict):
        payload = _record(payload.get("settings"))

    for group in ("ui", "account", "workflow", "notifications", "sync"):
        if isinstance(payload.get(group), dict):
            merged[group] = {**_record(merged.get(group)), **_record(payload.get(group))}

    return normalize_user_settings(merged, user)


def _document_payload(user: AuthenticatedUser, settings: dict[str, Any], include_created_at: bool) -> dict[str, Any]:
    payload = {
        "uid": user.uid,
        "email": settings["account"]["email"] or user.email,
        "version": SETTINGS_VERSION,
        "settings": settings,
        "updatedAt": repo.server_timestamp(),
    }
    if include_created_at:
        payload["createdAt"] = repo.server_timestamp()
    return payload


def _cache_key(user: AuthenticatedUser) -> str:
    return response_cache_service.account_cache_key("settings", user.uid)


def _load_user_settings(
    user: AuthenticatedUser,
    *,
    persist_default: bool,
) -> tuple[CachedPayload, bool]:
    cache_key = _cache_key(user)
    cached = response_cache_service.read_cached_payload(cache_key)
    if cached is not None and isinstance(cached.payload, dict):
        return cached, True

    doc_ref = repo.user_settings().document(user.uid)
    snapshot = doc_ref.get()
    exists = bool(getattr(snapshot, "exists", False))
    if not exists:
        settings = default_user_settings(user)
        if persist_default:
            doc_ref.set(_document_payload(user, settings, include_created_at=True))
    else:
        data = snapshot.to_dict() or {}
        settings = normalize_user_settings(serialize(data.get("settings") or data), user)
    return response_cache_service.write_cached_payload(cache_key, "settings", settings), exists


def get_user_settings_response(user: AuthenticatedUser) -> CachedPayload:
    cached, _ = _load_user_settings(user, persist_default=True)
    return cached


def get_user_settings(user: AuthenticatedUser) -> dict[str, Any]:
    return get_user_settings_response(user).payload


def _assert_expected_revision(expected_revision: str | None, current_revision: str) -> None:
    normalized = response_cache_service.normalize_if_none_match(expected_revision)
    if not normalized or normalized == "*":
        return
    if normalized != current_revision:
        raise SettingsWriteConflict("Settings changed on another device. Reload before saving again.")


def save_user_settings_response(
    user: AuthenticatedUser,
    patch: dict[str, Any],
    *,
    expected_revision: str | None = None,
) -> CachedPayload:
    lock_key = f"lock:settings:{user.uid}"
    with redis_cache.distributed_lock(lock_key, ttl_seconds=10, wait_timeout_seconds=1.5) as acquired:
        if not acquired:
            raise SettingsWriteBusy("Another settings update is still being committed.")
        current_cached, exists = _load_user_settings(user, persist_default=False)
        _assert_expected_revision(expected_revision, current_cached.revision)
        current = normalize_user_settings(current_cached.payload, user)
        settings = merge_user_settings(current, patch, user)
        settings["sync"]["lastSyncedAt"] = _now_millis()

        repo.user_settings().document(user.uid).set(
            _document_payload(user, settings, include_created_at=not exists),
            merge=exists,
        )
        return response_cache_service.write_cached_payload(_cache_key(user), "settings", settings)


def save_user_settings(user: AuthenticatedUser, patch: dict[str, Any]) -> dict[str, Any]:
    return save_user_settings_response(user, patch).payload


def reset_user_settings_response(
    user: AuthenticatedUser,
    *,
    expected_revision: str | None = None,
) -> CachedPayload:
    lock_key = f"lock:settings:{user.uid}"
    with redis_cache.distributed_lock(lock_key, ttl_seconds=10, wait_timeout_seconds=1.5) as acquired:
        if not acquired:
            raise SettingsWriteBusy("Another settings update is still being committed.")
        current_cached, exists = _load_user_settings(user, persist_default=False)
        _assert_expected_revision(expected_revision, current_cached.revision)
        settings = default_user_settings(user)
        settings["sync"]["lastSyncedAt"] = _now_millis()
        repo.user_settings().document(user.uid).set(
            _document_payload(user, settings, include_created_at=not exists),
            merge=exists,
        )
        return response_cache_service.write_cached_payload(_cache_key(user), "settings", settings)


def reset_user_settings(user: AuthenticatedUser) -> dict[str, Any]:
    return reset_user_settings_response(user).payload
