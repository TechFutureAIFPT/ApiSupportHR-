from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

try:
    from redis import Redis
    from redis.exceptions import RedisError, ResponseError
except ModuleNotFoundError:  # pragma: no cover - optional in isolated test envs
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass

    class ResponseError(RedisError):
        pass

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Any:
    settings = get_settings()
    if Redis is None or not settings.redis_connection_url:
        return None
    return Redis.from_url(
        settings.redis_connection_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_connect_timeout=max(0.1, settings.redis_connect_timeout_seconds),
        socket_timeout=max(0.1, settings.redis_socket_timeout_seconds),
        socket_keepalive=True,
        retry_on_timeout=True,
        health_check_interval=30,
    )


def close_redis_client() -> None:
    if not get_redis_client.cache_info().currsize:
        return
    client = get_redis_client()
    if client is not None:
        client.close()
    get_redis_client.cache_clear()


def ping() -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except RedisError:
        return False


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
        batch: list[str] = []
        for key in client.scan_iter(match=f"{prefix}*", count=200):
            batch.append(key)
            if len(batch) >= 200:
                deleted += int(client.unlink(*batch) or 0)
                batch.clear()
        if batch:
            deleted += int(client.unlink(*batch) or 0)
    except RedisError:
        return deleted
    return deleted


@contextmanager
def distributed_lock(
    key: str,
    *,
    ttl_seconds: int = 10,
    wait_timeout_seconds: float = 1.5,
):
    """Short owner-safe Redis lock; degrades to an acquired lock without Redis."""
    client = get_redis_client()
    if client is None:
        yield True
        return

    token = uuid.uuid4().hex
    deadline = time.monotonic() + max(0.0, wait_timeout_seconds)
    acquired = False
    try:
        while time.monotonic() <= deadline:
            try:
                acquired = bool(client.set(key, token, nx=True, ex=max(1, ttl_seconds)))
            except RedisError:
                # Cache/locking must never make the database unavailable.
                yield True
                return
            if acquired:
                break
            time.sleep(0.02)
        yield acquired
    finally:
        if acquired:
            try:
                client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    key,
                    token,
                )
            except RedisError:
                pass


def acquire_lock(key: str, ttl_seconds: int) -> bool:
    """SET NX EX ngắn hạn dùng để debounce công việc nặng (vd rebuild view) khi cùng 1 user
    kích hoạt nhiều lần liên tiếp trong vài giây. Trả True nếu lock vừa được acquire (nên chạy),
    False nếu đã có lock (nên bỏ qua). Nếu Redis không khả dụng, luôn trả True (không debounce
    được thì vẫn ưu tiên chạy đủ, an toàn hơn là bỏ sót việc cần làm)."""
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(key, "1", nx=True, ex=max(1, ttl_seconds)))
    except RedisError:
        return True


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


def push_json(key: str, payload: Any) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.rpush(key, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return True
    except (RedisError, TypeError, ValueError):
        return False


def blocking_pop_json(key: str, timeout_seconds: int = 5) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        item = client.blpop([key], timeout=max(1, timeout_seconds))
    except RedisError:
        return None
    if not item:
        return None
    try:
        return json.loads(item[1])
    except (json.JSONDecodeError, TypeError):
        return None


def acquire_slot(key: str, token: str, limit: int, lease_seconds: int) -> bool | None:
    """Acquire one distributed concurrency slot backed by a Redis sorted set."""
    client = get_redis_client()
    if client is None:
        return None
    now = time.time()
    script = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
    if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
      return 0
    end
    redis.call('ZADD', KEYS[1], ARGV[2], ARGV[4])
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
    return 1
    """
    try:
        acquired = client.eval(
            script,
            1,
            key,
            now,
            now + max(1, lease_seconds),
            max(1, limit),
            token,
            max(1, lease_seconds),
        )
        return bool(acquired)
    except RedisError:
        return None


def release_slot(key: str, token: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.zrem(key, token)
        return True
    except RedisError:
        return False


def ensure_stream_group(key: str, group: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.xgroup_create(name=key, groupname=group, id="0-0", mkstream=True)
        return True
    except ResponseError as error:
        return "BUSYGROUP" in str(error).upper()
    except RedisError:
        return False


def stream_add(key: str, payload: Any, max_length: int = 10000) -> str | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return str(client.xadd(key, {"payload": raw}, maxlen=max(1000, max_length), approximate=True))
    except (RedisError, TypeError, ValueError):
        return None


def _decode_stream_message(message: Any) -> tuple[str, Any] | None:
    if not isinstance(message, (list, tuple)) or len(message) != 2:
        return None
    message_id, fields = message
    if not isinstance(fields, dict):
        return str(message_id), None
    raw = fields.get("payload")
    if not isinstance(raw, str):
        return str(message_id), None
    try:
        return str(message_id), json.loads(raw)
    except json.JSONDecodeError:
        return str(message_id), None


def stream_read_group(
    key: str,
    group: str,
    consumer: str,
    block_milliseconds: int = 5000,
) -> tuple[str, Any] | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        response = client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={key: ">"},
            count=1,
            block=max(1000, block_milliseconds),
        )
    except RedisError:
        return None
    if not response or not response[0][1]:
        return None
    return _decode_stream_message(response[0][1][0])


def stream_claim_stale(
    key: str,
    group: str,
    consumer: str,
    min_idle_milliseconds: int,
) -> tuple[str, Any] | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        response = client.xautoclaim(
            name=key,
            groupname=group,
            consumername=consumer,
            min_idle_time=max(1000, min_idle_milliseconds),
            start_id="0-0",
            count=1,
        )
    except (RedisError, ResponseError):
        return None
    if not response or len(response) < 2 or not response[1]:
        return None
    return _decode_stream_message(response[1][0])


def stream_ack(key: str, group: str, message_id: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.xack(key, group, message_id))
    except RedisError:
        return False


def stream_touch(key: str, group: str, consumer: str, message_id: str) -> bool:
    """Reset a pending stream message idle clock while its worker is still alive."""
    client = get_redis_client()
    if client is None:
        return False
    try:
        claimed = client.xclaim(
            name=key,
            groupname=group,
            consumername=consumer,
            min_idle_time=0,
            message_ids=[message_id],
            justid=True,
        )
        return bool(claimed)
    except RedisError:
        return False


def stream_delete_consumer_if_idle(key: str, group: str, consumer: str) -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        consumers = client.xinfo_consumers(key, group)
        current = next((item for item in consumers if str(item.get("name")) == consumer), None)
        if current is None:
            return True
        if int(current.get("pending") or 0) > 0:
            return False
        client.xgroup_delconsumer(key, group, consumer)
        return True
    except (RedisError, ResponseError):
        return False


def stream_cleanup_idle_consumers(key: str, group: str, idle_milliseconds: int) -> int:
    client = get_redis_client()
    if client is None:
        return 0
    deleted = 0
    try:
        for item in client.xinfo_consumers(key, group):
            if int(item.get("pending") or 0) > 0:
                continue
            if int(item.get("idle") or 0) < max(1000, idle_milliseconds):
                continue
            client.xgroup_delconsumer(key, group, str(item.get("name")))
            deleted += 1
    except (RedisError, ResponseError):
        return deleted
    return deleted
