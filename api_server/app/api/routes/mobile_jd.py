from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.api.deps import get_optional_current_user
from app.core.config import get_settings
from app.schemas.account import AuthenticatedUser
from app.schemas.mobile_jd import JDSupplementalFields, JDStandardizeRequest, JDStandardizeResponse, TargetPlatform
from app.services.account.persistence_service import save_mobile_jd_standardization
from app.services.file_extraction_service import extract_text_from_upload
from app.services.mobile_jd import standardize_jd_text


router = APIRouter(prefix="/api/mobile/jd", tags=["mobile-jd"])


def _append_supplemental_fields(jd_text: str, supplemental_fields: JDSupplementalFields | None) -> str:
    if not supplemental_fields:
        return jd_text

    values = supplemental_fields.model_dump(by_alias=True)
    labels = {
        "companyName": "Tên công ty",
        "salary": "Mức lương",
        "location": "Địa điểm",
        "workingTime": "Thời gian làm việc",
        "benefits": "Quyền lợi",
        "applicationInfo": "Cách ứng tuyển",
        "notes": "Ghi chú bổ sung",
    }
    lines = [
        f"- {labels[key]}: {str(value).strip()}"
        for key, value in values.items()
        if str(value or "").strip()
    ]
    if not lines:
        return jd_text
    return f"{jd_text.strip()}\n\nTHÔNG TIN HR BỔ SUNG:\n" + "\n".join(lines)


def _parse_supplemental_fields(raw_value: str | None) -> JDSupplementalFields | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
        return JDSupplementalFields.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(status_code=400, detail="supplemental_fields_json không hợp lệ.") from error


@router.post("/standardize", response_model=JDStandardizeResponse)
def standardize_jd(
    payload: JDStandardizeRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> JDStandardizeResponse:
    try:
        jd_text = _append_supplemental_fields(payload.jd_text, payload.supplemental_fields)
        result = standardize_jd_text(jd_text, payload.target_platform)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response = JDStandardizeResponse.model_validate(result)
    response.saved_record_id = save_mobile_jd_standardization(
        current_user,
        jd_text=jd_text,
        target_platform=payload.target_platform,
        supplemental_fields=(
            payload.supplemental_fields.model_dump(by_alias=True) if payload.supplemental_fields else None
        ),
        response_payload=response.model_dump(by_alias=True),
    )
    return response


@router.post("/standardize-file", response_model=JDStandardizeResponse)
async def standardize_jd_file(
    file: UploadFile = File(...),
    target_platform: TargetPlatform = Form(default="generic"),
    supplemental_fields_json: str | None = Form(default=None),
    force_ocr: bool = Form(default=False),
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> JDStandardizeResponse:
    try:
        file_bytes = await file.read()
        settings = get_settings()
        supplemental_fields = _parse_supplemental_fields(supplemental_fields_json)
        jd_text = await asyncio.to_thread(
            extract_text_from_upload,
            file_bytes=file_bytes,
            filename=file.filename or "uploaded-jd",
            content_type=file.content_type or "",
            force_ocr=force_ocr,
            document_type="jd",
            api_keys=settings.quick_cv_gemini_api_keys,
        )
        jd_text = _append_supplemental_fields(jd_text, supplemental_fields)
        result = standardize_jd_text(jd_text, target_platform)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response = JDStandardizeResponse.model_validate(result)
    response.saved_record_id = await asyncio.to_thread(
        save_mobile_jd_standardization,
        current_user,
        jd_text=jd_text,
        target_platform=target_platform,
        supplemental_fields=supplemental_fields.model_dump(by_alias=True) if supplemental_fields else None,
        response_payload=response.model_dump(by_alias=True),
        source_file={
            "fileName": file.filename or "uploaded-jd",
            "mimeType": file.content_type or "",
            "fileSize": len(file_bytes),
            "forceOcr": force_ocr,
        },
    )
    return response
