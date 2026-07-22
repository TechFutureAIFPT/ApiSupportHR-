from __future__ import annotations

import asyncio
import copy
import traceback
import uuid
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.integrations import redis_cache
from app.repositories.postgres import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize
from app.services.cv_pipeline_service import run_smart_cv_analysis
from app.services.security_service import enter_analysis_job, leave_analysis_job


JobRecord = dict[str, Any]

_jobs: dict[str, JobRecord] = {}
_jobs_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_cache_key(job_id: str) -> str:
    return f"supporthr:analysis:job:{job_id}"


def _job_slot_key(uid: str) -> str:
    return f"supporthr:analysis:slots:{uid}"


def _source_text_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "jdText": str(payload.get("jd_text") or ""),
        "cvTexts": [
            {
                "fileName": str(entry.get("file_name") or entry.get("fileName") or "unknown-file"),
                "text": str(entry.get("text") or ""),
            }
            for entry in list(payload.get("cv_entries") or [])
            if isinstance(entry, dict)
        ],
    }


def _public_job(record: JobRecord) -> JobRecord:
    public = {
        "job_id": record["job_id"],
        "status": record["status"],
        "progress": record.get("progress", 0.0),
        "message": record.get("message", ""),
        "result": record.get("result"),
        "error": record.get("error"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }
    return copy.deepcopy(public)


def _persist_job_snapshot(record: JobRecord) -> None:
    if not record.get("owner_uid"):
        return
    try:
        repo.analysis_jobs().document(record["job_id"]).set(
            {
                "jobId": record["job_id"],
                "jobType": record.get("job_type", "analysis"),
                "uid": record.get("owner_uid"),
                "email": record.get("owner_email", ""),
                "status": record.get("status"),
                "progress": record.get("progress", 0.0),
                "message": record.get("message", ""),
                "result": record.get("result"),
                "error": record.get("error"),
                "sourceTexts": record.get("source_texts") or {},
                "createdAt": record.get("created_at"),
                "updatedAt": record.get("updated_at"),
            },
            merge=True,
        )
    except Exception as error:  # pragma: no cover - Supabase availability depends on runtime config
        print(f"[AnalysisJob] Supabase snapshot skipped for {record['job_id']}: {error}")


def _persist_job_record(record: JobRecord) -> bool:
    snapshot = copy.deepcopy(record)
    with _jobs_lock:
        _jobs[record["job_id"]] = snapshot

    settings = get_settings()
    redis_saved = redis_cache.set_json(
        _job_cache_key(record["job_id"]),
        snapshot,
        settings.analysis_job_result_ttl_seconds,
    )
    _persist_job_snapshot(snapshot)
    return redis_saved


def _record_from_supabase(job_id: str) -> JobRecord | None:
    try:
        document = repo.get_document(repo.analysis_jobs(), job_id)
        if not document.exists:
            return None
        data = serialize(document.to_dict() or {})
        return {
            "job_id": str(data.get("jobId") or job_id),
            "job_type": str(data.get("jobType") or "analysis"),
            "status": str(data.get("status") or "processing"),
            "progress": float(data.get("progress") or 0.0),
            "message": str(data.get("message") or ""),
            "result": data.get("result"),
            "error": data.get("error"),
            "owner_uid": data.get("uid"),
            "owner_email": data.get("email", ""),
            "created_at": data.get("createdAt"),
            "updated_at": data.get("updatedAt"),
        }
    except Exception:  # pragma: no cover - Supabase availability depends on runtime config
        return None


def _load_job_record(job_id: str) -> JobRecord | None:
    with _jobs_lock:
        record = copy.deepcopy(_jobs.get(job_id))
    if record is not None:
        return record

    cached = redis_cache.get_json(_job_cache_key(job_id))
    if isinstance(cached, dict):
        return copy.deepcopy(cached)
    return _record_from_supabase(job_id)


def _set_job(job_id: str, **updates: Any) -> JobRecord:
    current = _load_job_record(job_id)
    if current is None:
        raise KeyError(f"Analysis job not found: {job_id}")
    current.update(updates)
    current["updated_at"] = _now_iso()
    _persist_job_record(current)
    return current


def _resolve_execution_mode() -> str:
    settings = get_settings()
    if settings.analysis_job_mode == "in_process":
        return "in_process"

    redis_ready = redis_cache.ping()
    if settings.analysis_job_mode == "redis" and not redis_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis queue is required but unavailable.",
        )
    return "redis" if redis_ready else "in_process"


def _acquire_execution_slot(job_id: str, execution_mode: str, user: AuthenticatedUser | None) -> None:
    if user is None:
        return
    if execution_mode == "in_process":
        enter_analysis_job(user.uid)
        return

    settings = get_settings()
    acquired = redis_cache.acquire_slot(
        _job_slot_key(user.uid),
        job_id,
        settings.analysis_job_max_concurrency_per_user,
        settings.analysis_job_lease_seconds,
    )
    if acquired is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis concurrency control is unavailable.",
        )
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Mỗi tài khoản chỉ được chạy tối đa "
                f"{settings.analysis_job_max_concurrency_per_user} phiên phân tích song song."
            ),
        )


def _release_execution_slot(record: JobRecord) -> None:
    uid = str(record.get("owner_uid") or "")
    if not uid:
        return
    if record.get("execution_mode") == "redis":
        redis_cache.release_slot(_job_slot_key(uid), str(record["job_id"]))
        return
    leave_analysis_job(uid)


async def run_analysis_job(
    job_id: str,
    payload: dict[str, Any],
    current_user: AuthenticatedUser | None,
) -> None:
    try:
        _set_job(
            job_id,
            status="processing",
            progress=0.1,
            message="Module 1: translating documents and building local routing metadata.",
        )
        result = await run_smart_cv_analysis(
            str(payload.get("jd_text") or ""),
            dict(payload.get("weights") or {}),
            dict(payload.get("hard_filters") or {}),
            list(payload.get("cv_entries") or []),
            current_user=current_user,
        )
        _set_job(
            job_id,
            status="completed",
            progress=1.0,
            message="Analysis completed.",
            result={
                "candidates": result.get("candidates") or [],
                "pipeline": result.get("pipeline") or {},
            },
            error=None,
            payload=None,
        )
    except Exception as error:
        _set_job(
            job_id,
            status="failed",
            progress=1.0,
            message="Analysis failed.",
            result=None,
            error=str(error),
            traceback=traceback.format_exc(),
            payload=None,
        )
    finally:
        record = _load_job_record(job_id)
        if record is not None:
            _release_execution_slot(record)


async def run_vector_rebuild_job(
    job_id: str,
    payload: dict[str, Any],
    current_user: AuthenticatedUser,
) -> None:
    try:
        _set_job(
            job_id,
            status="processing",
            progress=0.1,
            message="Rebuilding uploaded-file vector index.",
        )
        from app.services.vector_index_service import rebuild_uploaded_file_vector_index

        result = await asyncio.to_thread(
            rebuild_uploaded_file_vector_index,
            current_user,
            int(payload.get("limit_count") or 200),
        )
        _set_job(
            job_id,
            status="completed",
            progress=1.0,
            message="Vector index rebuild completed.",
            result=result,
            error=None,
            payload=None,
        )
    except Exception as error:
        _set_job(
            job_id,
            status="failed",
            progress=1.0,
            message="Vector index rebuild failed.",
            result=None,
            error=str(error),
            traceback=traceback.format_exc(),
            payload=None,
        )
    finally:
        record = _load_job_record(job_id)
        if record is not None:
            _release_execution_slot(record)


def start_analysis_job(payload: dict[str, Any], current_user: AuthenticatedUser | None = None) -> JobRecord:
    settings = get_settings()
    execution_mode = _resolve_execution_mode()
    job_id = uuid.uuid4().hex
    _acquire_execution_slot(job_id, execution_mode, current_user)

    now = _now_iso()
    record: JobRecord = {
        "job_id": job_id,
        "job_type": "analysis",
        "status": "queued" if execution_mode == "redis" else "processing",
        "progress": 0.0,
        "message": "Analysis job queued." if execution_mode == "redis" else "Analysis job accepted.",
        "result": None,
        "error": None,
        "owner_uid": current_user.uid if current_user else None,
        "owner_email": current_user.email if current_user else "",
        "source_texts": _source_text_payload(payload),
        "payload": copy.deepcopy(payload) if execution_mode == "redis" else None,
        "execution_mode": execution_mode,
        "created_at": now,
        "updated_at": now,
    }

    redis_saved = _persist_job_record(record)
    if execution_mode == "redis":
        message_id = redis_cache.stream_add(
            settings.analysis_job_queue_key,
            {"job_id": job_id},
            settings.analysis_job_stream_max_length,
        )
        if not redis_saved or not message_id:
            _release_execution_slot(record)
            _set_job(
                job_id,
                status="failed",
                progress=1.0,
                message="Analysis queue is unavailable.",
                error="Unable to persist or enqueue the analysis job.",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to enqueue analysis job.",
            )
    else:
        asyncio.create_task(run_analysis_job(job_id, copy.deepcopy(payload), current_user))
    return _public_job(record)


def start_vector_rebuild_job(current_user: AuthenticatedUser, *, limit_count: int = 200) -> JobRecord:
    settings = get_settings()
    execution_mode = _resolve_execution_mode()
    job_id = uuid.uuid4().hex
    _acquire_execution_slot(job_id, execution_mode, current_user)
    payload = {"limit_count": min(max(1, int(limit_count)), 500)}
    now = _now_iso()
    record: JobRecord = {
        "job_id": job_id,
        "job_type": "vector_rebuild",
        "status": "queued" if execution_mode == "redis" else "processing",
        "progress": 0.0,
        "message": "Vector rebuild queued." if execution_mode == "redis" else "Vector rebuild accepted.",
        "result": None,
        "error": None,
        "owner_uid": current_user.uid,
        "owner_email": current_user.email,
        "source_texts": {},
        "payload": copy.deepcopy(payload) if execution_mode == "redis" else None,
        "execution_mode": execution_mode,
        "created_at": now,
        "updated_at": now,
    }
    redis_saved = _persist_job_record(record)
    if execution_mode == "redis":
        message_id = redis_cache.stream_add(
            settings.analysis_job_queue_key,
            {"job_id": job_id},
            settings.analysis_job_stream_max_length,
        )
        if not redis_saved or not message_id:
            _release_execution_slot(record)
            _set_job(
                job_id,
                status="failed",
                progress=1.0,
                message="Vector rebuild queue is unavailable.",
                error="Unable to persist or enqueue the vector rebuild job.",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to enqueue vector rebuild job.",
            )
    else:
        asyncio.create_task(run_vector_rebuild_job(job_id, payload, current_user))
    return _public_job(record)


def ensure_analysis_consumer_group() -> bool:
    settings = get_settings()
    return redis_cache.ensure_stream_group(
        settings.analysis_job_queue_key,
        settings.analysis_job_consumer_group,
    )


def dequeue_analysis_job(consumer_name: str, timeout_seconds: int = 5) -> tuple[str, str] | None:
    settings = get_settings()
    message = redis_cache.stream_claim_stale(
        settings.analysis_job_queue_key,
        settings.analysis_job_consumer_group,
        consumer_name,
        settings.analysis_job_reclaim_idle_seconds * 1000,
    )
    if message is None:
        message = redis_cache.stream_read_group(
            settings.analysis_job_queue_key,
            settings.analysis_job_consumer_group,
            consumer_name,
            timeout_seconds * 1000,
        )
    if message is None:
        return None
    message_id, item = message
    job_id = str(item.get("job_id") or "").strip() if isinstance(item, dict) else ""
    return message_id, job_id


def acknowledge_analysis_job(message_id: str) -> bool:
    settings = get_settings()
    return redis_cache.stream_ack(
        settings.analysis_job_queue_key,
        settings.analysis_job_consumer_group,
        message_id,
    )


def touch_analysis_job_message(message_id: str, consumer_name: str) -> bool:
    settings = get_settings()
    return redis_cache.stream_touch(
        settings.analysis_job_queue_key,
        settings.analysis_job_consumer_group,
        consumer_name,
        message_id,
    )


def remove_analysis_consumer(consumer_name: str) -> bool:
    settings = get_settings()
    return redis_cache.stream_delete_consumer_if_idle(
        settings.analysis_job_queue_key,
        settings.analysis_job_consumer_group,
        consumer_name,
    )


def cleanup_analysis_consumers() -> int:
    settings = get_settings()
    return redis_cache.stream_cleanup_idle_consumers(
        settings.analysis_job_queue_key,
        settings.analysis_job_consumer_group,
        settings.analysis_job_reclaim_idle_seconds * 1000,
    )


async def execute_queued_analysis_job(job_id: str) -> bool:
    record = _load_job_record(job_id)
    if record is None or record.get("status") not in {"queued", "processing"}:
        return False
    payload = record.get("payload")
    if not isinstance(payload, dict):
        _set_job(
            job_id,
            status="failed",
            progress=1.0,
            message="Analysis failed.",
            error="Queued job payload is missing.",
        )
        _release_execution_slot(record)
        return False

    current_user = None
    if record.get("owner_uid"):
        current_user = AuthenticatedUser(
            uid=str(record["owner_uid"]),
            email=str(record.get("owner_email") or ""),
        )
    if record.get("job_type") == "vector_rebuild":
        if current_user is None:
            _set_job(job_id, status="failed", progress=1.0, message="Vector index rebuild failed.", error="Owner is missing.")
            _release_execution_slot(record)
            return False
        await run_vector_rebuild_job(job_id, payload, current_user)
    else:
        await run_analysis_job(job_id, payload, current_user)
    return True


def get_analysis_job(job_id: str, current_user: AuthenticatedUser | None = None) -> JobRecord | None:
    record = _load_job_record(job_id)
    if record is None:
        return None

    owner_uid = record.get("owner_uid")
    if owner_uid and (current_user is None or current_user.uid != owner_uid):
        return None
    return _public_job(record)
