from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
import unicodedata

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account.shared import serialize, sorted_docs, to_millis
from app.utils.text_normalization import normalize_display_text


MAX_HISTORY_ENTRIES_PER_USER = 100
MOBILE_JD_SNIPPET_LENGTH = 800
MOBILE_TEXT_FIELD_LENGTH = 420


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


def _score_number(value: Any, fallback: float = 0) -> float:
    if isinstance(value, (int, float)):
      return float(value)
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit() or char == ".")
        try:
            return float(digits) if digits else fallback
        except ValueError:
            return fallback
    return fallback


def _first_text(record: dict[str, Any], keys: list[str], fallback: str = "") -> str:
    alias_set = {_normalize_lookup_key(key) for key in keys}
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_display_text(value.strip())
        if isinstance(value, (int, float)):
            return str(value)
    for key, value in record.items():
        if _normalize_lookup_key(str(key)) not in alias_set:
            continue
        if isinstance(value, str) and value.strip():
            return normalize_display_text(value.strip())
        if isinstance(value, (int, float)):
            return str(value)
    return fallback


def _normalize_lookup_key(value: str) -> str:
    normalized = normalize_display_text(value)
    decomposed = unicodedata.normalize("NFD", normalized)
    ascii_text = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    ascii_text = ascii_text.replace("Đ", "D").replace("đ", "d")
    return re.sub(r"\s+", " ", ascii_text.strip().lower())


def _candidate_avatar_url(candidate: dict[str, Any]) -> str:
    return _first_text(
        candidate,
        [
            "avatarUrl",
            "avatar",
            "photoUrl",
            "photoURL",
            "imageUrl",
            "imageURL",
            "profileImageUrl",
            "profilePhotoUrl",
            "picture",
        ],
    )


def _text_list(record: dict[str, Any], keys: list[str], limit: int) -> list[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, list):
            return [str(item).strip()[:MOBILE_TEXT_FIELD_LENGTH] for item in value if str(item).strip()][:limit]
    return []


def _details(record: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    raw = record.get("Chi tiết") or record.get("Chi tiet") or record.get("details") or []
    if not isinstance(raw, list):
        return []

    compacted: list[dict[str, Any]] = []
    for item in raw[:limit]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "Tiêu chí": _first_text(item, ["Tiêu chí", "Tieu chi", "criterion", "name"]),
                "Điểm": _first_text(item, ["Điểm", "Diem", "score"]),
                "Dẫn chứng": _first_text(item, ["Dẫn chứng", "evidence", "Giải thích", "explanation"])[:MOBILE_TEXT_FIELD_LENGTH],
            }
        )
    return compacted


def _compact_raw_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    return {
        "id": candidate.get("id"),
        "candidateName": candidate.get("candidateName") or candidate.get("name"),
        "avatarUrl": _candidate_avatar_url(candidate),
        "fileName": candidate.get("fileName"),
        "jobTitle": candidate.get("jobTitle"),
        "industry": candidate.get("industry"),
        "experienceLevel": candidate.get("experienceLevel"),
        "detectedLocation": candidate.get("detectedLocation"),
        "status": candidate.get("status"),
        "analysis": {
            "Tổng điểm": int(_score_number(analysis.get("Tổng điểm") or analysis.get("Tong diem") or analysis.get("score"))),
            "Hạng": _first_text(analysis, ["Hạng", "Hang", "rank"], "C"),
            "Điểm mạnh CV": _text_list(analysis, ["Điểm mạnh CV", "Diem manh CV", "strengths"], 5),
            "Điểm yếu CV": _text_list(analysis, ["Điểm yếu CV", "Diem yeu CV", "weaknesses"], 5),
            "Câu hỏi phỏng vấn": _text_list(analysis, ["Câu hỏi phỏng vấn", "Cau hoi phong van", "interview_questions"], 3),
            "Chi tiết": _details(analysis, 6),
        },
    }


def _extract_candidates(entry: dict[str, Any]) -> list[dict[str, Any]]:
    full_payload = entry.get("fullPayload") if isinstance(entry.get("fullPayload"), dict) else {}
    analysis_data = entry.get("analysisData") if isinstance(entry.get("analysisData"), dict) else {}
    candidates = full_payload.get("candidates") or entry.get("candidates") or analysis_data.get("candidates")
    if isinstance(candidates, list) and candidates:
        return [candidate for candidate in candidates if isinstance(candidate, dict)]

    top_candidates = entry.get("topCandidates")
    if isinstance(top_candidates, list):
        return [
            {
                "id": item.get("id"),
                "candidateName": item.get("name"),
                "avatarUrl": _candidate_avatar_url(item),
                "jobTitle": entry.get("jobPosition"),
                "status": "SUCCESS",
                "analysis": {
                    "Tổng điểm": item.get("score") or 0,
                    "Hạng": item.get("grade") or "C",
                    "Điểm mạnh CV": ["Có trong danh sách ứng viên nổi bật từ lịch sử web."],
                    "Điểm yếu CV": [],
                },
            }
            for item in top_candidates
            if isinstance(item, dict)
        ]
    return []


def _candidate_id(candidate: dict[str, Any], entry_id: str, index: int) -> str:
    raw_id = str(candidate.get("id") or f"{entry_id}-{index}-{candidate.get('fileName') or 'candidate'}")
    scoped = f"{entry_id or 'history'}-{index}-{raw_id}"
    return "".join(char if char.isalnum() or char in "_-" else "-" for char in scoped).replace("--", "-")


def _compact_candidate_view(candidate: dict[str, Any], entry: dict[str, Any], index: int) -> dict[str, Any] | None:
    if candidate.get("status") and candidate.get("status") != "SUCCESS":
        return None

    entry_id = str(entry.get("id") or "")
    full_payload = entry.get("fullPayload") if isinstance(entry.get("fullPayload"), dict) else {}
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    hard_filters = full_payload.get("hardFilters") if isinstance(full_payload.get("hardFilters"), dict) else {}
    score = int(_score_number(analysis.get("Tổng điểm") or analysis.get("Tong diem") or analysis.get("score") or candidate.get("totalScore")))
    rank = _first_text(analysis, ["Hạng", "Hang", "rank"], str(candidate.get("grade") or "C")).upper() or "C"
    candidate_name = str(candidate.get("candidateName") or candidate.get("name") or "Ứng viên chưa xác định")
    raw = _compact_raw_candidate(candidate)

    return {
        "id": _candidate_id(candidate, entry_id, index),
        "sourceHistoryId": entry_id,
        "syncHistoryId": str(entry.get("syncHistoryId") or ""),
        "sessionId": str(entry.get("sessionId") or full_payload.get("sessionId") or ""),
        "candidateName": candidate_name,
        "avatarUrl": _candidate_avatar_url(candidate),
        "fileName": str(candidate.get("fileName") or "Không rõ file"),
        "jobTitle": str(candidate.get("jobTitle") or entry.get("jobPosition") or full_payload.get("jobPosition") or "Vị trí chưa rõ"),
        "industry": str(candidate.get("industry") or "Chưa rõ ngành"),
        "experienceLevel": str(candidate.get("experienceLevel") or "Chưa rõ level"),
        "detectedLocation": str(candidate.get("detectedLocation") or entry.get("locationRequirement") or ""),
        "score": score,
        "rank": rank,
        "strengths": _text_list(analysis, ["Điểm mạnh CV", "Diem manh CV", "strengths"], 5),
        "weaknesses": _text_list(analysis, ["Điểm yếu CV", "Diem yeu CV", "weaknesses"], 5),
        "interviewQuestions": _text_list(analysis, ["Câu hỏi phỏng vấn", "Cau hoi phong van", "interview_questions"], 3),
        "details": _details(analysis, 6),
        "warnings": [
            str(item)[:MOBILE_TEXT_FIELD_LENGTH]
            for item in list(candidate.get("softFilterWarnings") or [])
            if str(item).strip()
        ],
        "hardFilterFailureReason": candidate.get("hardFilterFailureReason"),
        "hardFilters": hard_filters,
        "jdText": str(full_payload.get("jdText") or entry.get("jdTextSnippet") or "")[:MOBILE_JD_SNIPPET_LENGTH],
        "jobPosition": str(full_payload.get("jobPosition") or entry.get("jobPosition") or candidate.get("jobTitle") or ""),
        "raw": raw,
    }


def _compact_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    full_payload = entry.get("fullPayload") if isinstance(entry.get("fullPayload"), dict) else {}
    compact_candidates = [_compact_raw_candidate(candidate) for candidate in _extract_candidates(entry)[:6]]
    return {
        "id": str(entry.get("id") or ""),
        "timestamp": to_millis(entry.get("timestamp")) or int(_score_number(entry.get("timestamp"))),
        "jobPosition": str(entry.get("jobPosition") or full_payload.get("jobPosition") or ""),
        "locationRequirement": str(entry.get("locationRequirement") or ""),
        "totalCandidates": int(_score_number(entry.get("totalCandidates"), len(compact_candidates))),
        "userEmail": str(entry.get("userEmail") or entry.get("email") or ""),
        "fullPayload": {
            "jdText": str(full_payload.get("jdText") or entry.get("jdTextSnippet") or "")[:MOBILE_JD_SNIPPET_LENGTH],
            "jobPosition": str(full_payload.get("jobPosition") or entry.get("jobPosition") or ""),
            "hardFilters": full_payload.get("hardFilters") if isinstance(full_payload.get("hardFilters"), dict) else {},
            "candidates": compact_candidates,
        },
        "topCandidates": entry.get("topCandidates") if isinstance(entry.get("topCandidates"), list) else [],
    }


def _optimized_history_docs(collection_ref: Any, user: AuthenticatedUser, limit_count: int):
    try:
        return list(
            collection_ref.where("uid", "==", user.uid)
            .order_by("timestamp", direction="DESCENDING")
            .limit(limit_count)
            .stream()
        )
    except Exception:
        return sorted_docs(list(collection_ref.where("uid", "==", user.uid).stream()), "timestamp")[:limit_count]


def fetch_mobile_inbox(
    user: AuthenticatedUser,
    history_limit: int = 12,
    candidate_limit: int = 60,
    user_email: str | None = None,
) -> dict[str, Any]:
    cv_docs = _optimized_history_docs(repo.cv_history(), user, history_limit)
    sync_docs = _optimized_history_docs(repo.synced_history(), user, history_limit)
    entries: list[dict[str, Any]] = []

    for source, docs in (("cv", cv_docs), ("sync", sync_docs)):
        for doc in docs:
            data = doc.to_dict() or {}
            if user_email and data.get("userEmail") not in {user_email, user.email} and data.get("email") not in {user_email, user.email}:
                continue
            entries.append({"id": doc.id, "source": source, **serialize(data)})

    entries.sort(key=lambda item: to_millis(item.get("timestamp")), reverse=True)
    entries = entries[:history_limit]

    history = [_compact_history_entry(entry) for entry in entries]
    candidates = [
        candidate
        for entry in entries
        for index, raw_candidate in enumerate(_extract_candidates(entry))
        for candidate in [_compact_candidate_view(raw_candidate, entry, index)]
        if candidate is not None
    ]
    candidates.sort(key=lambda item: item.get("score") or 0, reverse=True)
    candidates = candidates[:candidate_limit]

    return {
        "candidates": candidates,
        "history": history,
        "stats": {
            "candidateCount": len(candidates),
            "historyCount": len(history),
            "latestTimestamp": history[0]["timestamp"] if history else None,
        },
        "revision": f"mobile-inbox-v1:{history[0]['timestamp'] if history else 0}:{len(candidates)}",
        "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
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
                "avatarUrl": _candidate_avatar_url(candidate),
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
                "avatarUrl": _candidate_avatar_url(candidate),
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
