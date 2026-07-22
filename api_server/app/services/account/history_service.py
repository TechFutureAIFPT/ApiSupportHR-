from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
import unicodedata

from app.repositories.postgres import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import response_cache_service, view_sync_service
from app.services.account.shared import fast_cleanup, optimized_docs, serialize, sorted_docs, to_millis
from app.utils.text_normalization import normalize_display_text


MAX_HISTORY_ENTRIES_PER_USER = 100
MOBILE_JD_SNIPPET_LENGTH = 800
MOBILE_TEXT_FIELD_LENGTH = 420


def cleanup_synced_history(user: AuthenticatedUser, keep_count: int = MAX_HISTORY_ENTRIES_PER_USER) -> None:
    fast_cleanup(repo.synced_history(), user.uid, keep_count)


def _normalize_user_email(user: AuthenticatedUser, user_email: str | None = None) -> str:
    normalized = (user_email or user.email or "").strip().lower()
    return normalized or "self"


def mobile_inbox_view_doc_id(user: AuthenticatedUser, user_email: str | None = None) -> str:
    email_key = _normalize_user_email(user, user_email)
    return f"{user.uid}__{email_key}"


def sync_history_entry(user: AuthenticatedUser, analysis_data: dict[str, Any]) -> str:
    candidates = list(analysis_data.get("candidates") or [])
    screening_index = _build_history_screening_index([candidate for candidate in candidates if isinstance(candidate, dict)])
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
            **screening_index,
        }
    )
    cleanup_synced_history(user, MAX_HISTORY_ENTRIES_PER_USER)
    view_sync_service.refresh_user_views(user, "history", rebuild_mobile_inbox=True)
    return doc_ref.id


def get_synced_history(user: AuthenticatedUser, limit_count: int = 20) -> list[dict[str, Any]]:
    docs = optimized_docs(repo.synced_history(), user.uid, limit_count)
    return [serialize((doc.to_dict() or {}).get("analysisData")) for doc in docs]


def get_sync_stats(user: AuthenticatedUser) -> dict[str, Any]:
    try:
        return repo.get_sync_stats(user.uid)
    except Exception:
        cache_count = repo.synced_cache().where("uid", "==", user.uid).count().get()[0][0].value
        history_count = repo.synced_history().where("uid", "==", user.uid).count().get()[0][0].value
        feedback_count = repo.analysis_feedback().where("uid", "==", user.uid).count().get()[0][0].value
        last_docs = optimized_docs(repo.synced_history(), user.uid, 1)
        last_sync_time = serialize(last_docs[0].to_dict().get("timestamp")) if last_docs else None
        return {
            "cacheEntries": int(cache_count),
            "historyEntries": int(history_count),
            "feedbackEntries": int(feedback_count),
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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _candidate_decision_status(candidate: dict[str, Any]) -> str:
    stage_decision = _as_dict(candidate.get("stageDecision"))
    status = str(stage_decision.get("status") or "").strip()
    if status:
        return status

    summary = _as_dict(candidate.get("screeningSummary"))
    has_mandatory_review = False
    for factor in summary.values():
        if not isinstance(factor, dict):
            continue
        if factor.get("mandatory") and factor.get("status") == "fail":
            return "hold"
        if factor.get("mandatory") and factor.get("status") == "review":
            has_mandatory_review = True
    if has_mandatory_review:
        return "review"
    return "unknown"


def _candidate_screening_outcome(candidate: dict[str, Any]) -> dict[str, str]:
    status = _candidate_decision_status(candidate)
    labels = {
        "hold": "Loại tự động",
        "review": "Cần HR rà soát",
        "ready_to_advance": "Đạt tự động",
        "not_ready": "Chưa sẵn sàng",
        "unknown": "Chưa kết luận",
    }
    return {"status": status, "label": labels.get(status, status or "Chưa kết luận")}


def _compact_screening_summary(value: Any) -> dict[str, Any]:
    summary = _as_dict(value)
    compacted: dict[str, Any] = {}
    for key in ("age", "education", "major", "knowledge", "experience", "location"):
        factor = _as_dict(summary.get(key))
        if not factor:
            continue
        compacted[key] = {
            "status": str(factor.get("status") or "na"),
            "mandatory": bool(factor.get("mandatory")),
            "expected": factor.get("expected"),
            "observed": factor.get("observed"),
            "reason": str(factor.get("reason") or "")[:MOBILE_TEXT_FIELD_LENGTH],
            "evidence": str(factor.get("evidence") or "")[:MOBILE_TEXT_FIELD_LENGTH],
        }
    return compacted


def _compact_candidate_profile(value: Any) -> dict[str, Any]:
    profile = _as_dict(value)
    if not profile:
        return {}
    return {
        "birthYear": profile.get("birthYear"),
        "age": profile.get("age"),
        "currentLocation": profile.get("currentLocation"),
        "educationLevel": profile.get("educationLevel"),
        "educationMajors": _as_list(profile.get("educationMajors"))[:8],
        "inferredKnowledgeAreas": _as_list(profile.get("inferredKnowledgeAreas"))[:8],
        "totalExperienceMonths": profile.get("totalExperienceMonths"),
        "relevantExperienceMonths": profile.get("relevantExperienceMonths"),
        "experienceDomains": _as_list(profile.get("experienceDomains"))[:8],
        "extractionWarnings": [str(item)[:MOBILE_TEXT_FIELD_LENGTH] for item in _as_list(profile.get("extractionWarnings"))[:5]],
    }


def _compact_hr_summary(value: Any) -> dict[str, Any]:
    summary = _as_dict(value)
    if not summary:
        return {}
    experience = _as_dict(summary.get("kinh_nghiem"))
    skills = [
        {
            "ten_ky_nang": str(item.get("ten_ky_nang") or "")[:120],
            "muc_do_dap_ung": str(item.get("muc_do_dap_ung") or "")[:80],
            "bang_chung_tu_cv": str(item.get("bang_chung_tu_cv") or "")[:MOBILE_TEXT_FIELD_LENGTH],
        }
        for item in _as_list(summary.get("danh_gia_ky_nang"))[:6]
        if isinstance(item, dict)
    ]
    return {
        "tong_diem_phu_hop": int(_score_number(summary.get("tong_diem_phu_hop"))),
        "nhan_xet_tong_quan": str(summary.get("nhan_xet_tong_quan") or "")[:MOBILE_TEXT_FIELD_LENGTH],
        "canh_bao_red_flag": [str(item)[:MOBILE_TEXT_FIELD_LENGTH] for item in _as_list(summary.get("canh_bao_red_flag"))[:5]],
        "kinh_nghiem": {
            "so_nam_yeu_cau": str(experience.get("so_nam_yeu_cau") or "")[:120],
            "so_nam_thuc_te": str(experience.get("so_nam_thuc_te") or "")[:120],
            "ket_luan": str(experience.get("ket_luan") or "")[:80],
        },
        "danh_gia_ky_nang": skills,
    }


def _build_history_screening_index(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    by_decision = {"ready_to_advance": 0, "review": 0, "hold": 0, "not_ready": 0, "unknown": 0}
    fail_factors = {key: 0 for key in ("age", "education", "major", "knowledge", "experience", "location")}
    top_hr_summaries: list[dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("status") == "FAILED":
            continue
        status = _candidate_decision_status(candidate)
        if status not in by_decision:
            status = "unknown"
        by_decision[status] += 1

        for key, factor in _as_dict(candidate.get("screeningSummary")).items():
            if key in fail_factors and isinstance(factor, dict) and factor.get("status") == "fail":
                fail_factors[key] += 1

        hr_summary = _compact_hr_summary(candidate.get("hrSummary"))
        if hr_summary:
            top_hr_summaries.append(
                {
                    "candidateName": candidate.get("candidateName") or candidate.get("name") or "",
                    "fileName": candidate.get("fileName") or "",
                    "score": hr_summary.get("tong_diem_phu_hop") or 0,
                    "nhan_xet_tong_quan": hr_summary.get("nhan_xet_tong_quan") or "",
                    "canh_bao_red_flag": hr_summary.get("canh_bao_red_flag") or [],
                    "screeningOutcome": _candidate_screening_outcome(candidate),
                }
            )

    top_hr_summaries.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return {
        "screeningStats": {
            "totalCandidates": sum(by_decision.values()),
            "byDecision": by_decision,
            "failFactors": fail_factors,
        },
        "autoRejectCount": by_decision["hold"],
        "reviewCount": by_decision["review"],
        "readyCount": by_decision["ready_to_advance"],
        "topHrSummaries": top_hr_summaries[:3],
    }


def _compact_raw_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}
    hr_summary = _compact_hr_summary(candidate.get("hrSummary"))
    screening_summary = _compact_screening_summary(candidate.get("screeningSummary"))
    candidate_profile = _compact_candidate_profile(candidate.get("candidateProfile"))
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
        "stageDecision": candidate.get("stageDecision") if isinstance(candidate.get("stageDecision"), dict) else None,
        "screeningOutcome": _candidate_screening_outcome(candidate),
        "autoRejectReasons": [str(item)[:MOBILE_TEXT_FIELD_LENGTH] for item in _as_list(candidate.get("autoRejectReasons"))[:5]],
        "screeningSummary": screening_summary,
        "candidateProfile": candidate_profile,
        "hrSummary": hr_summary,
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
    screening_summary = _compact_screening_summary(candidate.get("screeningSummary"))
    hr_summary = _compact_hr_summary(candidate.get("hrSummary"))

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
            for item in _as_list(candidate.get("softFilterWarnings"))
            if str(item).strip()
        ],
        "hardFilterFailureReason": candidate.get("hardFilterFailureReason"),
        "stageDecision": candidate.get("stageDecision") if isinstance(candidate.get("stageDecision"), dict) else None,
        "screeningOutcome": _candidate_screening_outcome(candidate),
        "autoRejectReasons": [str(item)[:MOBILE_TEXT_FIELD_LENGTH] for item in _as_list(candidate.get("autoRejectReasons"))[:5]],
        "screeningSummary": screening_summary,
        "candidateProfile": _compact_candidate_profile(candidate.get("candidateProfile")),
        "hrSummary": hr_summary,
        "hardFilters": hard_filters,
        "jdText": str(full_payload.get("jdText") or entry.get("jdTextSnippet") or "")[:MOBILE_JD_SNIPPET_LENGTH],
        "jobPosition": str(full_payload.get("jobPosition") or entry.get("jobPosition") or candidate.get("jobTitle") or ""),
        "raw": raw,
    }


def _compact_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    full_payload = entry.get("fullPayload") if isinstance(entry.get("fullPayload"), dict) else {}
    extracted_candidates = _extract_candidates(entry)
    compact_candidates = [_compact_raw_candidate(candidate) for candidate in extracted_candidates[:6]]
    index = _build_history_screening_index(extracted_candidates)
    return {
        "id": str(entry.get("id") or ""),
        "timestamp": to_millis(entry.get("timestamp")) or int(_score_number(entry.get("timestamp"))),
        "jobPosition": str(entry.get("jobPosition") or full_payload.get("jobPosition") or ""),
        "locationRequirement": str(entry.get("locationRequirement") or ""),
        "totalCandidates": int(_score_number(entry.get("totalCandidates"), len(compact_candidates))),
        "userEmail": str(entry.get("userEmail") or entry.get("email") or ""),
        "screeningStats": entry.get("screeningStats") if isinstance(entry.get("screeningStats"), dict) else index["screeningStats"],
        "autoRejectCount": int(_score_number(entry.get("autoRejectCount"), index["autoRejectCount"])),
        "reviewCount": int(_score_number(entry.get("reviewCount"), index["reviewCount"])),
        "readyCount": int(_score_number(entry.get("readyCount"), index["readyCount"])),
        "topHrSummaries": entry.get("topHrSummaries") if isinstance(entry.get("topHrSummaries"), list) else index["topHrSummaries"],
        "fullPayload": {
            "jdText": str(full_payload.get("jdText") or entry.get("jdTextSnippet") or "")[:MOBILE_JD_SNIPPET_LENGTH],
            "jobPosition": str(full_payload.get("jobPosition") or entry.get("jobPosition") or ""),
            "hardFilters": full_payload.get("hardFilters") if isinstance(full_payload.get("hardFilters"), dict) else {},
            "candidates": compact_candidates,
        },
        "topCandidates": entry.get("topCandidates") if isinstance(entry.get("topCandidates"), list) else [],
    }


def _optimized_history_docs(collection_ref: Any, user: AuthenticatedUser, limit_count: int):
    return optimized_docs(collection_ref, user.uid, limit_count)


def _build_mobile_inbox_payload(
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

    payload = {
        "candidates": candidates,
        "history": history,
        "stats": {
            "candidateCount": len(candidates),
            "historyCount": len(history),
            "latestTimestamp": history[0]["timestamp"] if history else None,
        },
        "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    payload["revision"] = response_cache_service.build_revision("mobile_inbox", payload)
    return payload


def build_mobile_inbox_view_document(user: AuthenticatedUser, user_email: str | None = None) -> dict[str, Any]:
    # candidate_limit=160 khớp mức tối đa FE thực sự yêu cầu (CVScreenerWelcome/FilteredCvLibraryPage
    # dùng candidateLimit=160) — trước đây 200 vượt nhu cầu thật, tốn thêm nén Python + kích thước
    # Tránh ghi document PostgreSQL không cần thiết.
    payload = _build_mobile_inbox_payload(user, history_limit=50, candidate_limit=160, user_email=user_email)
    return {
        "uid": user.uid,
        "email": user.email,
        "emailKey": _normalize_user_email(user, user_email),
        "payload": payload,
        "revision": payload["revision"],
        "generatedAt": payload["generatedAt"],
        "updatedAt": repo.server_timestamp(),
    }


def _load_mobile_inbox_from_view(
    user: AuthenticatedUser,
    history_limit: int,
    candidate_limit: int,
    user_email: str | None = None,
) -> dict[str, Any] | None:
    try:
        snapshot = repo.mobile_inbox_views().document(mobile_inbox_view_doc_id(user, user_email)).get()
    except Exception:
        return None
    if not snapshot.exists:
        return None
    data = serialize(snapshot.to_dict() or {})
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else None
    if not payload:
        return None
    history = list(payload.get("history") or [])[:history_limit]
    candidates = list(payload.get("candidates") or [])[:candidate_limit]
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    return {
        "candidates": candidates,
        "history": history,
        "stats": {
            "candidateCount": len(candidates),
            "historyCount": len(history),
            "latestTimestamp": stats.get("latestTimestamp") if history else None,
        },
        "revision": str(payload.get("revision") or response_cache_service.build_revision("mobile_inbox", payload)),
        "generatedAt": int(payload.get("generatedAt") or int(datetime.now(timezone.utc).timestamp() * 1000)),
    }


def fetch_mobile_inbox(
    user: AuthenticatedUser,
    history_limit: int = 12,
    candidate_limit: int = 60,
    user_email: str | None = None,
) -> dict[str, Any]:
    normalized_email = _normalize_user_email(user, user_email)
    cache_key = response_cache_service.account_cache_key(
        "mobile_inbox",
        user.uid,
        str(history_limit),
        str(candidate_limit),
        normalized_email,
    )

    def build_payload() -> dict[str, Any]:
        if normalized_email == _normalize_user_email(user):
            payload = _load_mobile_inbox_from_view(user, history_limit, candidate_limit)
            if payload is not None and (payload.get("history") or payload.get("candidates")):
                return payload
            view_document = build_mobile_inbox_view_document(user)
            try:
                repo.mobile_inbox_views().document(mobile_inbox_view_doc_id(user)).set(view_document)
            except Exception:
                pass
            cached_payload = view_document["payload"]
            return {
                "candidates": list(cached_payload.get("candidates") or [])[:candidate_limit],
                "history": list(cached_payload.get("history") or [])[:history_limit],
                "stats": cached_payload.get("stats") or {},
                "revision": cached_payload.get("revision"),
                "generatedAt": cached_payload.get("generatedAt"),
            }
        return _build_mobile_inbox_payload(
            user,
            history_limit=history_limit,
            candidate_limit=candidate_limit,
            user_email=user_email,
        )

    cached = response_cache_service.get_or_build_cached_payload(cache_key, "mobile_inbox", build_payload)
    payload = cached.payload if isinstance(cached.payload, dict) else {}
    if not payload.get("history") and not payload.get("candidates"):
        fresh_payload = build_payload()
        if fresh_payload.get("history") or fresh_payload.get("candidates"):
            cached = response_cache_service.write_cached_payload(
                cache_key,
                "mobile_inbox",
                fresh_payload,
                revision=str(fresh_payload.get("revision") or ""),
            )
    return {
        **cached.payload,
        "revision": cached.revision,
        "generatedAt": cached.generated_at,
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
    screening_index = _build_history_screening_index([candidate for candidate in candidates if isinstance(candidate, dict)])

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
            **screening_index,
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
    view_sync_service.refresh_user_views(user, "history", rebuild_mobile_inbox=True)
    return doc_ref.id


def fetch_recent_history(user: AuthenticatedUser, limit_count: int = 20, user_email: str | None = None) -> list[dict[str, Any]]:
    per_collection = min(limit_count * 2, 100)
    cv_docs = optimized_docs(repo.cv_history(), user.uid, per_collection)
    sync_docs = optimized_docs(repo.synced_history(), user.uid, per_collection)
    ordered = [("cv", doc) for doc in cv_docs] + [("sync", doc) for doc in sync_docs]
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
    view_sync_service.refresh_user_views(user, "history", rebuild_mobile_inbox=True)
    return doc_id


def fetch_manual_history(
    user: AuthenticatedUser,
    user_email: str | None = None,
    limit_count: int = 20,
) -> list[dict[str, Any]]:
    docs = optimized_docs(repo.manual_history(), user.uid, limit_count, timestamp_field="updatedAt")
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
    return sorted(items, key=lambda item: item["timestamp"], reverse=True)[:limit_count]
