from __future__ import annotations

import logging

from app.integrations import redis_cache
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.persistence_service import save_file_extraction
from app.services.account.shared import fast_cleanup, serialize, sorted_docs
from app.services import vector_index_service


logger = logging.getLogger("app.firestore.uploaded_files")

MAX_FILES_PER_USER = 500
MAX_EXTRACTED_TEXT_LENGTH = 10000


def _invalidate_uploaded_files_cache(uid: str) -> None:
    redis_cache.delete_prefix(f"uploaded_files:{uid}:")


def cleanup_uploaded_files(user: AuthenticatedUser, keep_count: int = MAX_FILES_PER_USER) -> None:
    fast_cleanup(repo.uploaded_files(), user.uid, keep_count, timestamp_field="uploadedAt")


def save_uploaded_file(user: AuthenticatedUser, payload: dict[str, object]) -> str:
    file_name = str(payload.get("fileName") or "")
    extension = file_name.split(".")[-1].lower() if "." in file_name else ""
    extracted_text = str(payload.get("extractedText") or "")

    doc_ref = repo.create_document(repo.uploaded_files())
    stored_payload = {
        "uid": user.uid,
        "email": user.email,
        "fileName": file_name,
        "fileType": str(payload.get("fileType") or "cv"),
        "fileSize": int(payload.get("fileSize") or 0),
        "mimeType": str(payload.get("mimeType") or ""),
        "fileExtension": extension,
        "ocrMethod": str(payload.get("ocrMethod") or ""),
        "extractedText": extracted_text[:MAX_EXTRACTED_TEXT_LENGTH],
        "extractedTextLength": len(extracted_text),
        "processingTimeMs": int(payload.get("processingTimeMs") or 0),
        "analysisSessionId": payload.get("analysisSessionId"),
        "candidateName": payload.get("candidateName"),
        "jobPosition": payload.get("jobPosition"),
        "uploadedAt": repo.server_timestamp(),
    }
    doc_ref.set(stored_payload)
    save_file_extraction(
        user,
        file_name=file_name,
        content_type=stored_payload["mimeType"],
        file_size=stored_payload["fileSize"],
        document_type=stored_payload["fileType"],
        force_ocr=str(stored_payload["ocrMethod"]).lower() not in {"", "browser-local", "text"},
        extracted_text=extracted_text,
    )
    vector_index_service.try_sync_uploaded_file_to_vector_store(user, doc_ref.id, stored_payload)
    cleanup_uploaded_files(user, MAX_FILES_PER_USER)
    _invalidate_uploaded_files_cache(user.uid)
    return doc_ref.id


def save_uploaded_files(user: AuthenticatedUser, files: list[dict[str, object]]) -> list[str]:
    return [save_uploaded_file(user, file_payload) for file_payload in files]


def _query_uploaded_files(
    user: AuthenticatedUser,
    *,
    file_type: str | None = None,
    session_id: str | None = None,
    limit_count: int | None = None,
) -> list[object]:
    """Đẩy filter (fileType/analysisSessionId) và order_by+limit xuống Firestore
    thay vì tải toàn bộ collection rồi lọc bằng Python."""
    base_query = repo.uploaded_files().where("uid", "==", user.uid)
    if file_type:
        base_query = base_query.where("fileType", "==", file_type)
    if session_id:
        base_query = base_query.where("analysisSessionId", "==", session_id)

    try:
        query = base_query.order_by("uploadedAt", direction="DESCENDING")
        if limit_count:
            query = query.limit(limit_count)
        return list(query.stream())
    except Exception as exc:
        logger.warning(
            "uploaded_files fallback to full-scan uid=%s file_type=%s session_id=%s error=%s",
            user.uid, file_type, session_id, exc,
        )
        ordered = sorted_docs(list(base_query.stream()), "uploadedAt")
        return ordered[:limit_count] if limit_count else ordered


def list_uploaded_files(user: AuthenticatedUser) -> list[dict[str, object]]:
    docs = _query_uploaded_files(user)
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in docs]


def get_user_files(user: AuthenticatedUser, limit_count: int = 50) -> list[dict[str, object]]:
    docs = _query_uploaded_files(user, limit_count=limit_count)
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in docs]


def get_user_files_by_type(user: AuthenticatedUser, file_type: str, limit_count: int = 50) -> list[dict[str, object]]:
    docs = _query_uploaded_files(user, file_type=file_type, limit_count=limit_count)
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in docs]


def get_files_by_session(user: AuthenticatedUser, session_id: str) -> list[dict[str, object]]:
    docs = _query_uploaded_files(user, session_id=session_id)
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in docs]


def delete_file(user: AuthenticatedUser, file_id: str) -> bool:
    snapshot = repo.uploaded_files().document(file_id).get()
    if not snapshot.exists:
        return False
    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return False
    snapshot.reference.delete()
    vector_index_service.delete_uploaded_file_vector_record(file_id)
    _invalidate_uploaded_files_cache(user.uid)
    return True


def touch_file(user: AuthenticatedUser, file_id: str) -> bool:
    snapshot = repo.uploaded_files().document(file_id).get()
    if not snapshot.exists:
        return False
    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return False
    snapshot.reference.set({"lastAccessedAt": repo.server_timestamp()}, merge=True)
    return True


def get_file_stats(user: AuthenticatedUser) -> dict[str, object]:
    base_query = repo.uploaded_files().where("uid", "==", user.uid)
    total_files = int(base_query.count().get()[0][0].value)
    total_cvs = int(base_query.where("fileType", "==", "cv").count().get()[0][0].value)
    total_jds = int(base_query.where("fileType", "==", "jd").count().get()[0][0].value)
    total_size = int(base_query.sum("fileSize").get()[0][0].value or 0)
    return {
        "totalFiles": total_files,
        "totalCVs": total_cvs,
        "totalJDs": total_jds,
        "totalSizeBytes": total_size,
        "recentFiles": get_user_files(user, limit_count=5),
    }
