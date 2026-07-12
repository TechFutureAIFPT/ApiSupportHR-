from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import get_settings
from app.prompts import render_prompt
from app.services.gemini_service import generate_content


_VALID_CONFIDENCE = {"high", "medium", "low"}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    cleaned = _normalize_text(text)
    if not cleaned:
        return None

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _fallback_reply(candidate_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Trả lời khung dựng từ chính snapshot, không gọi LLM — dùng khi Gemini lỗi/parse lỗi."""
    candidate = candidate_snapshot.get("candidate") if isinstance(candidate_snapshot.get("candidate"), dict) else {}
    name = _normalize_text(candidate.get("name")) or "Ứng viên"
    score = candidate.get("totalScore")
    grade = candidate.get("grade")
    stage_label = _normalize_text((candidate.get("stageDecision") or {}).get("label"))

    warnings = candidate_snapshot.get("warnings") if isinstance(candidate_snapshot.get("warnings"), dict) else {}
    red_flags = warnings.get("redFlags") if isinstance(warnings.get("redFlags"), list) else []

    criteria = candidate_snapshot.get("criteria") if isinstance(candidate_snapshot.get("criteria"), dict) else {}
    weak = criteria.get("weak") if isinstance(criteria.get("weak"), list) else []

    lines = [
        f"Kết luận nhanh: {name} hiện đạt {score if score is not None else '--'}/100 điểm, hạng {grade or '--'}.",
    ]
    if stage_label:
        lines.append(f"Trạng thái xử lý hiện tại: {stage_label}.")
    if red_flags:
        lines.append(f"Rủi ro cần xác minh: {', '.join(str(item) for item in red_flags[:3])}.")
    else:
        weak_names = [
            str(item.get("criterion")) for item in weak[:3] if isinstance(item, dict) and item.get("criterion")
        ]
        if weak_names:
            lines.append(f"Tiêu chí cần xác minh thêm: {', '.join(weak_names)}.")
    lines.append(
        "Hệ thống AI tạm thời không phản hồi được — đây là tóm tắt dựng từ dữ liệu đã phân tích sẵn, "
        "khuyến nghị hỏi lại sau ít phút."
    )

    return {
        "responseText": "\n".join(lines),
        "citedCriteria": [],
        "confidence": "low",
    }


def _build_prompt(
    candidate_snapshot: dict[str, Any],
    message: str,
    job_position: str,
    recruiter_context: str | None,
) -> str:
    return render_prompt(
        "chatbot/candidate_focus",
        context={
            "job_position": job_position or "Không nêu rõ",
            "recruiter_context": recruiter_context or "Không có bối cảnh bổ sung.",
            "candidate_snapshot_json": json.dumps(candidate_snapshot, ensure_ascii=False),
            "message": message,
        },
    )


def _normalize_reply_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    response_text = _normalize_text(payload.get("responseText")) or fallback["responseText"]

    raw_cited = payload.get("citedCriteria")
    cited = (
        [str(item).strip() for item in raw_cited if str(item).strip()]
        if isinstance(raw_cited, list)
        else []
    )

    confidence = str(payload.get("confidence") or "").strip().lower()
    if confidence not in _VALID_CONFIDENCE:
        confidence = fallback["confidence"]

    return {
        "responseText": response_text,
        "citedCriteria": cited[:5],
        "confidence": confidence,
    }


def reply_to_candidate_chat(
    candidate_snapshot: dict[str, Any],
    message: str,
    *,
    job_position: str = "",
    recruiter_context: str | None = None,
) -> dict[str, Any]:
    normalized_message = _normalize_text(message)
    fallback = _fallback_reply(candidate_snapshot)
    if not normalized_message:
        return fallback

    prompt = _build_prompt(candidate_snapshot, normalized_message, job_position, recruiter_context)

    try:
        response_text = generate_content(
            get_settings().gemini_default_model,
            prompt,
            {"temperature": 0.25, "responseMimeType": "application/json"},
        )
        parsed = _extract_json_payload(response_text)
        if parsed:
            return _normalize_reply_payload(parsed, fallback)
    except Exception:
        pass

    return fallback
