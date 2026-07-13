from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize


SETTINGS_VERSION = 1
ALLOWED_HISTORY_RETENTION = {50, 100, 200}
ALLOWED_THEMES = {"light", "dark", "system"}
ALLOWED_LANGUAGES = {"vi-VN", "en-US"}


def _now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _enum(value: Any, allowed: set[str], fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


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
            "language": _enum(ui.get("language"), ALLOWED_LANGUAGES, defaults["ui"]["language"]),
            "theme": _enum(ui.get("theme"), ALLOWED_THEMES, defaults["ui"]["theme"]),
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


def get_user_settings(user: AuthenticatedUser) -> dict[str, Any]:
    doc_ref = repo.user_settings().document(user.uid)
    snapshot = doc_ref.get()
    exists = bool(getattr(snapshot, "exists", False))
    if not exists:
        settings = default_user_settings(user)
        doc_ref.set(_document_payload(user, settings, include_created_at=True))
        return settings
    data = snapshot.to_dict() or {}
    return normalize_user_settings(serialize(data.get("settings") or data), user)


def save_user_settings(user: AuthenticatedUser, patch: dict[str, Any]) -> dict[str, Any]:
    doc_ref = repo.user_settings().document(user.uid)
    snapshot = doc_ref.get()
    exists = bool(getattr(snapshot, "exists", False))
    current = normalize_user_settings((snapshot.to_dict() or {}).get("settings") if exists else {}, user)
    settings = merge_user_settings(current, patch, user)
    settings["sync"]["lastSyncedAt"] = _now_millis()

    doc_ref.set(_document_payload(user, settings, include_created_at=not exists), merge=exists)
    return settings


def reset_user_settings(user: AuthenticatedUser) -> dict[str, Any]:
    doc_ref = repo.user_settings().document(user.uid)
    snapshot = doc_ref.get()
    exists = bool(getattr(snapshot, "exists", False))
    settings = default_user_settings(user)
    settings["sync"]["lastSyncedAt"] = _now_millis()
    doc_ref.set(_document_payload(user, settings, include_created_at=not exists), merge=exists)
    return settings
