from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.integrations.supabase_access import verify_access_token
from app.integrations import redis_cache


logger = logging.getLogger("supporthr.audit")


@dataclass(frozen=True)
class ResolvedActor:
    uid: str | None
    email: str | None


_fallback_windows: dict[str, deque[float]] = {}
_fallback_lock = threading.Lock()
_job_concurrency: dict[str, int] = {}
_job_concurrency_lock = threading.Lock()


def resolve_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def resolve_actor(request: Request) -> ResolvedActor:
    cached_uid = getattr(request.state, "auth_uid", None)
    cached_email = getattr(request.state, "auth_email", None)
    if cached_uid or cached_email:
        return ResolvedActor(uid=cached_uid, email=cached_email)

    token = _extract_bearer_token(request)
    if not token:
        return ResolvedActor(uid=None, email=None)
    try:
        decoded = verify_access_token(token)
    except Exception:
        return ResolvedActor(uid=None, email=None)

    uid = str(decoded.get("uid") or decoded.get("user_id") or "") or None
    email = str(decoded.get("email") or "") or None
    request.state.auth_uid = uid
    request.state.auth_email = email
    return ResolvedActor(uid=uid, email=email)


def _fallback_check_limit(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    with _fallback_lock:
        bucket = _fallback_windows.setdefault(key, deque())
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
    return True


def enforce_window_limit(key: str, limit: int, window_seconds: int) -> None:
    redis_key = f"rate_limit:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
    count = redis_cache.increment(redis_key, window_seconds)
    if count is None:
        allowed = _fallback_check_limit(redis_key, limit, window_seconds)
        if not allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="QuÃ¡ nhiá»u yÃªu cáº§u. HÃ£y thá»­ láº¡i sau.")
        return

    if count > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="QuÃ¡ nhiá»u yÃªu cáº§u. HÃ£y thá»­ láº¡i sau.")


def apply_request_rate_limits(request: Request) -> None:
    path = request.url.path
    method = request.method.upper()
    ip = resolve_client_ip(request)
    actor = resolve_actor(request)

    if path.startswith("/health"):
        enforce_window_limit(f"health:{ip}", 30, 60)
        return

    if path.startswith("/api/account") and method == "GET":
        enforce_window_limit(f"account_read:ip:{ip}", 60, 60)
        if actor.uid:
            enforce_window_limit(f"account_read:user:{actor.uid}", 120, 60)
        return

    heavy_upload_paths = {
        "/api/mobile/jd/standardize",
        "/api/mobile/jd/standardize-file",
        "/api/cv/quick-score",
        "/api/cv/quick-score-text",
        "/api/files/extract-text",
    }
    if path in heavy_upload_paths:
        enforce_window_limit(f"upload:ip:{ip}", 20, 60)
        if actor.uid:
            enforce_window_limit(f"upload:user:{actor.uid}", 10, 60)
        return

    async_job_paths = {"/api/cv/analyze-core-async", "/api/analysis/jobs"}
    if path in async_job_paths and actor.uid:
        enforce_window_limit(f"analysis_jobs:user:{actor.uid}", 10, 15 * 60)


def enter_analysis_job(uid: str) -> None:
    with _job_concurrency_lock:
        current = _job_concurrency.get(uid, 0)
        if current >= 3:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Mỗi tài khoản chỉ được chạy tối đa 3 phiên phân tích song song.",
            )
        _job_concurrency[uid] = current + 1


def leave_analysis_job(uid: str | None) -> None:
    if not uid:
        return
    with _job_concurrency_lock:
        current = _job_concurrency.get(uid, 0)
        if current <= 1:
            _job_concurrency.pop(uid, None)
            return
        _job_concurrency[uid] = current - 1


def log_audit_event(record: dict[str, Any]) -> None:
    logger.info(record)
