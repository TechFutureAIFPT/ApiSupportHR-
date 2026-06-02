from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import get_settings
from app.schemas.mobile_jd import JDStandardizeRequest, JDStandardizeResponse, TargetPlatform
from app.services.file_extraction_service import extract_text_from_upload
from app.services.mobile_jd import standardize_jd_text


router = APIRouter(prefix="/api/mobile/jd", tags=["mobile-jd"])


@router.post("/standardize", response_model=JDStandardizeResponse)
def standardize_jd(payload: JDStandardizeRequest) -> JDStandardizeResponse:
    try:
        result = standardize_jd_text(payload.jd_text, payload.target_platform)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return JDStandardizeResponse.model_validate(result)


@router.post("/standardize-file", response_model=JDStandardizeResponse)
async def standardize_jd_file(
    file: UploadFile = File(...),
    target_platform: TargetPlatform = Form(default="generic"),
    force_ocr: bool = Form(default=False),
) -> JDStandardizeResponse:
    try:
        file_bytes = await file.read()
        settings = get_settings()
        jd_text = await asyncio.to_thread(
            extract_text_from_upload,
            file_bytes=file_bytes,
            filename=file.filename or "uploaded-jd",
            content_type=file.content_type or "",
            force_ocr=force_ocr,
            document_type="jd",
            api_keys=settings.quick_cv_gemini_api_keys,
        )
        result = standardize_jd_text(jd_text, target_platform)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return JDStandardizeResponse.model_validate(result)
