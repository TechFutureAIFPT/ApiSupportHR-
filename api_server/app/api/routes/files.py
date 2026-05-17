from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.files import ExtractedTextResponse
from app.services.file_extraction_service import extract_text_from_upload


router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/extract-text", response_model=ExtractedTextResponse)
async def extract_text(
    file: UploadFile = File(...),
    force_ocr: bool = Form(False),
    document_type: str | None = Form(None),
) -> ExtractedTextResponse:
    try:
        file_bytes = await file.read()
        text = extract_text_from_upload(
            file_bytes=file_bytes,
            filename=file.filename or "uploaded-file",
            content_type=file.content_type or "",
            force_ocr=force_ocr,
            document_type=document_type,
        )
        return ExtractedTextResponse(text=text)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
