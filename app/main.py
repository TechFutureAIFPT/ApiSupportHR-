from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_ai import router as ai_router
from app.api.routes_account import router as account_router
from app.api.routes_files import router as file_router
from app.core.config import get_settings


settings = get_settings()


def _build_allowed_origins() -> list[str]:
    origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    }
    if settings.frontend_origin:
        origins.add(settings.frontend_origin)
    origins.update(origin for origin in settings.google_drive_allowed_origins if origin)
    return sorted(origins)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)
app.include_router(file_router)
app.include_router(account_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
