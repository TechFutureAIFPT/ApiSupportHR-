from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import get_current_user
from app.api.pagination import CursorPageResponse, decode_cursor, parse_field_selection
from app.api.response_utils import cached_json_response
from app.repositories.firestore.page_repository import paginate_owner_records
from app.schemas.account import AuthenticatedUser, UploadedFileCreateRequest, UploadedFilesBatchRequest
from app.services.account import response_cache_service, uploaded_file_service
from app.services import vector_index_service
from app.core.config import get_settings
from app.schemas.analysis import AnalysisJobAcceptedResponse
from app.services.analysis_job_service import start_vector_rebuild_job


router = APIRouter()
settings = get_settings()

UPLOADED_FILE_PAGE_FIELDS = {
    "id", "fileName", "fileType", "fileSize", "mimeType", "fileExtension",
    "ocrMethod", "extractedText", "extractedTextLength", "processingTimeMs",
    "analysisSessionId", "candidateName", "jobPosition", "uploadedAt", "lastAccessedAt",
}
UPLOADED_FILE_PAGE_DEFAULT_FIELDS = (
    "id", "fileName", "fileType", "fileSize", "mimeType", "fileExtension",
    "ocrMethod", "extractedTextLength", "processingTimeMs", "analysisSessionId",
    "candidateName", "jobPosition", "uploadedAt", "lastAccessedAt",
)


@router.post("/uploaded-files")
def save_uploaded_file(payload: UploadedFileCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": uploaded_file_service.save_uploaded_file(current_user, payload.model_dump())}


@router.post("/uploaded-files/batch")
def save_uploaded_files(payload: UploadedFilesBatchRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ids": uploaded_file_service.save_uploaded_files(current_user, [item.model_dump() for item in payload.files])}


@router.post(
    "/uploaded-files/vector-index/rebuild",
    response_model=AnalysisJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rebuild_uploaded_files_vector_index(
    limit_count: int = Query(default=200, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    job = start_vector_rebuild_job(current_user, limit_count=limit_count)
    return AnalysisJobAcceptedResponse(
        job_id=str(job["job_id"]),
        status=str(job["status"]),
        status_url=f"/api/analysis/status/{job['job_id']}",
    )


@router.get("/uploaded-files")
def list_uploaded_files(
    request: Request,
    limit_count: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    cache_key_name = response_cache_service.account_cache_key("uploaded_files", current_user.uid, "all", str(limit_count))
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key_name,
        "uploaded_files",
        lambda: uploaded_file_service.get_user_files(current_user, limit_count=limit_count),
    )
    return cached_json_response(request, cached)


@router.get("/uploaded-files/page", response_model=CursorPageResponse, response_model_by_alias=True)
def list_uploaded_files_page(
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    cursor: str | None = Query(default=None),
    fields: str | None = Query(default=None),
    file_type: str | None = Query(default=None, alias="fileType"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    selected_fields = parse_field_selection(
        fields,
        allowed_fields=UPLOADED_FILE_PAGE_FIELDS,
        default_fields=UPLOADED_FILE_PAGE_DEFAULT_FIELDS,
    )
    return paginate_owner_records(
        table_sources=(("uploaded_files", "uploaded"),),
        owner_id=current_user.uid,
        page_size=page_size,
        fields=selected_fields,
        cursor=decode_cursor(cursor),
        filters={"fileType": file_type} if file_type else None,
    )


@router.get("/uploaded-files/by-type/{file_type}")
def list_uploaded_files_by_type(
    request: Request,
    file_type: str,
    limit_count: int = Query(default=50, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    cache_key_name = response_cache_service.account_cache_key("uploaded_files", current_user.uid, "type", file_type, str(limit_count))
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key_name,
        "uploaded_files",
        lambda: uploaded_file_service.get_user_files_by_type(current_user, file_type=file_type, limit_count=limit_count),
    )
    return cached_json_response(request, cached)


@router.get("/uploaded-files/by-session/{session_id}")
def list_uploaded_files_by_session(session_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return uploaded_file_service.get_files_by_session(current_user, session_id=session_id, limit_count=200)


@router.delete("/uploaded-files/{file_id}")
def delete_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": uploaded_file_service.delete_file(current_user, file_id)}


@router.post("/uploaded-files/{file_id}/touch")
@router.patch("/uploaded-files/{file_id}/touch")
def touch_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": uploaded_file_service.touch_file(current_user, file_id)}


@router.post("/uploaded-files/{file_id}/vectorize")
def vectorize_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return vector_index_service.reindex_uploaded_file(current_user, file_id)


@router.get("/uploaded-files/stats")
def get_uploaded_file_stats(request: Request, current_user: AuthenticatedUser = Depends(get_current_user)):
    cache_key_name = response_cache_service.account_cache_key("uploaded_files", current_user.uid, "stats")
    cached = response_cache_service.get_or_build_cached_payload(
        cache_key_name,
        "uploaded_files",
        lambda: uploaded_file_service.get_file_stats(current_user),
    )
    return cached_json_response(request, cached)
