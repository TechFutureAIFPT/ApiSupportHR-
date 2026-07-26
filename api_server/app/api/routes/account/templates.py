from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api.pagination import CursorPageResponse, decode_cursor, parse_field_selection
from app.api.response_utils import cached_json_response
from app.api.deps import get_current_user
from app.repositories.firestore.page_repository import paginate_owner_records
from app.schemas.account import AuthenticatedUser, UserJDTemplateCreateRequest, UserJDTemplateUpdateRequest
from app.services.account import response_cache_service, template_service
from app.core.config import get_settings


router = APIRouter()
settings = get_settings()

TEMPLATE_PAGE_FIELDS = {
    "id", "name", "category", "jobPosition", "jdText", "hardFilters",
    "createdAt", "updatedAt",
}
TEMPLATE_PAGE_DEFAULT_FIELDS = (
    "id", "name", "category", "jobPosition", "jdText", "hardFilters",
    "createdAt", "updatedAt",
)


@router.get("/jd-templates")
def get_jd_templates(
    request: Request,
    limit_count: int = Query(default=100, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    cache_key = response_cache_service.account_cache_key("templates", current_user.uid, str(limit_count))
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key,
        "templates",
        lambda: template_service.get_user_templates(current_user, limit_count=limit_count),
    )
    return cached_json_response(request, cached)


@router.get("/jd-templates/page", response_model=CursorPageResponse, response_model_by_alias=True)
def get_jd_templates_page(
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(default=None),
    fields: str | None = Query(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    selected_fields = parse_field_selection(
        fields,
        allowed_fields=TEMPLATE_PAGE_FIELDS,
        default_fields=TEMPLATE_PAGE_DEFAULT_FIELDS,
    )
    return paginate_owner_records(
        table_sources=(("jd_templates", "template"),),
        owner_id=current_user.uid,
        page_size=page_size,
        fields=selected_fields,
        cursor=decode_cursor(cursor),
    )


@router.post("/jd-templates")
def create_jd_template(payload: UserJDTemplateCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return template_service.create_template(current_user, payload.model_dump())


@router.patch("/jd-templates/{template_id}")
def update_jd_template(
    template_id: str,
    payload: UserJDTemplateUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return {"ok": template_service.update_template(current_user, template_id, payload.model_dump(exclude_unset=True))}


@router.delete("/jd-templates/{template_id}")
def delete_jd_template(template_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": template_service.delete_template(current_user, template_id)}


@router.post("/jd-templates/seed-defaults")
def seed_jd_templates(current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"created": template_service.seed_default_templates_if_empty(current_user)}
