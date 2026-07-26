from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.api.pagination import CursorPageResponse, CursorToken, encode_cursor
from app.repositories.firestore import account_repository as repo


COLLECTIONS = {
    "cv_history": (repo.cv_history, ("timestamp", "updatedAt", "createdAt")),
    "synced_analysis_history": (repo.synced_history, ("timestamp", "updatedAt", "createdAt")),
    "uploaded_files": (repo.uploaded_files, ("lastAccessedAt", "uploadedAt", "updatedAt")),
    "jd_templates": (repo.jd_templates, ("updatedAt", "createdAt")),
    "analysis_feedback": (repo.analysis_feedback, ("updatedAt", "createdAt")),
    "chatbot_sessions": (repo.chatbot_sessions, ("updatedAt", "createdAt")),
    "manual_history": (repo.manual_history, ("updatedAt", "createdAt", "timestamp")),
}


def _sort_millis(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except (ValueError, TypeError):
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return 0
    return 0


def _sort_value(payload: dict[str, Any], candidates: tuple[str, ...]) -> int:
    for field in candidates:
        value = _sort_millis(payload.get(field))
        if value:
            return value
    return 0


def paginate_owner_records(
    *,
    table_sources: Iterable[tuple[str, str]],
    owner_id: str,
    page_size: int,
    fields: list[str],
    cursor: CursorToken | None = None,
    filters: dict[str, str] | None = None,
) -> CursorPageResponse:
    sources = list(table_sources)
    rows: list[tuple[int, str, str, dict[str, Any]]] = []
    filters = filters or {}
    for table, source in sources:
        if table not in COLLECTIONS:
            raise ValueError("Unsupported pagination collection.")
        collection_factory, sort_fields = COLLECTIONS[table]
        query = collection_factory().where("uid", "==", owner_id)
        for field, value in filters.items():
            query = query.where(field, "==", value)
        for snapshot in query.stream():
            payload = snapshot.to_dict() or {}
            rows.append((_sort_value(payload, sort_fields), snapshot.id, source, payload))

    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if cursor is not None:
        cursor_ms = _sort_millis(cursor.sort_at)
        rows = [item for item in rows if (item[0], item[1]) < (cursor_ms, cursor.document_id)]

    visible = rows[: page_size + 1]
    has_more = len(visible) > page_size
    visible = visible[:page_size]
    include_source = "source" in fields or len(sources) > 1
    items: list[dict[str, Any]] = []
    for _, document_id, source, payload in visible:
        item = {"id": document_id}
        for field in fields:
            if field not in {"id", "source"} and field in payload:
                item[field] = payload[field]
        if include_source:
            item["source"] = source
        items.append(item)

    next_cursor = None
    if has_more and visible:
        sort_at, document_id, _, _ = visible[-1]
        next_cursor = encode_cursor(str(sort_at), document_id)
    return CursorPageResponse(
        items=items,
        nextCursor=next_cursor,
        hasMore=has_more,
        pageSize=page_size,
    )
