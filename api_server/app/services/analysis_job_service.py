from __future__ import annotations

import asyncio
import copy
import traceback
import uuid
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize
from app.services.cv_pipeline_service import run_smart_cv_analysis


JobRecord = dict[str, Any]

_jobs: dict[str, JobRecord] = {}
_jobs_lock = RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    except Exception as error:  # pragma: no cover - Firebase availability depends on runtime config
        print(f"[AnalysisJob] Firestore snapshot skipped for {record['job_id']}: {error}")


def _set_job(job_id: str, **updates: Any) -> JobRecord:
    with _jobs_lock:
        current = _jobs.get(job_id)
        if not current:
            raise KeyError(f"Analysis job not found: {job_id}")
        current.update(updates)
        current["updated_at"] = _now_iso()
        snapshot = copy.deepcopy(current)
    _persist_job_snapshot(snapshot)
    return snapshot


async def _run_job(job_id: str, payload: dict[str, Any], current_user: AuthenticatedUser | None) -> None:
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
        )


def start_analysis_job(payload: dict[str, Any], current_user: AuthenticatedUser | None = None) -> JobRecord:
    job_id = uuid.uuid4().hex
    now = _now_iso()
    record: JobRecord = {
        "job_id": job_id,
        "status": "processing",
        "progress": 0.0,
        "message": "Analysis job accepted.",
        "result": None,
        "error": None,
        "owner_uid": current_user.uid if current_user else None,
        "owner_email": current_user.email if current_user else "",
        "source_texts": _source_text_payload(payload),
        "created_at": now,
        "updated_at": now,
    }
    with _jobs_lock:
        _jobs[job_id] = copy.deepcopy(record)

    _persist_job_snapshot(record)
    asyncio.create_task(_run_job(job_id, copy.deepcopy(payload), current_user))
    return _public_job(record)


def get_analysis_job(job_id: str, current_user: AuthenticatedUser | None = None) -> JobRecord | None:
    with _jobs_lock:
        record = copy.deepcopy(_jobs.get(job_id))

    if record is None:
        try:
            document = repo.get_document(repo.analysis_jobs(), job_id)
            if document.exists:
                data = serialize(document.to_dict() or {})
                record = {
                    "job_id": str(data.get("jobId") or job_id),
                    "status": str(data.get("status") or "processing"),
                    "progress": float(data.get("progress") or 0.0),
                    "message": str(data.get("message") or ""),
                    "result": data.get("result"),
                    "error": data.get("error"),
                    "owner_uid": data.get("uid"),
                    "created_at": data.get("createdAt"),
                    "updated_at": data.get("updatedAt"),
                }
        except Exception:  # pragma: no cover - Firebase availability depends on runtime config
            record = None

    if record is None:
        return None

    owner_uid = record.get("owner_uid")
    if owner_uid:
        if current_user is None or current_user.uid != owner_uid:
            return None
    return _public_job(record)
