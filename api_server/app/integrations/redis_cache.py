from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ModuleNotFoundError:  # pragma: no cover - optional in isolated test envs
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Any:
    settings = get_settings()
    if Redis is None or not settings.redis_connection_url:
        return None
    return Redis.from_url(settings.redis_connection_url, decode_responses=True)


def get_json(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except RedisError:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json(key: str, payload: Any, ttl_seconds: int) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.set(key, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), ex=max(1, ttl_seconds))
        return True
    except RedisError:
        return False


def delete(key: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.delete(key)
        return True
    except RedisError:
        return False


def delete_prefix(prefix: str) -> int:
    client = get_redis_client()
    if client is None:
        return 0
    deleted = 0
    try:
        for key in client.scan_iter(match=f"{prefix}*"):
            deleted += int(client.delete(key) or 0)
    except RedisError:
        return deleted
    return deleted


def increment(key: str, ttl_seconds: int) -> int | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        value = int(client.incr(key))
        if value == 1:
            client.expire(key, max(1, ttl_seconds))
        return value
    except RedisError:
        return None


def ttl(key: str) -> int | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        value = int(client.ttl(key))
        return value if value >= 0 else None
    except RedisError:
        return None
