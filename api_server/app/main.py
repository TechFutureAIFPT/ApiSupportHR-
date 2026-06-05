from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import account_router, ai_router, files_router, mobile_jd_router
from app.core.config import get_settings


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

api_app = FastAPI(title=settings.app_name)

api_app.include_router(ai_router)
api_app.include_router(files_router)
api_app.include_router(account_router)
api_app.include_router(mobile_jd_router)


@api_app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Wrap the whole ASGI app so CORS headers are present even on unexpected 500s.
app = CORSMiddleware(
    api_app,
    allow_origins=_build_allowed_origins(),
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}):(8081|8090|19006)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
