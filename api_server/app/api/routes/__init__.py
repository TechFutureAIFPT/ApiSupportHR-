from app.api.routes.account import router as account_router
from app.api.routes.ai import router as ai_router
from app.api.routes.files import router as files_router
from app.api.routes.mobile_jd import router as mobile_jd_router

__all__ = ["account_router", "ai_router", "files_router", "mobile_jd_router"]
