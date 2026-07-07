from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.schemas.account import AuthenticatedUser
from app.services import gemini_service
from app.services.account import chatbot_service


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_text(value).lower())


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


def _clip_strings(values: Any, *, limit: int = 4) -> list[str]:
    if not isinstance(values, list):
        return []

    items: list[str] = []
    for item in values:
        text = _normalize_text(item)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def _normalize_stage_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "", "label": "", "reason": "", "blockingReasons": []}

    blocking = value.get("blockingReasons")
    return {
        "status": _normalize_text(value.get("status")),
        "label": _normalize_text(value.get("label")),
        "reason": _normalize_text(value.get("reason")),
        "blockingReasons": _clip_strings(blocking, limit=4),
    }


def _normalize_candidate_brief(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    candidate_id = _normalize_text(item.get("id"))
    candidate_name = _normalize_text(item.get("candidateName"))
    if not candidate_id or not candidate_name:
        return None

    try:
        score = float(item.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0

    return {
        "id": candidate_id,
        "candidateName": candidate_name,
        "score": score,
        "rank": _normalize_text(item.get("rank")) or "C",
        "headlineVerdict": _normalize_text(item.get("headlineVerdict")),
        "topStrengths": _clip_strings(item.get("topStrengths"), limit=4),
        "topRisks": _clip_strings(item.get("topRisks"), limit=4),
        "matchedRequirements": _clip_strings(item.get("matchedRequirements"), limit=6),
        "missingRequirements": _clip_strings(item.get("missingRequirements"), limit=6),
        "redFlags": _clip_strings(item.get("redFlags"), limit=4),
        "stageDecision": _normalize_stage_decision(item.get("stageDecision")),
        "interviewQuestions": _clip_strings(item.get("interviewQuestions"), limit=4),
    }


def _dedupe_candidate_briefs(candidate_briefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in candidate_briefs:
        normalized = _normalize_candidate_brief(item)
        if normalized is None:
            continue
        deduped[normalized["id"]] = normalized
    return list(deduped.values())


def _find_focus_candidate_id(message: str, candidate_briefs: list[dict[str, Any]]) -> str | None:
    message_key = _normalize_name_key(message)
    if not message_key:
        return None

    for item in candidate_briefs:
        name_key = _normalize_name_key(item.get("candidateName"))
        if name_key and name_key in message_key:
            return str(item["id"])
    return None


def _pick_candidates(
    message: str,
    candidate_briefs: list[dict[str, Any]],
    selected_candidate_ids: list[str],
    focus_candidate_id: str | None,
) -> tuple[str | None, list[dict[str, Any]]]:
    by_id = {str(item["id"]): item for item in candidate_briefs}

    resolved_focus = focus_candidate_id if focus_candidate_id in by_id else _find_focus_candidate_id(message, candidate_briefs)
    chosen: list[dict[str, Any]] = []

    if resolved_focus and resolved_focus in by_id:
        chosen.append(by_id[resolved_focus])

    for candidate_id in selected_candidate_ids:
        item = by_id.get(candidate_id)
        if item and item not in chosen:
            chosen.append(item)

    if not chosen:
        chosen = sorted(candidate_briefs, key=lambda item: float(item.get("score") or 0), reverse=True)[:3]

    return resolved_focus, chosen[:3]


def _recommended_action(candidate: dict[str, Any]) -> str:
    stage_decision = candidate.get("stageDecision") or {}
    label = _normalize_text(stage_decision.get("label"))
    if label:
        return label

    score = float(candidate.get("score") or 0)
    if score >= 75:
        return "Ưu tiên mời phỏng vấn"
    if score >= 60:
        return "Phỏng vấn xác minh thêm"
    return "Chưa ưu tiên shortlist"


def _build_candidate_card(candidate: dict[str, Any], focus_candidate_id: str | None) -> dict[str, Any]:
    return {
        "id": candidate["id"],
        "candidateName": candidate["candidateName"],
        "score": float(candidate.get("score") or 0),
        "rank": candidate.get("rank") or "C",
        "headlineVerdict": candidate.get("headlineVerdict") or "",
        "topStrengths": _clip_strings(candidate.get("topStrengths"), limit=3),
        "topRisks": _clip_strings(candidate.get("topRisks"), limit=3),
        "matchedRequirements": _clip_strings(candidate.get("matchedRequirements"), limit=4),
        "missingRequirements": _clip_strings(candidate.get("missingRequirements"), limit=4),
        "redFlags": _clip_strings(candidate.get("redFlags"), limit=3),
        "interviewQuestions": _clip_strings(candidate.get("interviewQuestions"), limit=3),
        "recommendedAction": _recommended_action(candidate),
        "focusLabel": "Ứng viên đang đào sâu" if focus_candidate_id and candidate["id"] == focus_candidate_id else "",
        "stageDecision": _normalize_stage_decision(candidate.get("stageDecision")),
    }


def _fallback_reply(
    message: str,
    candidate_briefs: list[dict[str, Any]],
    selected_candidate_ids: list[str],
    focus_candidate_id: str | None,
) -> dict[str, Any]:
    resolved_focus, chosen = _pick_candidates(message, candidate_briefs, selected_candidate_ids, focus_candidate_id)
    cards = [_build_candidate_card(item, resolved_focus) for item in chosen]

    if cards:
        lead = cards[0]
        response_text = "\n".join(
            [
                f"- Kết luận nhanh: {lead['candidateName']} hiện là ứng viên nổi bật nhất để xem tiếp.",
                f"- Điểm mạnh chính: {', '.join(lead['topStrengths']) or 'Cần xem thêm evidence trong hồ sơ.'}",
                f"- Rủi ro cần xác minh: {', '.join(lead['topRisks']) or 'Chưa thấy red flag lớn trong snapshot hiện tại.'}",
                f"- Bước tiếp theo: {lead['recommendedAction']}.",
            ]
        )
    else:
        response_text = "- Kết luận nhanh: hiện chưa đủ snapshot ứng viên để tư vấn chính xác."

    focus_name = next((card["candidateName"] for card in cards if card["id"] == resolved_focus), cards[0]["candidateName"] if cards else "ứng viên này")
    return {
        "responseText": response_text,
        "suggestedCandidateIds": [card["id"] for card in cards],
        "focusCandidateId": resolved_focus,
        "candidateCards": cards,
        "followUpQuestions": [
            f"Bạn muốn tôi đào sâu điểm mạnh và rủi ro của {focus_name} không?",
            "Bạn muốn tôi gợi ý 3 câu hỏi phỏng vấn xác minh tiếp theo không?",
            "Bạn muốn so sánh ứng viên này với 1-2 ứng viên top còn lại không?",
        ],
        "suggestedActions": list(dict.fromkeys([card["recommendedAction"] for card in cards if card.get("recommendedAction")]))[:3],
    }


def _build_prompt(
    session_data: dict[str, Any],
    candidate_briefs: list[dict[str, Any]],
    chosen_candidates: list[dict[str, Any]],
    message: str,
    focus_candidate_id: str | None,
) -> str:
    analysis_context = session_data.get("analysisContext") if isinstance(session_data.get("analysisContext"), dict) else {}
    focus_name = next(
        (item.get("candidateName") for item in chosen_candidates if item.get("id") == focus_candidate_id),
        "",
    )
    payload = {
        "analysisContext": analysis_context,
        "focusCandidateId": focus_candidate_id,
        "focusCandidateName": focus_name,
        "selectedCandidates": chosen_candidates,
        "availableCandidates": candidate_briefs[:12],
        "recruiterQuestion": message,
    }
    return "\n".join(
        [
            "Bạn là Candidate Copilot cho SupportHR, phục vụ recruiter.",
            "Ưu tiên verdict-first: nói kết luận ngắn gọn trước, sau đó mới nêu bằng chứng.",
            "Chỉ dùng dữ liệu có trong snapshot. Không bịa kỹ năng hoặc kinh nghiệm.",
            "Nếu chưa đủ dữ liệu, nói rõ phần thiếu và đề xuất bước xác minh tiếp theo.",
            'Trả về JSON hợp lệ với đúng cấu trúc: {"responseText":"...","suggestedCandidateIds":["..."],"focusCandidateId":"...","candidateCards":[{"id":"","candidateName":"","score":0,"rank":"","headlineVerdict":"","topStrengths":[],"topRisks":[],"matchedRequirements":[],"missingRequirements":[],"redFlags":[],"interviewQuestions":[],"recommendedAction":"","focusLabel":"","stageDecision":{"status":"","label":"","reason":"","blockingReasons":[]}}],"followUpQuestions":["..."],"suggestedActions":["..."]}.',
            "responseText: tối đa 4 gạch đầu dòng, ngắn, rõ, dùng tiếng Việt.",
            "",
            json.dumps(payload, ensure_ascii=False),
        ]
    )


def _normalize_reply_payload(payload: dict[str, Any], fallback: dict[str, Any], candidate_briefs: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item["id"]): item for item in candidate_briefs}
    suggested_ids = [
        candidate_id
        for candidate_id in _clip_strings(payload.get("suggestedCandidateIds"), limit=3)
        if candidate_id in by_id
    ]
    if not suggested_ids:
        suggested_ids = list(fallback["suggestedCandidateIds"])

    focus_candidate_id = _normalize_text(payload.get("focusCandidateId")) or fallback.get("focusCandidateId")
    if focus_candidate_id and focus_candidate_id not in by_id:
        focus_candidate_id = fallback.get("focusCandidateId")

    raw_cards = payload.get("candidateCards")
    cards = []
    if isinstance(raw_cards, list):
        for item in raw_cards:
            normalized = _normalize_candidate_brief(item)
            if normalized is None:
                continue
            cards.append(_build_candidate_card(normalized, focus_candidate_id))
            if len(cards) >= 3:
                break
    if not cards:
        cards = list(fallback["candidateCards"])

    return {
        "responseText": _normalize_text(payload.get("responseText")) or fallback["responseText"],
        "suggestedCandidateIds": suggested_ids,
        "focusCandidateId": focus_candidate_id,
        "candidateCards": cards,
        "followUpQuestions": _clip_strings(payload.get("followUpQuestions"), limit=3) or list(fallback["followUpQuestions"]),
        "suggestedActions": _clip_strings(payload.get("suggestedActions"), limit=3) or list(fallback["suggestedActions"]),
    }


def reply_to_chatbot_session(
    user: AuthenticatedUser,
    session_id: str,
    message: str,
    *,
    selected_candidate_ids: list[str] | None = None,
    focus_candidate_id: str | None = None,
    candidate_briefs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshot = chatbot_service.get_owned_chatbot_session_snapshot(user, session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy phiên chatbot.")

    session_data = snapshot.to_dict() or {}
    normalized_message = _normalize_text(message)
    if not normalized_message:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Câu hỏi chatbot không được để trống.")

    latest_candidate_briefs = _dedupe_candidate_briefs(candidate_briefs or session_data.get("candidateBriefs") or [])
    if not latest_candidate_briefs:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Phiên chatbot chưa có snapshot ứng viên để tư vấn.")

    selected_ids = [candidate_id for candidate_id in (selected_candidate_ids or []) if candidate_id]
    resolved_focus, chosen = _pick_candidates(normalized_message, latest_candidate_briefs, selected_ids, focus_candidate_id)
    fallback = _fallback_reply(normalized_message, latest_candidate_briefs, selected_ids, resolved_focus)

    prompt = _build_prompt(session_data, latest_candidate_briefs, chosen, normalized_message, resolved_focus)
    provider_payload = fallback

    try:
        response_text = gemini_service.generate_content(get_settings().gemini_default_model, prompt, {"temperature": 0.2})
        parsed_payload = _extract_json_payload(response_text)
        if parsed_payload:
            provider_payload = _normalize_reply_payload(parsed_payload, fallback, latest_candidate_briefs)
    except Exception:
        provider_payload = fallback

    now = int(time.time() * 1000)
    user_message = {
        "id": f"{now}-u",
        "author": "user",
        "content": normalized_message,
        "timestamp": now,
        "suggestedCandidateIds": selected_ids,
        "metadata": {
            "focusCandidateId": resolved_focus,
            "candidateCards": [],
            "followUpQuestions": [],
            "suggestedActions": [],
        },
    }
    assistant_message = {
        "id": f"{now + 1}-b",
        "author": "bot",
        "content": provider_payload["responseText"],
        "timestamp": now + 1,
        "suggestedCandidateIds": provider_payload["suggestedCandidateIds"],
        "metadata": {
            "focusCandidateId": provider_payload["focusCandidateId"],
            "candidateCards": provider_payload["candidateCards"],
            "followUpQuestions": provider_payload["followUpQuestions"],
            "suggestedActions": provider_payload["suggestedActions"],
        },
    }

    chatbot_service.add_chatbot_messages(user, session_id, [user_message, assistant_message])
    chatbot_service.update_chatbot_session_state(
        user,
        session_id,
        {
            "candidateBriefs": latest_candidate_briefs,
            "lastSuggestedCandidateIds": provider_payload["suggestedCandidateIds"],
            "lastFocusCandidateId": provider_payload["focusCandidateId"] or "",
            "lastMessageAt": assistant_message["timestamp"],
        },
    )

    return {
        "sessionId": session_id,
        "userMessage": user_message,
        "assistantMessage": assistant_message,
        "responseText": provider_payload["responseText"],
        "suggestedCandidateIds": provider_payload["suggestedCandidateIds"],
        "focusCandidateId": provider_payload["focusCandidateId"],
        "candidateCards": provider_payload["candidateCards"],
        "followUpQuestions": provider_payload["followUpQuestions"],
        "suggestedActions": provider_payload["suggestedActions"],
    }
