from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.routes import account_router, ai_router, files_router, mobile_jd_router, salary_router
from app.core.config import get_settings
from app.integrations import redis_cache
from app.services.local_classifier_service import get_classifier_status, warm_classifier
from app.services.security_service import apply_request_rate_limits, log_audit_event, resolve_client_ip
from app.utils.text_normalization import normalize_payload_text


settings = get_settings()


def _build_allowed_origins() -> list[str]:
    origins = {
        "http://localhost:3000",
        "http://localhost:8081",
        "http://localhost:8090",
        "http://localhost:19006",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8081",
        "http://127.0.0.1:8090",
        "http://127.0.0.1:19006",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://www.supporthr-tf.com.vn",
        "https://supporthr-tf.com.vn",
    }
    if settings.frontend_origin:
        origins.add(settings.frontend_origin)
    origins.update(origin for origin in settings.google_drive_allowed_origins if origin)
    return sorted(origins)


def verify_runtime_artifacts() -> None:
    if settings.local_classifier_mode != "local":
        return
    status = warm_classifier()
    if settings.require_classifier_ready and not bool(status.get("ready")):
        raise RuntimeError(f"Local classifier failed readiness validation: {status.get('error')}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    verify_runtime_artifacts()
    try:
        yield
    finally:
        redis_cache.close_redis_client()


api_app = FastAPI(title=settings.app_name, lifespan=lifespan)


@api_app.middleware("http")
async def audit_and_guard_requests(request: Request, call_next):
    started_at = time.perf_counter()
    request.state.app_check_verified = getattr(request.state, "app_check_verified", False)
    request.state.cache_status = getattr(request.state, "cache_status", "bypass")

    try:
        if settings.maintenance_mode and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            raise HTTPException(status_code=503, detail="SupportHR is temporarily read-only for data migration.")
        # redis-py is synchronous; keep its network I/O off the event loop.
        await run_in_threadpool(apply_request_rate_limits, request)
        response = await call_next(request)
    except HTTPException as error:
        response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
    finally:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_audit_event(
            {
                "uid": getattr(request.state, "auth_uid", ""),
                "path": request.url.path,
                "method": request.method,
                "statusCode": getattr(locals().get("response"), "status_code", 500),
                "latencyMs": elapsed_ms,
                "clientIp": resolve_client_ip(request),
                "cache": getattr(request.state, "cache_status", "bypass"),
                "appCheck": bool(getattr(request.state, "app_check_verified", False)),
            }
        )
    response.headers["Server-Timing"] = f'app;dur={elapsed_ms:.2f}'
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
    response.headers["X-Cache-Status"] = str(getattr(request.state, "cache_status", "bypass"))
    return response


@api_app.middleware("http")
async def normalize_json_text_response(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    if not body:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=content_type,
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=content_type,
        )

    headers = dict(response.headers)
    headers.pop("content-length", None)
    normalized_body = json.dumps(
        normalize_payload_text(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return Response(
        content=normalized_body,
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
    )


# Added after response normalization so the final JSON bytes are compressed.
api_app.add_middleware(
    GZipMiddleware,
    minimum_size=settings.gzip_minimum_size,
    compresslevel=settings.gzip_compress_level,
)


api_app.include_router(ai_router)
api_app.include_router(files_router)
api_app.include_router(account_router)
api_app.include_router(mobile_jd_router)
api_app.include_router(salary_router)


def _readiness_payload() -> dict[str, object]:
    classifier = get_classifier_status()
    classifier_ready = bool(classifier.get("ready")) or settings.local_classifier_mode == "auto"
    if settings.require_classifier_ready and settings.local_classifier_mode == "local" and not classifier_ready:
        raise HTTPException(status_code=503, detail="Local classifier is not ready")
    redis_required = settings.analysis_job_mode == "redis"
    redis_ready = redis_cache.ping() if redis_required else None
    if redis_required and not redis_ready:
        raise HTTPException(status_code=503, detail="Redis analysis queue is not ready")
    from app.integrations.firebase_admin import firestore_ready

    firestore_is_ready = firestore_ready()
    if not firestore_is_ready:
        raise HTTPException(status_code=503, detail="Firebase Firestore is not ready")
    return {
        "status": "ok",
        "classifier": {
            "ready": bool(classifier.get("ready")),
            "modelVersion": classifier.get("model_version"),
            "labelCount": classifier.get("label_count"),
        },
        "queue": {
            "mode": settings.analysis_job_mode,
            "redisReady": redis_ready,
        },
        "data": {
            "provider": "firebase",
            "firestoreReady": firestore_is_ready,
        },
    }


@api_app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@api_app.get("/health/ready")
def health_ready() -> dict[str, object]:
    return _readiness_payload()


@api_app.get("/health")
def health() -> dict[str, object]:
    return _readiness_payload()


app = CORSMiddleware(
    api_app,
    allow_origins=_build_allowed_origins(),
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}):(8081|8090|19006)$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "If-None-Match", "If-Match",
        "X-Firebase-AppCheck",
    ],
    expose_headers=[
        "ETag", "X-Data-Revision", "X-Generated-At", "X-Cache-Status",
        "X-Process-Time-Ms", "Server-Timing",
    ],
)
