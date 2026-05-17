from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.account import AuthenticatedUser, UploadedFileCreateRequest, UploadedFilesBatchRequest
from app.services.account import uploaded_file_service
from app.services import vector_index_service


router = APIRouter()


@router.post("/uploaded-files")
def save_uploaded_file(payload: UploadedFileCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": uploaded_file_service.save_uploaded_file(current_user, payload.model_dump())}


@router.post("/uploaded-files/batch")
def save_uploaded_files(payload: UploadedFilesBatchRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ids": uploaded_file_service.save_uploaded_files(current_user, [item.model_dump() for item in payload.files])}


@router.post("/uploaded-files/vector-index/rebuild")
def rebuild_uploaded_files_vector_index(
    limit_count: int = Query(default=500, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return vector_index_service.rebuild_uploaded_file_vector_index(current_user, limit_count=limit_count)


@router.get("/uploaded-files")
def list_uploaded_files(
    limit_count: int = Query(default=50, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return uploaded_file_service.get_user_files(current_user, limit_count=limit_count)


@router.get("/uploaded-files/by-type/{file_type}")
def list_uploaded_files_by_type(
    file_type: str,
    limit_count: int = Query(default=50, ge=1, le=500),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return uploaded_file_service.get_user_files_by_type(current_user, file_type=file_type, limit_count=limit_count)


@router.get("/uploaded-files/by-session/{session_id}")
def list_uploaded_files_by_session(session_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return uploaded_file_service.get_files_by_session(current_user, session_id=session_id)


@router.delete("/uploaded-files/{file_id}")
def delete_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": uploaded_file_service.delete_file(current_user, file_id)}


@router.post("/uploaded-files/{file_id}/touch")
def touch_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"ok": uploaded_file_service.touch_file(current_user, file_id)}


@router.post("/uploaded-files/{file_id}/vectorize")
def vectorize_uploaded_file(file_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return vector_index_service.reindex_uploaded_file(current_user, file_id)


@router.get("/uploaded-files/stats")
def get_uploaded_file_stats(current_user: AuthenticatedUser = Depends(get_current_user)):
    return uploaded_file_service.get_file_stats(current_user)
