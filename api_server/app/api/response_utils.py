from __future__ import annotations

from typing import Any

from fastapi import Request
from starlette.responses import JSONResponse, Response

from app.services.account.response_cache_service import CachedPayload, build_etag, normalize_if_none_match


def cached_json_response(request: Request, cached: CachedPayload | dict[str, Any]) -> Response:
    if isinstance(cached, dict):
        revision = str(cached.get("revision") or "").strip()
        generated_at = int(cached.get("generatedAt") or 0)
        payload = cached
        cache_hit = False
    else:
        revision = cached.revision
        generated_at = cached.generated_at
        payload = cached.payload
        cache_hit = cached.cache_hit

    etag = build_etag(revision)
    request.state.cache_status = "hit" if cache_hit else "miss"
    headers = {
        "ETag": etag,
        "X-Data-Revision": revision,
    }
    if generated_at:
        headers["X-Generated-At"] = str(generated_at)

    if normalize_if_none_match(request.headers.get("if-none-match")) == revision:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
