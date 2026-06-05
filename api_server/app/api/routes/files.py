from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_optional_current_user
from app.schemas.account import AuthenticatedUser
from app.schemas.files import ExtractedTextResponse
from app.services.account.persistence_service import save_file_extraction
from app.services.file_extraction_service import extract_text_from_upload


router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/extract-text", response_model=ExtractedTextResponse)
async def extract_text(
    file: UploadFile = File(...),
    force_ocr: bool = Form(False),
    document_type: str | None = Form(None),
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> ExtractedTextResponse:
    try:
        file_bytes = await file.read()
        text = await asyncio.to_thread(
            extract_text_from_upload,
            file_bytes=file_bytes,
            filename=file.filename or "uploaded-file",
            content_type=file.content_type or "",
            force_ocr=force_ocr,
            document_type=document_type,
        )
        saved_record_id = await asyncio.to_thread(
            save_file_extraction,
            current_user,
            file_name=file.filename or "uploaded-file",
            content_type=file.content_type or "",
            file_size=len(file_bytes),
            document_type=document_type,
            force_ocr=force_ocr,
            extracted_text=text,
        )
        return ExtractedTextResponse(text=text, saved_record_id=saved_record_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
