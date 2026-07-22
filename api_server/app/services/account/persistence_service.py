from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from app.repositories.postgres import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import optimized_docs


MAX_ARTIFACTS_PER_USER = 200


def _now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _base_payload(user: AuthenticatedUser, artifact_type: str) -> dict[str, Any]:
    timestamp = _now_millis()
    return {
        "uid": user.uid,
        "email": user.email,
        "displayName": user.display_name or "",
        "photoURL": user.photo_url or "",
        "artifactType": artifact_type,
        "createdAt": repo.server_timestamp(),
        "updatedAt": repo.server_timestamp(),
        "timestamp": timestamp,
    }


def _cleanup(collection_ref: Any, user: AuthenticatedUser, keep_count: int = MAX_ARTIFACTS_PER_USER) -> None:
    try:
        docs = optimized_docs(collection_ref, user.uid, keep_count + 50)
        stale_ids = [doc.id for doc in docs[keep_count:]]
        delete_many = getattr(collection_ref, "delete_many", None)
        if callable(delete_many):
            delete_many(stale_ids)
        else:
            for document_id in stale_ids:
                collection_ref.document(document_id).delete()
    except Exception as error:  # pragma: no cover - Supabase availability depends on runtime config
        print(f"[Persistence] Cleanup skipped: {error}")


def _create(
    collection_factory: Callable[[], Any],
    user: AuthenticatedUser,
    artifact_type: str,
    payload: dict[str, Any],
) -> str | None:
    try:
        collection_ref = collection_factory()
        doc_ref = repo.create_document(collection_ref)
        doc_ref.set({**_base_payload(user, artifact_type), **payload})
        _cleanup(collection_ref, user)
        return doc_ref.id
    except Exception as error:  # pragma: no cover - Supabase availability depends on runtime config
        print(f"[Persistence] Save skipped for {artifact_type}: {error}")
        return None


def save_ai_request(
    user: AuthenticatedUser | None,
    *,
    operation: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str | None:
    if user is None:
        return None
    return _create(
        repo.ai_request_history,
        user,
        "ai_request",
        {
            "operation": operation,
            "request": request_payload,
            "response": response_payload,
            "metadata": metadata or {},
        },
    )


def save_quick_cv_score(
    user: AuthenticatedUser | None,
    *,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
) -> str | None:
    if user is None:
        return None
    items = response_payload.get("items") or []
    first_item = items[0] if items and isinstance(items[0], dict) else {}
    jd_text = str(request_payload.get("jd_text") or request_payload.get("jdText") or request_payload.get("jdText") or "")
    return _create(
        repo.quick_cv_scores,
        user,
        "quick_cv_score",
        {
            "feature": "mobileQuickCvAnalysis",
            "schemaVersion": 1,
            "source": "backend",
            "items": items,
            "jdText": jd_text,
            "jdTitle": str(request_payload.get("jd_title") or request_payload.get("jdTitle") or ""),
            "targetRole": str(first_item.get("target_role") or first_item.get("targetRole") or ""),
            "summary": str(first_item.get("summary") or ""),
            "usageNote": response_payload.get("usage_note")
            or response_payload.get("usageNote")
            or "AI output is a screening aid and should be reviewed by a recruiter.",
            "model": response_payload.get("model") or "",
            "request": request_payload,
            "response": response_payload,
            "itemCount": len(items),
        },
    )


def save_file_extraction(
    user: AuthenticatedUser | None,
    *,
    file_name: str,
    content_type: str,
    file_size: int,
    document_type: str | None,
    force_ocr: bool,
    extracted_text: str,
) -> str | None:
    if user is None:
        return None
    return _create(
        repo.file_extractions,
        user,
        "file_extraction",
        {
            "fileName": file_name,
            "mimeType": content_type,
            "fileSize": file_size,
            "documentType": document_type or "",
            "forceOcr": force_ocr,
            "extractedText": extracted_text,
            "extractedTextLength": len(extracted_text),
        },
    )


def save_mobile_jd_standardization(
    user: AuthenticatedUser | None,
    *,
    jd_text: str,
    target_platform: str,
    supplemental_fields: dict[str, Any] | None,
    response_payload: dict[str, Any],
    source_file: dict[str, Any] | None = None,
) -> str | None:
    if user is None:
        return None
    normalized_jd = response_payload.get("normalizedJD") or response_payload.get("normalized_jd") or {}
    return _create(
        repo.mobile_jd_history,
        user,
        "mobile_jd_standardization",
        {
            "feature": "mobileJDStandardization",
            "schemaVersion": 1,
            "input": {
                "jdText": jd_text,
                "targetPlatform": target_platform,
                "supplementalFields": supplemental_fields or {},
                "sourceFile": source_file or {},
            },
            "result": response_payload,
            "template": normalized_jd if isinstance(normalized_jd, dict) else {},
            "usageNote": "AI output is a drafting aid and should be reviewed by a recruiter.",
            "model": str(response_payload.get("model") or ""),
            "jdText": jd_text,
            "targetPlatform": target_platform,
            "supplementalFields": supplemental_fields or {},
            "response": response_payload,
            "sourceFile": source_file or {},
            "score": response_payload.get("score"),
            "title": normalized_jd.get("title") if isinstance(normalized_jd, dict) else "",
        },
    )
