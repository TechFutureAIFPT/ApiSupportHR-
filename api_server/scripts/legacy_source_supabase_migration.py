from __future__ import annotations

"""Offline legacy-source export/import utility; never installed in the production runtime."""

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from dotenv import load_dotenv


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


ARCHIVE_VERSION = 1
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
SYSTEM_COLLECTIONS = {"approvedExemplars", "vectorLibraryRecords"}
SECRET_FIELDS = {"accessToken", "refreshToken"}


def _target_collisions(firestore_data: dict[str, list[dict[str, Any]]]) -> list[str]:
    seen: set[tuple[str, str]] = set()
    collisions: list[str] = []
    for collection, documents in firestore_data.items():
        table = COLLECTION_TABLES.get(collection)
        if not table:
            continue
        for document in documents:
            key = (table, str(document.get("id") or ""))
            if key in seen:
                collisions.append(f"{table}/{key[1]}")
            seen.add(key)
    return sorted(set(collisions))


def _auth_summary(users: list[dict[str, Any]]) -> dict[str, Any]:
    provider_counts: dict[str, int] = {}
    for user in users:
        for provider in user.get("provider_ids") or []:
            provider_counts[str(provider)] = provider_counts.get(str(provider), 0) + 1
    emails = [str(user.get("email") or "").strip().lower() for user in users if user.get("email")]
    return {
        "users": len(users),
        "password_users": sum(1 for user in users if user.get("password_hash")),
        "verified_emails": sum(1 for user in users if user.get("email_verified")),
        "provider_counts": provider_counts,
        "duplicate_emails": sorted({email for email in emails if emails.count(email) > 1}),
    }


def _load_environment() -> None:
    load_dotenv(API_ROOT / ".env")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, bytes):
        return {"__bytes_b64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_map"):
        return _json_safe(value.to_map())
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {"latitude": float(value.latitude), "longitude": float(value.longitude)}
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _b64_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return base64.b64encode(bytes(value)).decode("ascii")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _checksum(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _archive_key() -> bytes:
    raw = os.getenv("MIGRATION_ARCHIVE_KEY", "").strip()
    if not raw:
        raise RuntimeError("MIGRATION_ARCHIVE_KEY is required (base64-encoded 32-byte key).")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as error:
        raise RuntimeError("MIGRATION_ARCHIVE_KEY must be valid base64.") from error
    if len(key) != 32:
        raise RuntimeError("MIGRATION_ARCHIVE_KEY must decode to exactly 32 bytes.")
    return key


def _encrypt_json(payload: dict[str, Any]) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    encrypted = AESGCM(_archive_key()).encrypt(nonce, _canonical_json(payload), b"supporthr-firebase-archive-v1")
    return b"SHR1" + nonce + encrypted


def _decrypt_json(raw: bytes) -> dict[str, Any]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not raw.startswith(b"SHR1") or len(raw) < 32:
        raise RuntimeError("Unsupported or corrupt migration archive.")
    decoded = AESGCM(_archive_key()).decrypt(raw[4:16], raw[16:], b"supporthr-firebase-archive-v1")
    payload = json.loads(decoded.decode("utf-8"))
    if int(payload.get("archive_version", 0)) != ARCHIVE_VERSION:
        raise RuntimeError("Unsupported migration archive version.")
    return payload


def _safe_output_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[4]
    if path == repo_root or repo_root in path.parents:
        raise RuntimeError(f"Migration archives must be outside the Git workspace: {repo_root}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _firebase_context():
    from firebase_admin import credentials, firestore, get_app, initialize_app

    app_name = "supporthr-legacy-migration"
    try:
        app = get_app(app_name)
    except ValueError:
        raw_service_account = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw_service_account:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is required for legacy-source migration.")
        try:
            service_account = json.loads(raw_service_account)
        except json.JSONDecodeError as error:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON must be valid JSON.") from error

        options: dict[str, str] = {}
        database_url = os.getenv("FIREBASE_DATABASE_URL", "").strip()
        storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
        if database_url:
            options["databaseURL"] = database_url
        if storage_bucket:
            options["storageBucket"] = storage_bucket
        app = initialize_app(
            credentials.Certificate(service_account),
            options=options or None,
            name=app_name,
        )
    return app, firestore.client(app=app)


def _fetch_rtdb_chatbot(app: Any) -> dict[str, Any]:
    from google.auth.transport.requests import Request as GoogleRequest

    database_url = os.getenv("FIREBASE_DATABASE_URL", "").strip().rstrip("/")
    if not database_url:
        return {}
    credential = app.credential.get_credential()
    credential.refresh(GoogleRequest())
    request = Request(
        f"{database_url}/chatbot.json",
        headers={"Authorization": f"Bearer {credential.token}"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _json_safe(payload if isinstance(payload, dict) else {})


def _storage_preflight(app: Any) -> dict[str, Any]:
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if not bucket_name:
        return {"configured": False, "exists": False, "objects": 0}
    try:
        from firebase_admin import storage

        bucket = storage.bucket(name=bucket_name, app=app)
        if not bucket.exists():
            return {"configured": True, "exists": False, "objects": 0, "bucket": bucket_name}
        object_count = sum(1 for _ in bucket.list_blobs())
        return {"configured": True, "exists": True, "objects": object_count, "bucket": bucket_name}
    except Exception as error:
        return {
            "configured": True,
            "exists": False,
            "objects": 0,
            "bucket": bucket_name,
            "error": f"{type(error).__name__}: {error}",
        }


def _export_source() -> dict[str, Any]:
    from firebase_admin import auth

    app, firestore_client = _firebase_context()
    collections: dict[str, list[dict[str, Any]]] = {}
    for collection_ref in sorted(firestore_client.collections(), key=lambda item: item.id):
        documents: list[dict[str, Any]] = []
        for snapshot in collection_ref.stream():
            payload = _json_safe(snapshot.to_dict() or {})
            documents.append(
                {
                    "id": snapshot.id,
                    "payload": payload,
                    "create_time": _json_safe(snapshot.create_time),
                    "update_time": _json_safe(snapshot.update_time),
                    "checksum": _checksum(payload),
                }
            )
        collections[collection_ref.id] = documents

    users: list[dict[str, Any]] = []
    page = auth.list_users(app=app)
    while page:
        for user in page.users:
            users.append(
                {
                    "uid": user.uid,
                    "email": user.email,
                    "email_verified": bool(user.email_verified),
                    "display_name": user.display_name,
                    "photo_url": user.photo_url,
                    "disabled": bool(user.disabled),
                    "provider_ids": sorted(item.provider_id for item in user.provider_data),
                    "password_hash": _b64_value(user.password_hash),
                    "password_salt": _b64_value(user.password_salt),
                    "custom_claims": _json_safe(user.custom_claims or {}),
                }
            )
        page = page.get_next_page()

    rtdb_chatbot = _fetch_rtdb_chatbot(app)
    return {
        "archive_version": ARCHIVE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "firebase_project_id": os.getenv("FIREBASE_PROJECT_ID", "").strip(),
        "auth_users": users,
        "firestore": collections,
        "rtdb_chatbot": rtdb_chatbot,
        "storage_preflight": _storage_preflight(app),
    }


def command_preflight(_: argparse.Namespace) -> int:
    archive = _export_source()
    counts = {name: len(documents) for name, documents in archive["firestore"].items()}
    unknown = sorted(set(counts) - set(COLLECTION_TABLES))
    collisions = _target_collisions(archive["firestore"])
    rtdb_sessions = sum(
        len(sessions) for sessions in archive["rtdb_chatbot"].values() if isinstance(sessions, dict)
    )
    print(json.dumps({
        "auth": _auth_summary(archive["auth_users"]),
        "firestore_collections": len(counts),
        "firestore_documents": sum(counts.values()),
        "collection_counts": counts,
        "rtdb_chatbot_sessions": rtdb_sessions,
        "storage": archive["storage_preflight"],
        "unknown_collections": unknown,
        "target_id_collisions": collisions,
    }, ensure_ascii=False, indent=2))
    return 1 if unknown or collisions else 0


def command_export(args: argparse.Namespace) -> int:
    path = _safe_output_path(args.output)
    archive = _export_source()
    unknown = sorted(set(archive["firestore"]) - set(COLLECTION_TABLES))
    if unknown:
        raise RuntimeError(f"Refusing export/import workflow until collections are mapped: {unknown}")
    collisions = _target_collisions(archive["firestore"])
    if collisions:
        raise RuntimeError(f"Target table/document ID collisions must be resolved explicitly: {collisions}")
    encrypted = _encrypt_json(archive)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)
    summary = {
        "archive_sha256": hashlib.sha256(encrypted).hexdigest(),
        "auth": _auth_summary(archive["auth_users"]),
        "firestore_documents": sum(len(items) for items in archive["firestore"].values()),
        "firestore_collections": {name: len(items) for name, items in archive["firestore"].items()},
        "rtdb_chatbot_sessions": sum(
            len(items) for items in archive["rtdb_chatbot"].values() if isinstance(items, dict)
        ),
        "storage": archive["storage_preflight"],
    }
    path.with_suffix(path.suffix + ".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"archive": str(path), **summary}, ensure_ascii=False, indent=2))
    return 0


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _trim_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).strip(): _trim_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_trim_keys(item) for item in value]
    return value


def _secret_key() -> bytes:
    raw = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError("DATA_ENCRYPTION_KEY is required for Google Drive token migration.")
    key = base64.b64decode(raw, validate=True)
    if len(key) != 32:
        raise RuntimeError("DATA_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def _encrypt_secret_payload(value: dict[str, Any]) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ciphertext = AESGCM(_secret_key()).encrypt(nonce, _canonical_json(value), b"supporthr-data-secret-v1")
    return b"SHDS1" + nonce + ciphertext


def _owner_lookup(connection: Any, archive: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute("select lower(email), array_agg(id::text) from auth.users where email is not null group by lower(email)")
        grouped_users = {email: ids for email, ids in cursor.fetchall()}
    duplicate_emails = sorted(email for email, ids in grouped_users.items() if len(ids) != 1)
    if duplicate_emails:
        raise RuntimeError(f"Supabase Auth contains non-unique emails: {duplicate_emails}")
    email_to_supabase = {email: ids[0] for email, ids in grouped_users.items()}

    uid_to_supabase: dict[str, str] = {}
    verified_email_to_supabase: dict[str, str] = {}
    with connection.cursor() as cursor:
        for user in archive["auth_users"]:
            uid = str(user.get("uid") or "")
            email = str(user.get("email") or "").strip().lower()
            supabase_user_id = email_to_supabase.get(email)
            if supabase_user_id:
                uid_to_supabase[uid] = supabase_user_id
                if bool(user.get("email_verified")):
                    verified_email_to_supabase[email] = supabase_user_id
            cursor.execute(
                """
                insert into public.legacy_identity_map(firebase_uid, supabase_user_id, email, match_method)
                values (%s, %s::uuid, %s, %s)
                on conflict (firebase_uid) do update set
                  supabase_user_id = excluded.supabase_user_id,
                  email = excluded.email,
                  match_method = excluded.match_method,
                  updated_at = now()
                """,
                (uid, supabase_user_id, email or None, "uid" if supabase_user_id else "unresolved"),
            )
    return uid_to_supabase, verified_email_to_supabase


def _resolve_owner(payload: dict[str, Any], uid_map: dict[str, str], email_map: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    legacy_uid = str(payload.get("uid") or "").strip() or None
    if legacy_uid and legacy_uid in uid_map:
        return uid_map[legacy_uid], legacy_uid, "uid"
    for key in ("email", "userEmail"):
        email = str(payload.get(key) or "").strip().lower()
        if email and email in email_map:
            return email_map[email], legacy_uid, "email"
    return None, legacy_uid, "unresolved"


def _typed_columns(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "job_position": payload.get("jobPosition"),
        "action": payload.get("action"),
        "file_type": payload.get("fileType"),
        "collection_key": payload.get("collectionKey"),
        "expires_at": _parse_timestamp(payload.get("expiresAt")),
    }


def _upsert_document(
    connection: Any,
    *,
    table: str,
    collection: str,
    document: dict[str, Any],
    owner_id: str | None,
    legacy_uid: str | None,
) -> None:
    from psycopg import sql
    from psycopg.types.json import Jsonb

    source_payload = json.loads(json.dumps(document["payload"]))
    operational_payload = _trim_keys(json.loads(json.dumps(source_payload)))
    secret_payload: bytes | None = None
    if collection == "googleDriveConnections":
        secrets = {field: operational_payload.pop(field) for field in SECRET_FIELDS if operational_payload.get(field)}
        for field in SECRET_FIELDS:
            source_payload.pop(field, None)
        if secrets:
            secret_payload = _encrypt_secret_payload(secrets)
    if owner_id:
        operational_payload["uid"] = owner_id
    if collection == "approvedExemplars" and not operational_payload.get("status"):
        operational_payload["status"] = "pending"
        operational_payload["approved"] = False

    vector_value = operational_payload.get("vector") or operational_payload.get("embedding")
    legacy_embedding = [float(item) for item in vector_value] if isinstance(vector_value, list) else None
    typed = _typed_columns(operational_payload)
    created_at = _parse_timestamp(operational_payload.get("createdAt") or operational_payload.get("timestamp"))
    updated_at = _parse_timestamp(operational_payload.get("updatedAt") or operational_payload.get("timestamp"))
    query = sql.SQL(
        """
        insert into public.{table}(
          id, owner_id, legacy_uid, payload, source_payload,
          source_collection, source_document_id, source_checksum,
          source_created_at, source_updated_at, created_at, updated_at,
          status, job_position, action, file_type, collection_key, expires_at,
          secret_payload{vector_columns}
        ) values (
          %(id)s, %(owner_id)s::uuid, %(legacy_uid)s, %(payload)s, %(source_payload)s,
          %(source_collection)s, %(source_document_id)s, %(source_checksum)s,
          %(source_created_at)s, %(source_updated_at)s,
          coalesce(%(created_at)s, now()), coalesce(%(updated_at)s, now()),
          %(status)s, %(job_position)s, %(action)s, %(file_type)s, %(collection_key)s, %(expires_at)s,
          %(secret_payload)s{vector_values}
        )
        on conflict (id) do update set
          owner_id = excluded.owner_id,
          legacy_uid = excluded.legacy_uid,
          payload = excluded.payload,
          source_payload = excluded.source_payload,
          source_collection = excluded.source_collection,
          source_document_id = excluded.source_document_id,
          source_checksum = excluded.source_checksum,
          source_created_at = excluded.source_created_at,
          source_updated_at = excluded.source_updated_at,
          updated_at = excluded.updated_at,
          status = excluded.status,
          job_position = excluded.job_position,
          action = excluded.action,
          file_type = excluded.file_type,
          collection_key = excluded.collection_key,
          expires_at = excluded.expires_at,
          secret_payload = excluded.secret_payload
          {vector_updates}
        """
    ).format(
        table=sql.Identifier(table),
        vector_columns=sql.SQL(", legacy_embedding, embedding_model, vector_index_version") if table in {"vector_library_records", "approved_exemplars"} else sql.SQL(""),
        vector_values=sql.SQL(", %(legacy_embedding)s, %(embedding_model)s, %(vector_index_version)s") if table in {"vector_library_records", "approved_exemplars"} else sql.SQL(""),
        vector_updates=sql.SQL(", legacy_embedding = excluded.legacy_embedding, embedding_model = excluded.embedding_model, vector_index_version = excluded.vector_index_version") if table in {"vector_library_records", "approved_exemplars"} else sql.SQL(""),
    )
    params = {
        "id": str(document["id"]),
        "owner_id": owner_id,
        "legacy_uid": legacy_uid,
        "payload": Jsonb(operational_payload),
        "source_payload": Jsonb(source_payload),
        "source_collection": collection,
        "source_document_id": str(document["id"]),
        "source_checksum": str(document["checksum"]),
        "source_created_at": _parse_timestamp(document.get("create_time")),
        "source_updated_at": _parse_timestamp(document.get("update_time")),
        "created_at": created_at,
        "updated_at": updated_at,
        "secret_payload": secret_payload,
        "legacy_embedding": legacy_embedding,
        "embedding_model": operational_payload.get("vectorModel") or operational_payload.get("embeddingModel"),
        "vector_index_version": operational_payload.get("vectorIndexVersion"),
        **typed,
    }
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        if table == "approved_exemplars":
            cursor.execute(
                """
                update public.approved_exemplars
                set approved = %s, rubric_version = %s
                where id = %s
                """,
                (
                    bool(operational_payload.get("approved")),
                    operational_payload.get("rubricVersion"),
                    str(document["id"]),
                ),
            )


def command_import(args: argparse.Namespace) -> int:
    import psycopg
    from psycopg.types.json import Jsonb

    archive_bytes = Path(args.archive).resolve().read_bytes()
    archive = _decrypt_json(archive_bytes)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required.")
    unknown = sorted(set(archive["firestore"]) - set(COLLECTION_TABLES))
    if unknown:
        raise RuntimeError(f"No target mapping for collections: {unknown}")
    collisions = _target_collisions(archive["firestore"])
    if collisions:
        raise RuntimeError(f"Archive contains target table/document ID collisions: {collisions}")
    archive_checksum = hashlib.sha256(archive_bytes).hexdigest()

    with psycopg.connect(database_url, autocommit=False, prepare_threshold=None) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into public.migration_runs(source_project, archive_checksum, source_summary)
                values (%s, %s, %s) returning id::text
                """,
                (
                    archive.get("firebase_project_id"),
                    archive_checksum,
                    Jsonb({
                        "auth_users": len(archive["auth_users"]),
                        "firestore_documents": sum(len(items) for items in archive["firestore"].values()),
                    }),
                ),
            )
            run_id = cursor.fetchone()[0]

        uid_map, email_map = _owner_lookup(connection, archive)
        migrated = unresolved = 0
        for collection, documents in archive["firestore"].items():
            table = COLLECTION_TABLES[collection]
            for document in documents:
                payload = _trim_keys(document["payload"])
                if collection in SYSTEM_COLLECTIONS:
                    owner_id, legacy_uid, match_method = None, None, "system"
                else:
                    owner_id, legacy_uid, match_method = _resolve_owner(payload, uid_map, email_map)
                _upsert_document(
                    connection,
                    table=table,
                    collection=collection,
                    document=document,
                    owner_id=owner_id,
                    legacy_uid=legacy_uid,
                )
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        insert into public.migration_documents(
                          run_id, source_system, source_collection, source_document_id,
                          source_checksum, target_table, target_id, owner_id, status
                        ) values (%s::uuid, 'firestore', %s, %s, %s, %s, %s, %s::uuid, 'migrated')
                        """,
                        (run_id, collection, document["id"], document["checksum"], table, document["id"], owner_id),
                    )
                    if match_method == "unresolved":
                        unresolved += 1
                        cursor.execute(
                            """
                            insert into public.migration_unresolved_owners(
                              run_id, source_system, source_collection, source_document_id,
                              legacy_uid, legacy_email, reason
                            ) values (%s::uuid, 'firestore', %s, %s, %s, %s, 'No unique Firebase Auth owner match')
                            """,
                            (
                                run_id,
                                collection,
                                document["id"],
                                legacy_uid,
                                payload.get("email") or payload.get("userEmail"),
                            ),
                        )
                migrated += 1

        rtdb_count = 0
        with connection.cursor() as cursor:
            for legacy_uid, sessions in archive.get("rtdb_chatbot", {}).items():
                if not isinstance(sessions, dict):
                    continue
                owner_id = uid_map.get(legacy_uid)
                for session_id, payload in sessions.items():
                    checksum = _checksum(payload)
                    target_id = hashlib.sha256(f"{legacy_uid}:{session_id}".encode()).hexdigest()
                    cursor.execute(
                        """
                        insert into public.legacy_rtdb_chatbot_sessions(
                          id, owner_id, legacy_uid, session_id, payload, source_checksum
                        ) values (%s, %s::uuid, %s, %s, %s, %s)
                        on conflict (id) do update set
                          owner_id = excluded.owner_id,
                          payload = excluded.payload,
                          source_checksum = excluded.source_checksum,
                          migrated_at = now()
                        """,
                        (target_id, owner_id, legacy_uid, session_id, Jsonb(payload), checksum),
                    )
                    cursor.execute(
                        """
                        insert into public.migration_documents(
                          run_id, source_system, source_collection, source_document_id,
                          source_checksum, target_table, target_id, owner_id, status
                        ) values (%s::uuid, 'rtdb', 'chatbot', %s, %s, 'legacy_rtdb_chatbot_sessions', %s, %s::uuid, 'migrated')
                        """,
                        (run_id, f"{legacy_uid}/{session_id}", checksum, target_id, owner_id),
                    )
                    if not owner_id:
                        cursor.execute(
                            """
                            insert into public.migration_unresolved_owners(
                              run_id, source_system, source_collection, source_document_id, legacy_uid, reason
                            ) values (%s::uuid, 'rtdb', 'chatbot', %s, %s, 'Realtime Database UID not found in Firebase Auth')
                            """,
                            (run_id, session_id, legacy_uid),
                        )
                        unresolved += 1
                    rtdb_count += 1

            cursor.execute(
                """
                update public.migration_runs
                set status = 'completed', result_summary = %s, finished_at = now()
                where id = %s::uuid
                """,
                (Jsonb({"firestore_migrated": migrated, "rtdb_migrated": rtdb_count, "unresolved": unresolved}), run_id),
            )
        connection.commit()
    print(json.dumps({"run_id": run_id, "firestore_migrated": migrated, "rtdb_migrated": rtdb_count, "unresolved": unresolved}, indent=2))
    return 0


def command_reconcile(args: argparse.Namespace) -> int:
    import psycopg

    archive = _decrypt_json(Path(args.archive).resolve().read_bytes())
    expected_firestore = sum(len(items) for items in archive["firestore"].values())
    expected_rtdb = sum(len(items) for items in archive.get("rtdb_chatbot", {}).values() if isinstance(items, dict))
    expected_vector_count = len(archive["firestore"].get("vectorLibraryRecords", []))
    expected_pending_exemplars = sum(
        1
        for item in archive["firestore"].get("approvedExemplars", [])
        if not item.get("payload", {}).get("status")
        or not item.get("payload", {}).get("approved")
        or not item.get("payload", {}).get("rubricVersion")
    )
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required.")
    with psycopg.connect(database_url, prepare_threshold=None) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select id::text
            from public.migration_runs
            where status = 'completed'
            order by finished_at desc nulls last
            limit 1
            """
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("No completed migration run found.")
        run_id = row[0]
        mismatches: list[dict[str, str]] = []
        actual_firestore = 0
        for collection, documents in archive["firestore"].items():
            table = COLLECTION_TABLES[collection]
            cursor.execute(
                f"select source_document_id, source_checksum from public.{table} where source_collection = %s",
                (collection,),
            )
            actual = {str(document_id): str(checksum) for document_id, checksum in cursor.fetchall()}
            expected = {str(item["id"]): str(item["checksum"]) for item in documents}
            actual_firestore += sum(1 for document_id, checksum in expected.items() if actual.get(document_id) == checksum)
            for document_id, checksum in expected.items():
                if actual.get(document_id) != checksum:
                    mismatches.append({
                        "source": "firestore",
                        "collection": collection,
                        "id": document_id,
                        "expected": checksum,
                        "actual": actual.get(document_id, "missing"),
                    })

        actual_rtdb = 0
        for legacy_uid, sessions in archive.get("rtdb_chatbot", {}).items():
            if not isinstance(sessions, dict):
                continue
            for session_id, payload in sessions.items():
                target_id = hashlib.sha256(f"{legacy_uid}:{session_id}".encode()).hexdigest()
                cursor.execute(
                    "select source_checksum from public.legacy_rtdb_chatbot_sessions where id = %s",
                    (target_id,),
                )
                row = cursor.fetchone()
                expected_checksum = _checksum(payload)
                actual_checksum = str(row[0]) if row else "missing"
                if actual_checksum == expected_checksum:
                    actual_rtdb += 1
                else:
                    mismatches.append({
                        "source": "rtdb",
                        "collection": "chatbot",
                        "id": f"{legacy_uid}/{session_id}",
                        "expected": expected_checksum,
                        "actual": actual_checksum,
                    })

        expected_emails = sorted(
            str(user.get("email") or "").strip().lower()
            for user in archive["auth_users"]
            if str(user.get("email") or "").strip()
        )
        cursor.execute("select lower(email) from auth.users where email is not null order by lower(email)")
        actual_emails = [str(row[0]) for row in cursor.fetchall()]
        cursor.execute("select count(*) from auth.users")
        actual_auth_count = int(cursor.fetchone()[0])
        auth_match = expected_emails == actual_emails and actual_auth_count == len(archive["auth_users"])
        cursor.execute(
            "select count(*) from public.migration_unresolved_owners where run_id = %s::uuid",
            (run_id,),
        )
        unresolved = int(cursor.fetchone()[0])
        cursor.execute("select count(*) from public.vector_library_records where legacy_embedding is not null and cardinality(legacy_embedding) = 3072")
        legacy_vector_count = int(cursor.fetchone()[0])
        cursor.execute("select count(*) from public.vector_library_records where embedding is not null and vector_dims(embedding) = 768")
        runtime_vector_count = int(cursor.fetchone()[0])
        cursor.execute("select count(*) from public.approved_exemplars where approved = false and status = 'pending'")
        pending_exemplar_count = int(cursor.fetchone()[0])
        cursor.execute(
            """
            select count(*) from public.google_drive_connections
            where payload ?| array['accessToken','refreshToken']
               or source_payload ?| array['accessToken','refreshToken']
            """
        )
        plaintext_secret_count = int(cursor.fetchone()[0])
    success = (
        actual_firestore == expected_firestore
        and actual_rtdb == expected_rtdb
        and not mismatches
        and auth_match
        and legacy_vector_count == expected_vector_count
        and runtime_vector_count == expected_vector_count
        and pending_exemplar_count == expected_pending_exemplars
        and plaintext_secret_count == 0
    )
    result = {
        "run_id": run_id,
        "success": success,
        "firestore": {"expected": expected_firestore, "migrated": actual_firestore},
        "rtdb": {"expected": expected_rtdb, "migrated": actual_rtdb},
        "auth": {"expected": len(archive["auth_users"]), "actual": actual_auth_count, "email_set_match": auth_match},
        "vectors": {"expected": expected_vector_count, "legacy_3072": legacy_vector_count, "runtime_768": runtime_vector_count},
        "pending_exemplars": {"expected": expected_pending_exemplars, "actual": pending_exemplar_count},
        "plaintext_secret_records": plaintext_secret_count,
        "unresolved_owners": unresolved,
        "checksum_mismatches": mismatches[:100],
    }
    print(json.dumps(result, indent=2))
    return 0 if success else 2


def command_reembed(args: argparse.Namespace) -> int:
    """Create the current 768-dimension runtime vectors without touching legacy/source data."""
    import psycopg
    from psycopg.types.json import Jsonb

    from app.core.config import get_settings
    from app.services.gemini_service import embed_text

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required.")
    settings = get_settings()
    completed = 0
    with psycopg.connect(database_url, prepare_threshold=None) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select id, payload
                from public.vector_library_records
                where embedding is null
                order by id
                """
            )
            rows = list(cursor.fetchall())
        for document_id, raw_payload in rows:
            payload = dict(raw_payload or {})
            text_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"vector", "embedding", "embeddingVector", "cvEmbedding"}
            }
            source_text = json.dumps(text_payload, ensure_ascii=False, sort_keys=True, default=str)[:6000]
            vector = embed_text(
                source_text,
                model=settings.gemini_embedding_model,
                output_dimensionality=768,
                title=str(payload.get("name") or document_id),
            )
            payload["vector"] = vector
            payload["embeddingModel"] = settings.gemini_embedding_model
            payload["embeddingDimension"] = 768
            payload["vectorIndexVersion"] = settings.vector_index_version
            vector_text = "[" + ",".join(str(float(value)) for value in vector) + "]"
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update public.vector_library_records
                    set embedding = %s::vector,
                        embedding_model = %s,
                        vector_index_version = %s,
                        payload = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    (
                        vector_text,
                        settings.gemini_embedding_model,
                        settings.vector_index_version,
                        Jsonb(payload),
                        document_id,
                    ),
                )
            connection.commit()
            completed += 1
            print(f"reembedded={completed}/{len(rows)} id={document_id}")
    print(json.dumps({"reembedded": completed, "dimension": 768, "model": settings.gemini_embedding_model}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Encrypted, idempotent Firebase -> Supabase migration for SupportHR")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight", help="Read-only source inventory")
    preflight.set_defaults(handler=command_preflight)
    export = subparsers.add_parser("export", help="Create an encrypted source archive outside the Git workspace")
    export.add_argument("--output", required=True)
    export.set_defaults(handler=command_export)
    import_command = subparsers.add_parser("import", help="Idempotently import an encrypted archive")
    import_command.add_argument("--archive", required=True)
    import_command.set_defaults(handler=command_import)
    reconcile = subparsers.add_parser("reconcile", help="Compare archive totals with the latest completed migration")
    reconcile.add_argument("--archive", required=True)
    reconcile.set_defaults(handler=command_reconcile)
    reembed = subparsers.add_parser("reembed", help="Generate current 768-dimension runtime vectors")
    reembed.set_defaults(handler=command_reembed)
    return parser


def main() -> int:
    _load_environment()
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except Exception as error:
        print(f"migration_error={type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
