from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs, to_millis


MAX_HISTORY_ENTRIES_PER_USER = 100


def cleanup_synced_history(user: AuthenticatedUser, keep_count: int = MAX_HISTORY_ENTRIES_PER_USER) -> None:
    docs = list(repo.synced_history().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "timestamp")
    for doc in ordered[keep_count:]:
        doc.reference.delete()


def sync_history_entry(user: AuthenticatedUser, analysis_data: dict[str, Any]) -> str:
    candidates = list(analysis_data.get("candidates") or [])
    grades_count = {"A": 0, "B": 0, "C": 0}
    for candidate in candidates:
        grade = "C"
        if candidate.get("status") != "FAILED":
            grade = str(((candidate.get("analysis") or {}).get("Hạng")) or "C")
        if grade not in grades_count:
            grade = "C"
        grades_count[grade] += 1

    job = analysis_data.get("job") or {}
    doc_ref = repo.create_document(repo.synced_history())
    doc_ref.set(
        {
            "uid": user.uid,
            "email": user.email,
            "analysisData": analysis_data,
            "timestamp": repo.server_timestamp(),
            "jobPosition": str(job.get("position") or ""),
            "locationRequirement": str(job.get("locationRequirement") or ""),
            "totalCandidates": len(candidates),
            "gradesCount": grades_count,
        }
    )
    cleanup_synced_history(user, MAX_HISTORY_ENTRIES_PER_USER)
    return doc_ref.id


def get_synced_history(user: AuthenticatedUser, limit_count: int = 20) -> list[dict[str, Any]]:
    docs = list(repo.synced_history().where("uid", "==", user.uid).stream())
    ordered = sorted_docs(docs, "timestamp")[:limit_count]
    return [serialize((doc.to_dict() or {}).get("analysisData")) for doc in ordered]


def get_sync_stats(user: AuthenticatedUser) -> dict[str, Any]:
    cache_docs = list(repo.synced_cache().where("uid", "==", user.uid).stream())
    history_docs = list(repo.synced_history().where("uid", "==", user.uid).stream())
    feedback_docs = list(repo.analysis_feedback().where("uid", "==", user.uid).stream())
    latest_history = sorted_docs(history_docs, "timestamp")[:1]
    last_sync_time = None
    if latest_history:
        last_sync_time = serialize(latest_history[0].to_dict().get("timestamp"))

    return {
        "cacheEntries": len(cache_docs),
        "historyEntries": len(history_docs),
        "feedbackEntries": len(feedback_docs),
        "lastSyncTime": last_sync_time,
    }


def save_history_session(user: AuthenticatedUser, payload: dict[str, Any]) -> str:
    candidates = list(payload.get("candidates") or [])
    total = len(candidates)
    grades = {"A": 0, "B": 0, "C": 0}
    top_candidates: list[dict[str, Any]] = []
    scored_success = []

    for candidate in candidates:
        grade = "C"
        total_score = 0
        if candidate.get("status") != "FAILED":
            analysis = candidate.get("analysis") or {}
            grade = str(analysis.get("Hạng") or "C")
            total_score = int(analysis.get("Tổng điểm") or 0)
        if grade not in grades:
            grade = "C"
        grades[grade] += 1
        if candidate.get("status") == "SUCCESS":
            scored_success.append((total_score, candidate))

    for _, candidate in sorted(scored_success, key=lambda item: item[0], reverse=True)[:3]:
        details = (candidate.get("analysis") or {}).get("Chi tiết") or []
        jd_fit = 0
        for detail in details:
            criterion = str(detail.get("Tiêu chí") or "")
            if criterion.startswith("Phù hợp JD"):
                raw_score = str(detail.get("Điểm") or "0").split("/")[0]
                try:
                    jd_fit = int(float(raw_score))
                except Exception:
                    jd_fit = 0
                break
        top_candidates.append(
            {
                "id": candidate.get("id"),
                "name": candidate.get("candidateName"),
                "score": int((candidate.get("analysis") or {}).get("Tổng điểm") or 0),
                "jdFit": jd_fit,
                "grade": str((candidate.get("analysis") or {}).get("Hạng") or "C"),
            }
        )

    jd_text = str(payload.get("jdText") or "")
    job_position = str(payload.get("jobPosition") or "")
    location_requirement = str(payload.get("locationRequirement") or "")
    user_email = str(payload.get("userEmail") or user.email)
    weights = payload.get("weights") or {}
    hard_filters = payload.get("hardFilters") or {}

    doc_ref = repo.create_document(repo.cv_history())
    doc_ref.set(
        {
            "uid": user.uid,
            "userEmail": user_email,
            "jobPosition": job_position,
            "locationRequirement": location_requirement,
            "jdTextSnippet": jd_text[:300],
            "totalCandidates": total,
            "grades": grades,
            "topCandidates": top_candidates,
            "fullPayload": {
                "jdText": jd_text,
                "jobPosition": job_position,
                "weights": weights,
                "hardFilters": hard_filters,
                "candidates": candidates,
            },
            "createdAt": repo.server_timestamp(),
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
    )
    return doc_ref.id


def fetch_recent_history(user: AuthenticatedUser, limit_count: int = 20, user_email: str | None = None) -> list[dict[str, Any]]:
    docs = list(repo.cv_history().where("uid", "==", user.uid).stream())
    synced_docs = list(repo.synced_history().where("uid", "==", user.uid).stream())
    ordered = [
        ("cv", doc)
        for doc in sorted_docs(docs, "timestamp")
    ] + [
        ("sync", doc)
        for doc in sorted_docs(synced_docs, "timestamp")
    ]
    ordered.sort(key=lambda item: to_millis((item[1].to_dict() or {}).get("timestamp")), reverse=True)
    items = []
    for source, doc in ordered:
        data = doc.to_dict() or {}
        if "fullPayload" not in data and "jobPosition" not in data and "analysisData" not in data:
            continue
        if user_email and data.get("userEmail") not in {user_email, user.email} and data.get("email") not in {user_email, user.email}:
            continue
        items.append({"id": doc.id, "source": source, **serialize(data)})
        if len(items) >= limit_count:
            break
    return items


def save_manual_history_snapshot(user: AuthenticatedUser, payload: dict[str, Any]) -> str:
    jd_text = str(payload.get("jdText") or "")
    job_position = str(payload.get("jobPosition") or "")
    location_requirement = str(payload.get("locationRequirement") or "")
    candidates = list(payload.get("candidates") or [])
    user_email = str(payload.get("userEmail") or user.email)
    weights = payload.get("weights") or {}
    hard_filters = payload.get("hardFilters") or {}
    grades = {"A": 0, "B": 0, "C": 0}
    cv_list = []

    for candidate in candidates:
        grade = "C"
        if candidate.get("status") != "FAILED":
            grade = str((candidate.get("analysis") or {}).get("Hạng") or "C")
        if grade not in grades:
            grade = "C"
        grades[grade] += 1
        jd_fit = 0
        if candidate.get("status") != "FAILED":
            for detail in ((candidate.get("analysis") or {}).get("Chi tiết") or []):
                if str(detail.get("Tiêu chí") or "").startswith("Phù hợp JD"):
                    raw_score = str(detail.get("Điểm") or "0").split("/")[0]
                    try:
                        jd_fit = int(float(raw_score))
                    except Exception:
                        jd_fit = 0
                    break
        cv_list.append(
            {
                "id": candidate.get("id"),
                "name": candidate.get("candidateName"),
                "fileName": candidate.get("fileName"),
                "grade": grade,
                "totalScore": int((candidate.get("analysis") or {}).get("Tổng điểm") or 0),
                "jdFit": jd_fit,
            }
        )

    doc_id = f"manual-{user.uid}"
    repo.manual_history().document(doc_id).set(
        {
            "uid": user.uid,
            "email": user_email,
            "JD mẫu": jd_text,
            "Vị trí Lọc JD": job_position,
            "Yêu cầu địa điểm": location_requirement,
            "Thời gian lưu": datetime.now(timezone.utc).isoformat(),
            "Danh sách CV": cv_list,
            "Thống kê": grades,
            "weights": weights,
            "hardFilters": hard_filters,
            "updatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        merge=True,
    )
    return doc_id


def fetch_manual_history(user: AuthenticatedUser, user_email: str | None = None) -> list[dict[str, Any]]:
    docs = list(repo.manual_history().where("uid", "==", user.uid).stream())
    items = []
    for doc in docs:
        data = doc.to_dict() or {}
        if user_email and data.get("email") not in {user_email, user.email}:
            continue
        cv_list = list(data.get("Danh sách CV") or [])
        items.append(
            {
                "id": doc.id,
                "timestamp": int(data.get("updatedAt") or 0),
                "jobPosition": str(data.get("Vị trí Lọc JD") or ""),
                "locationRequirement": str(data.get("Yêu cầu địa điểm") or ""),
                "jdTextSnippet": str(data.get("JD mẫu") or "")[:300],
                "totalCandidates": len(cv_list),
                "grades": serialize(data.get("Thống kê") or {"A": 0, "B": 0, "C": 0}),
                "topCandidates": cv_list[:3],
                "userEmail": str(data.get("email") or ""),
            }
        )
    return sorted(items, key=lambda item: item["timestamp"], reverse=True)
