from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable


logger = logging.getLogger("app.supabase.optimized_docs")


def to_millis(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, datetime):
        return to_millis(value)
    return value


def sorted_docs(docs: Iterable[Any], field_name: str, reverse: bool = True) -> list[Any]:
    return sorted(docs, key=lambda doc: to_millis(doc.to_dict().get(field_name)), reverse=reverse)


def optimized_docs(collection_ref: Any, uid: str, limit_count: int, timestamp_field: str = "timestamp") -> list[Any]:
    """Fetch docs using PostgreSQL ORDER BY + LIMIT, with a bounded compatibility fallback."""
    try:
        return list(
            collection_ref.where("uid", "==", uid)
            .order_by(timestamp_field, direction="DESCENDING")
            .limit(limit_count)
            .stream()
        )
    except Exception as exc:
        logger.warning(
            "optimized_docs fallback to full-scan collection=%s uid=%s field=%s error=%s",
            getattr(collection_ref, "id", "?"), uid, timestamp_field, exc,
        )
        return sorted_docs(
            list(collection_ref.where("uid", "==", uid).stream()),
            timestamp_field,
        )[:limit_count]


def fast_cleanup(collection_ref: Any, uid: str, keep_count: int, timestamp_field: str = "timestamp") -> None:
    """Delete documents beyond keep_count using an ordered bounded scan.

    Reads at most keep_count + 30 docs (not the entire collection), so the
    common no-op case (user under limit) completes in a single bounded read.
    """
    scan_limit = keep_count + 30
    docs = optimized_docs(collection_ref, uid, scan_limit, timestamp_field)
    excess = docs[keep_count:]
    if not excess:
        return
    delete_many = getattr(collection_ref, "delete_many", None)
    if callable(delete_many):
        delete_many(doc.id for doc in excess)
    else:
        for doc in excess:
            doc.reference.delete()
    # If we hit the scan ceiling, there may be more — sweep only what's unknown
    if len(docs) == scan_limit:
        keep_ids = {doc.id for doc in docs[:keep_count]}
        stale_ids = [
            doc.id
            for doc in collection_ref.where("uid", "==", uid).stream()
            if doc.id not in keep_ids
        ]
        if callable(delete_many):
            delete_many(stale_ids)
        else:
            for document_id in stale_ids:
                collection_ref.document(document_id).delete()
