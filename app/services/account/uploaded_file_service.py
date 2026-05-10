from __future__ import annotations

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs


MAX_FILES_PER_USER = 500
MAX_EXTRACTED_TEXT_LENGTH = 10000


def cleanup_uploaded_files(user: AuthenticatedUser, keep_count: int = MAX_FILES_PER_USER) -> None:
    docs = list(repo.uploaded_files().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "uploadedAt")
    for doc in ordered[keep_count:]:
        doc.reference.delete()


def save_uploaded_file(user: AuthenticatedUser, payload: dict[str, object]) -> str:
    file_name = str(payload.get("fileName") or "")
    extension = file_name.split(".")[-1].lower() if "." in file_name else ""
    extracted_text = str(payload.get("extractedText") or "")

    doc_ref = repo.create_document(repo.uploaded_files())
    doc_ref.set(
        {
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
    )
    cleanup_uploaded_files(user, MAX_FILES_PER_USER)
    return doc_ref.id


def save_uploaded_files(user: AuthenticatedUser, files: list[dict[str, object]]) -> list[str]:
    return [save_uploaded_file(user, file_payload) for file_payload in files]


def list_uploaded_files(user: AuthenticatedUser) -> list[dict[str, object]]:
    docs = list(repo.uploaded_files().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "uploadedAt")
    return [{"id": doc.id, **serialize(doc.to_dict())} for doc in ordered]


def get_user_files(user: AuthenticatedUser, limit_count: int = 50) -> list[dict[str, object]]:
    return list_uploaded_files(user)[:limit_count]


def get_user_files_by_type(user: AuthenticatedUser, file_type: str, limit_count: int = 50) -> list[dict[str, object]]:
    return [item for item in list_uploaded_files(user) if item.get("fileType") == file_type][:limit_count]


def get_files_by_session(user: AuthenticatedUser, session_id: str) -> list[dict[str, object]]:
    return [item for item in list_uploaded_files(user) if item.get("analysisSessionId") == session_id]


def delete_file(user: AuthenticatedUser, file_id: str) -> bool:
    snapshot = repo.uploaded_files().document(file_id).get()
    if not snapshot.exists:
        return False
    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return False
    snapshot.reference.delete()
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
    files = list_uploaded_files(user)
    total_cvs = sum(1 for item in files if item.get("fileType") == "cv")
    total_jds = sum(1 for item in files if item.get("fileType") == "jd")
    total_size = sum(int(item.get("fileSize") or 0) for item in files)
    return {
        "totalFiles": len(files),
        "totalCVs": total_cvs,
        "totalJDs": total_jds,
        "totalSizeBytes": total_size,
        "recentFiles": files[:5],
    }
