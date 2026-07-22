from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Iterable

from app.integrations.data_crypto import decrypt_secret_payload, encrypt_secret_payload
from app.integrations.postgres import get_postgres_pool


COLLECTION_TABLES = {
    "users": "profiles",
    "userSettings": "user_settings",
    "googleDriveConnections": "google_drive_connections",
    "googleDriveOAuthStates": "google_drive_oauth_states",
    "userSyncState": "user_sync_state",
    "cvHistory": "cv_history",
    "syncedAnalysisHistory": "synced_analysis_history",
    "syncedAnalysisCache": "synced_analysis_cache",
    "uploadedFiles": "uploaded_files",
    "userJDTemplates": "jd_templates",
    "chatbotSessions": "chatbot_sessions",
    "CLdl7JGuaOGIuijiDZeG": "manual_history",
    "analysisFeedback": "analysis_feedback",
    "analysisFeedback.  Document ID": "analysis_feedback",
    "analysisJobs": "analysis_jobs",
    "aiRequestHistory": "ai_request_history",
    "fileExtractions": "file_extractions",
    "mobileJDStandardizations": "mobile_jd_standardizations",
    "mobileQuickCvAnalyses": "mobile_quick_cv_analyses",
    "mobileInboxViews": "mobile_inbox_views",
    "approvedExemplars": "approved_exemplars",
    "vectorLibraryRecords": "vector_library_records",
    "desktopSessions": "desktop_sessions",
    "sessionCommands": "session_commands",
    "candidateSchedules": "candidate_schedules",
}

SECRET_FIELDS = {"accessToken", "refreshToken"}


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        dt = value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if hasattr(value, "timestamp") and callable(value.timestamp):
        return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc).isoformat()
    return str(value)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _checksum(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _uuid_or_none(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _filter_parts(filter_value: Any) -> tuple[str, str, Any]:
    field = getattr(filter_value, "field_path", None)
    operator = getattr(filter_value, "op_string", None)
    value = getattr(filter_value, "value", None)
    if field is None:
        field = getattr(filter_value, "field", None)
    if operator is None:
        operator = getattr(filter_value, "op", None)
    return str(field), str(operator), value


@dataclass(frozen=True)
class _QueryState:
    filters: tuple[tuple[str, str, Any], ...] = ()
    order_field: str | None = None
    descending: bool = False
    limit_count: int | None = None


class PostgresDocumentSnapshot:
    def __init__(self, reference: "PostgresDocumentReference", data: dict[str, Any] | None) -> None:
        self.reference = reference
        self.id = reference.id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._data) if self._data is not None else None


class PostgresDocumentReference:
    def __init__(self, collection: "PostgresCollectionReference", document_id: str) -> None:
        self._collection = collection
        self.id = document_id

    def get(self) -> PostgresDocumentSnapshot:
        return PostgresDocumentSnapshot(self, self._collection._fetch_one(self.id))

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        clean = _json_safe(payload)
        if merge:
            current = self.get().to_dict() or {}
            current.update(clean)
            clean = current
        self._collection._upsert(self.id, clean)

    def update(self, payload: dict[str, Any]) -> None:
        if not self.get().exists:
            raise KeyError(f"Document {self.id} does not exist.")
        self.set(payload, merge=True)

    def delete(self) -> None:
        self._collection._delete(self.id)


class _CountValue:
    def __init__(self, value: int) -> None:
        self.value = value


class PostgresCountQuery:
    def __init__(self, query: "PostgresCollectionReference") -> None:
        self._query = query

    def get(self) -> list[list[_CountValue]]:
        return [[_CountValue(self._query._count())]]


class PostgresCollectionReference:
    def __init__(self, source_collection: str, state: _QueryState | None = None) -> None:
        try:
            self.table = COLLECTION_TABLES[source_collection]
        except KeyError as error:
            raise ValueError(f"No Supabase table mapping for collection {source_collection!r}.") from error
        self.source_collection = source_collection
        self._state = state or _QueryState()

    def document(self, document_id: str | None = None) -> PostgresDocumentReference:
        return PostgresDocumentReference(self, document_id or str(uuid.uuid4()))

    def add(self, payload: dict[str, Any]) -> tuple[Any, PostgresDocumentReference]:
        reference = self.document()
        reference.set(payload)
        return None, reference

    def where(self, field: str | None = None, operator: str | None = None, value: Any = None, *, filter: Any = None):
        clause = _filter_parts(filter) if filter is not None else (str(field), str(operator), value)
        if clause[1] != "==":
            raise ValueError(f"Unsupported PostgreSQL compatibility query operator: {clause[1]}")
        return PostgresCollectionReference(
            self.source_collection,
            replace(self._state, filters=(*self._state.filters, clause)),
        )

    def order_by(self, field: str, direction: Any = "ASCENDING"):
        direction_text = str(direction).upper()
        descending = direction_text.endswith("DESCENDING") or direction_text == "DESC"
        return PostgresCollectionReference(
            self.source_collection,
            replace(self._state, order_field=field, descending=descending),
        )

    def limit(self, count: int):
        return PostgresCollectionReference(
            self.source_collection,
            replace(self._state, limit_count=max(0, int(count))),
        )

    def count(self) -> PostgresCountQuery:
        return PostgresCountQuery(self)

    def stream(self) -> Iterable[PostgresDocumentSnapshot]:
        return [
            PostgresDocumentSnapshot(self.document(row[0]), self._row_payload(row))
            for row in self._select_rows()
        ]

    def _where_sql(self) -> tuple[str, list[Any]]:
        fragments: list[str] = []
        parameters: list[Any] = []
        for field, _operator, value in self._state.filters:
            if field == "uid" and _uuid_or_none(value):
                fragments.append("owner_id = %s::uuid")
                parameters.append(str(value))
            else:
                fragments.append("payload ->> %s = %s")
                parameters.extend([field, str(value).lower() if isinstance(value, bool) else str(value)])
        return (" where " + " and ".join(fragments), parameters) if fragments else ("", parameters)

    def _select_rows(self) -> list[tuple[Any, ...]]:
        where_sql, parameters = self._where_sql()
        order_sql = ""
        if self._state.order_field:
            order_sql = " order by payload ->> %s " + ("desc" if self._state.descending else "asc")
            parameters.append(self._state.order_field)
        limit_sql = ""
        if self._state.limit_count is not None:
            limit_sql = " limit %s"
            parameters.append(self._state.limit_count)
        vector_column = ", embedding::text" if self.table in {"vector_library_records", "approved_exemplars"} else ""
        query = f"select id, payload, owner_id::text, legacy_uid, secret_payload{vector_column} from public.{self.table}{where_sql}{order_sql}{limit_sql}"
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return list(cursor.fetchall())

    def _count(self) -> int:
        where_sql, parameters = self._where_sql()
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"select count(*) from public.{self.table}{where_sql}", parameters)
                row = cursor.fetchone()
                return int(row[0] if row else 0)

    def _fetch_one(self, document_id: str) -> dict[str, Any] | None:
        vector_column = ", embedding::text" if self.table in {"vector_library_records", "approved_exemplars"} else ""
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"select id, payload, owner_id::text, legacy_uid, secret_payload{vector_column} from public.{self.table} where id = %s",
                    (document_id,),
                )
                row = cursor.fetchone()
        return self._row_payload(row) if row else None

    def _row_payload(self, row: tuple[Any, ...]) -> dict[str, Any]:
        payload = dict(row[1] or {})
        if row[2]:
            payload["uid"] = row[2]
        elif row[3] and "uid" not in payload:
            payload["uid"] = row[3]
        if row[4] is not None:
            payload.update(decrypt_secret_payload(row[4]))
        if len(row) > 5 and row[5]:
            vector = [float(item) for item in str(row[5]).strip("[]").split(",") if item]
            payload["vector"] = vector
            payload["embedding"] = vector
        return payload

    def _upsert(self, document_id: str, payload: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        clean = dict(payload)
        secret_payload: bytes | None = None
        if self.table == "google_drive_connections":
            secrets = {key: clean.pop(key) for key in list(clean) if key in SECRET_FIELDS}
            if secrets:
                secret_payload = encrypt_secret_payload(secrets)
        owner_id = _uuid_or_none(clean.get("uid")) or (_uuid_or_none(document_id) if self.table == "profiles" else None)
        legacy_uid = None if owner_id else (str(clean.get("uid")) if clean.get("uid") else None)
        source_payload = dict(clean)
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    insert into public.{self.table}
                      (id, owner_id, legacy_uid, payload, source_payload, source_collection,
                       source_document_id, source_checksum, migrated_at, updated_at, secret_payload,
                       status, job_position, action, file_type, collection_key)
                    values (%s, %s::uuid, %s, %s, %s, %s, %s, %s, now(), now(), %s, %s, %s, %s, %s, %s)
                    on conflict (id) do update set
                      owner_id = excluded.owner_id,
                      legacy_uid = excluded.legacy_uid,
                      payload = excluded.payload,
                      source_payload = excluded.source_payload,
                      source_checksum = excluded.source_checksum,
                      updated_at = now(),
                      status = excluded.status,
                      job_position = excluded.job_position,
                      action = excluded.action,
                      file_type = excluded.file_type,
                      collection_key = excluded.collection_key,
                      secret_payload = coalesce(excluded.secret_payload, public.{self.table}.secret_payload)
                    """,
                    (
                        document_id,
                        owner_id,
                        legacy_uid,
                        Jsonb(clean),
                        Jsonb(source_payload),
                        self.source_collection,
                        document_id,
                        _checksum(source_payload),
                        secret_payload,
                        clean.get("status"),
                        clean.get("jobPosition"),
                        clean.get("action"),
                        clean.get("fileType"),
                        clean.get("collectionKey"),
                    ),
                )
                if self.table in {"vector_library_records", "approved_exemplars"}:
                    vector_value = clean.get("vector") or clean.get("embedding")
                    vector_text = None
                    if isinstance(vector_value, list) and len(vector_value) == 768:
                        vector_text = "[" + ",".join(str(float(value)) for value in vector_value) + "]"
                    cursor.execute(
                        f"""
                        update public.{self.table}
                        set embedding = coalesce(%s::vector, embedding),
                            embedding_model = coalesce(%s, embedding_model),
                            vector_index_version = coalesce(%s, vector_index_version)
                        where id = %s
                        """,
                        (
                            vector_text,
                            clean.get("embeddingModel") or clean.get("vectorModel"),
                            clean.get("vectorIndexVersion"),
                            document_id,
                        ),
                    )
                if self.table == "approved_exemplars":
                    cursor.execute(
                        """
                        update public.approved_exemplars
                        set approved = %s, rubric_version = %s
                        where id = %s
                        """,
                        (bool(clean.get("approved")), clean.get("rubricVersion"), document_id),
                    )
            connection.commit()

    def _delete(self, document_id: str) -> None:
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"delete from public.{self.table} where id = %s", (document_id,))
            connection.commit()


class PostgresDocumentDatabase:
    def collection(self, name: str) -> PostgresCollectionReference:
        return PostgresCollectionReference(name)
