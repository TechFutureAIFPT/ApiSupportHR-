from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.response_utils import cached_json_response
from app.api.deps import get_current_user
from app.schemas.account import AuthenticatedUser, UserJDTemplateCreateRequest, UserJDTemplateUpdateRequest
from app.services.account import response_cache_service, template_service


router = APIRouter()


@router.get("/jd-templates")
def get_jd_templates(request: Request, current_user: AuthenticatedUser = Depends(get_current_user)):
    cache_key = response_cache_service.account_cache_key("templates", current_user.uid)
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key,
        "templates",
        lambda: template_service.get_user_templates(current_user),
    )
    return cached_json_response(request, cached)


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
