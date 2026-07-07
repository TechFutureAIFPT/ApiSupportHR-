from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.core.config import get_settings
from app.integrations import redis_cache
from app.services.account.shared import serialize


@dataclass
class CachedPayload:
    payload: Any
    revision: str
    generated_at: int
    cache_hit: bool = False


def _stable_json(value: Any) -> str:
    return json.dumps(serialize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def build_revision(namespace: str, value: Any) -> str:
    digest = hashlib.sha256(f"{namespace}:{_stable_json(value)}".encode("utf-8")).hexdigest()
    return digest[:24]


def build_etag(revision: str) -> str:
    return f"\"{revision}\""


def normalize_if_none_match(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().strip('"')


def now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def get_ttl_seconds(kind: str) -> int:
    settings = get_settings()
    if kind == "mobile_inbox":
        return settings.mobile_inbox_cache_ttl_seconds
    if kind == "templates":
        return settings.template_cache_ttl_seconds
    if kind == "sync_cache":
        return settings.sync_cache_ttl_seconds
    return settings.account_cache_ttl_seconds


def read_cached_payload(key: str) -> CachedPayload | None:
    cached = redis_cache.get_json(key)
    if not isinstance(cached, dict):
        return None
    revision = str(cached.get("revision") or "").strip()
    if not revision:
        return None
    return CachedPayload(
        payload=cached.get("payload"),
        revision=revision,
        generated_at=int(cached.get("generatedAt") or now_millis()),
        cache_hit=True,
    )


def write_cached_payload(key: str, kind: str, payload: Any, revision: str | None = None) -> CachedPayload:
    final_revision = revision or build_revision(kind, payload)
    envelope = {
        "payload": payload,
        "revision": final_revision,
        "generatedAt": now_millis(),
    }
    redis_cache.set_json(key, envelope, get_ttl_seconds(kind))
    return CachedPayload(
        payload=payload,
        revision=final_revision,
        generated_at=int(envelope["generatedAt"]),
        cache_hit=False,
    )


def get_or_build_cached_payload(
    key: str,
    kind: str,
    builder: Callable[[], Any],
    *,
    revision: str | None = None,
) -> CachedPayload:
    cached = read_cached_payload(key)
    if cached is not None:
        return cached
    payload = builder()
    return write_cached_payload(key, kind, payload, revision=revision)


def account_cache_key(prefix: str, uid: str, *parts: str) -> str:
    safe_parts = [prefix, uid, *[part or "self" for part in parts]]
    return ":".join(item.replace(" ", "_") for item in safe_parts)


def invalidate_user_account_cache(uid: str) -> None:
    for prefix in (
        f"mobile_inbox:{uid}:",
        f"history:{uid}:",
        f"sync_history:{uid}:",
        f"templates:{uid}:",
        f"sync_cache:{uid}:",
    ):
        redis_cache.delete_prefix(prefix)
