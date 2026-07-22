from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.api.pagination import CursorPageResponse, CursorToken, encode_cursor
from app.integrations.postgres import get_postgres_pool


PAGE_TABLES = {
    "cv_history",
    "synced_analysis_history",
    "uploaded_files",
    "jd_templates",
    "analysis_feedback",
    "chatbot_sessions",
    "manual_history",
}


def _projection(fields: list[str]) -> tuple[str, list[str]]:
    payload_fields = [field for field in fields if field not in {"id", "source"}]
    if not payload_fields:
        return "'{}'::jsonb", []
    placeholders = ", ".join("%s, payload -> %s" for _ in payload_fields)
    parameters = [value for field in payload_fields for value in (field, field)]
    return f"jsonb_strip_nulls(jsonb_build_object({placeholders}))", parameters


def _sort_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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
    if not sources or any(table not in PAGE_TABLES for table, _ in sources):
        raise ValueError("Unsupported pagination table.")

    projection_sql, projection_parameters = _projection(fields)
    union_parts: list[str] = []
    parameters: list[Any] = []
    filters = filters or {}
    filter_columns = {"fileType": "file_type", "action": "action", "status": "status"}

    for table, source in sources:
        where_parts = ["owner_id = %s::uuid"]
        part_parameters: list[Any] = [*projection_parameters, owner_id]
        for field, value in filters.items():
            if field in filter_columns:
                where_parts.append(f"{filter_columns[field]} = %s")
                part_parameters.append(value)
            else:
                where_parts.append("payload ->> %s = %s")
                part_parameters.extend([field, value])
        union_parts.append(
            f"select id, {projection_sql} as selected_payload, %s::text as source, "
            f"coalesce(source_updated_at, updated_at) as sort_at "
            f"from public.{table} where {' and '.join(where_parts)}"
        )
        # source placeholder is in SELECT after projection and before WHERE.
        parameters.extend([*projection_parameters, source, *part_parameters[len(projection_parameters):]])

    cursor_sql = ""
    if cursor is not None:
        cursor_sql = "where (sort_at, id) < (%s::timestamptz, %s)"
        parameters.extend([cursor.sort_at, cursor.document_id])
    parameters.append(page_size + 1)
    query = f"""
        select id, selected_payload, source, sort_at
        from ({' union all '.join(union_parts)}) as records
        {cursor_sql}
        order by sort_at desc, id desc
        limit %s
    """

    with get_postgres_pool().connection() as connection:
        with connection.cursor() as db_cursor:
            db_cursor.execute(query, parameters)
            rows = list(db_cursor.fetchall())

    has_more = len(rows) > page_size
    visible_rows = rows[:page_size]
    items: list[dict[str, Any]] = []
    include_source = "source" in fields or len(sources) > 1
    for document_id, payload, source, _sort_at in visible_rows:
        item = {"id": str(document_id), **dict(payload or {})}
        if include_source:
            item["source"] = source
        items.append(item)

    next_cursor = None
    if has_more and visible_rows:
        last_id, _payload, _source, last_sort_at = visible_rows[-1]
        next_cursor = encode_cursor(_sort_iso(last_sort_at), str(last_id))
    return CursorPageResponse(
        items=items,
        nextCursor=next_cursor,
        hasMore=has_more,
        pageSize=page_size,
    )
