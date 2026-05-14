from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.repositories.firestore import account_repository as account_repo
from app.repositories.firestore import vector_repository as vector_repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs
from app.services.gemini_service import embed_text


MIN_VECTOR_TEXT_LENGTH = 120
MAX_VECTOR_TEXT_LENGTH = 8000
MAX_VECTOR_SNIPPET_LENGTH = 400

INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "it": [
        "it",
        "software",
        "developer",
        "engineer",
        "backend",
        "frontend",
        "fullstack",
        "full-stack",
        "devops",
        "data engineer",
        "data scientist",
        "qa",
        "tester",
        "react",
        "vue",
        "angular",
        "node",
        "python",
        "java",
        "sql",
        "docker",
        "kubernetes",
        "fastapi",
    ],
    "sales": [
        "sales",
        "kinh doanh",
        "ban hang",
        "business development",
        "account executive",
        "account manager",
        "sale admin",
        "inside sales",
        "bd",
    ],
    "marketing": [
        "marketing",
        "content",
        "seo",
        "social media",
        "performance",
        "brand",
        "digital",
        "ads",
        "quang cao",
        "truyen thong",
    ],
    "design": [
        "design",
        "designer",
        "product designer",
        "ui/ux",
        "ux/ui",
        "figma",
        "photoshop",
        "illustrator",
        "creative",
        "thiet ke",
    ],
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_file_name(file_name: str) -> str:
    safe = re.sub(r"[^\w.-]+", "-", (file_name or "").strip().lower())
    return safe.strip("-") or "document"


def _display_name(file_name: str, candidate_name: str | None) -> str:
    if candidate_name and candidate_name.strip():
        return candidate_name.strip()
    return re.sub(r"\.[^.]+$", "", (file_name or "").strip()) or "Unknown Candidate"


def _detect_collection_key(payload: dict[str, Any]) -> str | None:
    values = [
        str(payload.get("jobPosition") or ""),
        str(payload.get("candidateName") or ""),
        str(payload.get("fileName") or ""),
        str(payload.get("extractedText") or "")[:2000],
    ]
    haystack = " ".join(values).lower()
    for collection_key, keywords in INDUSTRY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return collection_key
    return None


def vector_record_id_for_uploaded_file(file_id: str) -> str:
    return f"uploaded-file-{file_id}"


def _build_embedding_text(payload: dict[str, Any]) -> str:
    sections = [
        f"Document type: {str(payload.get('fileType') or 'cv').strip().lower()}",
        f"Candidate: {str(payload.get('candidateName') or '').strip()}",
        f"Job position: {str(payload.get('jobPosition') or '').strip()}",
        f"File name: {str(payload.get('fileName') or '').strip()}",
        "Content:",
        _normalize_text(str(payload.get("extractedText") or "")),
    ]
    return "\n".join(section for section in sections if section.strip())[:MAX_VECTOR_TEXT_LENGTH]


def _vector_status_payload(
    *,
    status: str,
    error: str | None = None,
    record_id: str | None = None,
    collection_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "vectorStatus": status,
        "vectorIndexedAt": account_repo.server_timestamp(),
    }
    if error:
        payload["vectorError"] = error[:500]
    else:
        payload["vectorError"] = None
    if record_id:
        payload["vectorRecordId"] = record_id
    if collection_key:
        payload["vectorCollectionKey"] = collection_key
    return payload


def _set_uploaded_file_vector_status(file_id: str, payload: dict[str, Any]) -> None:
    account_repo.set_document(account_repo.uploaded_files(), file_id, payload, merge=True)


def _build_vector_record(
    user: AuthenticatedUser,
    source_id: str,
    payload: dict[str, Any],
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    file_type = str(payload.get("fileType") or "").strip().lower()
    if file_type != "cv":
        return None, "unsupported_file_type", None

    extracted_text = _normalize_text(str(payload.get("extractedText") or ""))
    if len(extracted_text) < MIN_VECTOR_TEXT_LENGTH:
        return None, "insufficient_text", None

    collection_key = _detect_collection_key(payload)
    if not collection_key:
        return None, "unknown_industry", None

    settings = get_settings()
    vector = embed_text(_build_embedding_text(payload), settings.gemini_embedding_model)
    record_id = vector_record_id_for_uploaded_file(source_id)
    file_name = str(payload.get("fileName") or "")
    candidate_name = str(payload.get("candidateName") or "")
    job_position = str(payload.get("jobPosition") or "")
    uploaded_at = payload.get("uploadedAt") or account_repo.server_timestamp()

    record = {
        "id": record_id,
        "collectionKey": collection_key,
        "name": _display_name(file_name, candidate_name),
        "role": job_position,
        "relativePath": f"uploaded-files/{source_id}/{_normalize_file_name(file_name)}",
        "textSnippet": extracted_text[:MAX_VECTOR_SNIPPET_LENGTH],
        "vector": vector,
        "vectorModel": settings.gemini_embedding_model,
        "sourceCollection": account_repo.UPLOADED_FILES_COLLECTION,
        "sourceId": source_id,
        "uploadedAt": uploaded_at,
        "updatedAt": account_repo.server_timestamp(),
        "metadata": {
            "ownerUid": user.uid,
            "ownerEmail": user.email,
            "fileType": file_type,
            "fileName": file_name,
            "mimeType": str(payload.get("mimeType") or ""),
            "analysisSessionId": payload.get("analysisSessionId"),
            "candidateName": candidate_name or None,
            "jobPosition": job_position or None,
        },
    }
    return collection_key, None, record


def sync_uploaded_file_to_vector_store(
    user: AuthenticatedUser,
    source_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    collection_key, skip_reason, record = _build_vector_record(user, source_id, payload)
    if not record or not collection_key:
        delete_uploaded_file_vector_record(source_id)
        _set_uploaded_file_vector_status(
            source_id,
            _vector_status_payload(status="skipped", error=skip_reason),
        )
        return {
            "indexed": False,
            "recordId": None,
            "collectionKey": None,
            "reason": skip_reason,
        }

    collection_name = get_settings().vector_store_firestore_collection
    doc_ref = vector_repo.vector_library(collection_name).document(record["id"])
    snapshot = doc_ref.get()
    current = snapshot.to_dict() or {}
    if snapshot.exists and current.get("createdAt") is not None:
        record["createdAt"] = current["createdAt"]
    else:
        record["createdAt"] = account_repo.server_timestamp()
    doc_ref.set(record, merge=False)

    _set_uploaded_file_vector_status(
        source_id,
        _vector_status_payload(
            status="ready",
            record_id=record["id"],
            collection_key=collection_key,
        ),
    )
    return {
        "indexed": True,
        "recordId": record["id"],
        "collectionKey": collection_key,
        "reason": None,
    }


def try_sync_uploaded_file_to_vector_store(
    user: AuthenticatedUser,
    source_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        return sync_uploaded_file_to_vector_store(user, source_id, payload)
    except Exception as error:
        delete_uploaded_file_vector_record(source_id)
        _set_uploaded_file_vector_status(
            source_id,
            _vector_status_payload(status="error", error=str(error)),
        )
        return {
            "indexed": False,
            "recordId": None,
            "collectionKey": None,
            "reason": "error",
            "error": str(error),
        }


def delete_uploaded_file_vector_record(source_id: str) -> None:
    try:
        collection_name = get_settings().vector_store_firestore_collection
        vector_repo.vector_library(collection_name).document(vector_record_id_for_uploaded_file(source_id)).delete()
    except Exception:
        return


def reindex_uploaded_file(user: AuthenticatedUser, file_id: str) -> dict[str, Any]:
    snapshot = account_repo.uploaded_files().document(file_id).get()
    if not snapshot.exists:
        return {"ok": False, "reason": "not_found", "indexed": False}
    data = snapshot.to_dict() or {}
    if data.get("uid") != user.uid:
        return {"ok": False, "reason": "forbidden", "indexed": False}
    result = try_sync_uploaded_file_to_vector_store(user, file_id, serialize(data))
    return {"ok": True, **result}


def rebuild_uploaded_file_vector_index(user: AuthenticatedUser, limit_count: int = 500) -> dict[str, Any]:
    docs = list(account_repo.uploaded_files().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "uploadedAt")[:limit_count]

    indexed = 0
    skipped = 0
    failed = 0
    entries: list[dict[str, Any]] = []

    for doc in ordered:
        data = serialize(doc.to_dict())
        result = try_sync_uploaded_file_to_vector_store(user, doc.id, data)
        if result.get("indexed"):
            indexed += 1
        elif result.get("reason") == "error":
            failed += 1
        else:
            skipped += 1
        entries.append(
            {
                "fileId": doc.id,
                "fileName": data.get("fileName"),
                "indexed": result.get("indexed", False),
                "collectionKey": result.get("collectionKey"),
                "recordId": result.get("recordId"),
                "reason": result.get("reason"),
            }
        )

    return {
        "processed": len(ordered),
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "entries": entries,
    }
