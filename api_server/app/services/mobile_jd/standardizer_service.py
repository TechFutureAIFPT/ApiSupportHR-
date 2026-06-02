from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.prompts import render_prompt
from app.schemas.mobile_jd import TargetPlatform
from app.services.gemini_service import generate_content
from app.services.mobile_jd.platform_links import get_platform_info


MAX_JD_LENGTH = 12000

SECTION_RULES = [
    ("title", "Chức danh", ("chuc danh", "vi tri", "tuyen dung", "job title"), "high"),
    ("overview", "Tổng quan công việc", ("muc dich", "tong quan", "gioi thieu", "about role"), "medium"),
    ("responsibilities", "Mô tả công việc", ("mo ta", "nhiem vu", "trach nhiem", "responsibilities"), "high"),
    ("requirements", "Yêu cầu công việc", ("yeu cau", "kinh nghiem", "ky nang", "requirements"), "high"),
    ("benefits", "Quyền lợi", ("quyen loi", "phuc loi", "benefit", "dai ngo"), "medium"),
    ("salary", "Mức lương", ("luong", "thu nhap", "salary"), "high"),
    ("location", "Địa điểm làm việc", ("dia diem", "location", "remote", "hybrid", "onsite"), "medium"),
    ("workingTime", "Thời gian làm việc", ("thoi gian", "working time", "full time", "part time"), "low"),
    ("applicationInfo", "Cách ứng tuyển", ("ung tuyen", "gui cv", "email", "apply"), "medium"),
]

PLATFORM_GUIDANCE = {
    "generic": "Dùng bố cục phổ thông, rõ ràng: Chức danh, Tổng quan, Mô tả, Yêu cầu, Quyền lợi, Địa điểm, Lương, Cách ứng tuyển.",
    "parse_jd": "Tối ưu để đưa sang công cụ chỉnh JD: giữ cấu trúc rõ, tách bullet ngắn, không thêm thông tin chưa có.",
    "topcv": "Tối ưu cho bài đăng TopCV: tiêu đề rõ, quyền lợi nổi bật, yêu cầu cụ thể, từ khóa ngành nghề dễ tìm kiếm.",
    "vietnamworks": "Tối ưu cho VietnamWorks: nhấn mạnh phạm vi công việc, yêu cầu kinh nghiệm, phúc lợi và môi trường làm việc.",
    "linkedin": "Tối ưu cho LinkedIn Jobs: ngôn ngữ chuyên nghiệp, có overview ngắn, responsibilities và qualifications rõ ràng.",
}


def _normalize_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    cleaned = cleaned.replace(",}", "}").replace(",]", "]")
    data = json.loads(cleaned)
    return data if isinstance(data, dict) else {}


def _as_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    if isinstance(value, str) and value.strip():
        return [line.strip("-• \t") for line in value.splitlines() if line.strip()][:limit]
    return []


def _as_text(value: Any, max_length: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length]


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip(" -•\t")
        if 4 <= len(cleaned) <= 90:
            return cleaned
    return "Vị trí tuyển dụng"


def _detect_missing_sections(jd_text: str) -> list[dict[str, str]]:
    normalized = _normalize_ascii(jd_text)
    missing: list[dict[str, str]] = []
    for key, label, tokens, priority in SECTION_RULES:
        if not any(token in normalized for token in tokens):
            missing.append(
                {
                    "key": key,
                    "label": label,
                    "reason": f"JD chưa thể hiện rõ phần {label.lower()}.",
                    "priority": priority,
                }
            )
    return missing


def _fallback_keywords(text: str) -> list[str]:
    normalized_words = re.findall(r"[A-Za-zÀ-ỹ0-9+#.]{3,}", text)
    stop_words = {
        "công",
        "việc",
        "ứng",
        "viên",
        "kinh",
        "nghiệm",
        "yêu",
        "cầu",
        "mô",
        "tả",
        "làm",
        "với",
        "cho",
        "the",
        "and",
        "you",
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for word in normalized_words:
        key = _normalize_ascii(word)
        if key in stop_words or key in seen:
            continue
        seen.add(key)
        keywords.append(word)
        if len(keywords) >= 10:
            break
    return keywords


def _build_fallback(jd_text: str, target_platform: TargetPlatform) -> dict[str, Any]:
    missing = _detect_missing_sections(jd_text)
    score = max(45, 100 - len(missing) * 7)
    lines = [line.strip(" -•\t") for line in jd_text.splitlines() if line.strip()]
    body_lines = lines[1:] if len(lines) > 1 else lines
    requirements = [line for line in body_lines if re.search(r"kinh nghiệm|kỹ năng|yêu cầu|thành thạo|biết", line, re.I)]
    responsibilities = [line for line in body_lines if line not in requirements][:6]
    weak_points = []
    if len(jd_text) < 500:
        weak_points.append(
            {
                "label": "Nội dung JD còn ngắn",
                "detail": "JD nên mô tả rõ nhiệm vụ, yêu cầu bắt buộc, quyền lợi và thông tin ứng tuyển.",
            }
        )
    if missing:
        weak_points.append(
            {
                "label": "Thiếu cấu trúc đăng tuyển",
                "detail": "Một số phần quan trọng chưa rõ nên ứng viên khó đánh giá mức độ phù hợp.",
            }
        )

    suggestions = [
        {
            "label": item["label"],
            "detail": f"Bổ sung phần {item['label'].lower()} bằng thông tin cụ thể, tránh viết chung chung.",
        }
        for item in missing[:6]
    ]
    if not suggestions:
        suggestions.append(
            {
                "label": "Tối ưu từ khóa",
                "detail": "Giữ các từ khóa kỹ năng, ngành nghề và cấp bậc để bài đăng dễ được tìm thấy hơn.",
            }
        )

    return {
        "score": score,
        "missingSections": missing,
        "weakPoints": weak_points,
        "suggestions": suggestions,
        "normalizedJD": {
            "title": _first_non_empty_line(jd_text),
            "overview": " ".join(body_lines[:2])[:450],
            "responsibilities": responsibilities[:6] or body_lines[:6],
            "requirements": requirements[:6],
            "benefits": [],
            "workingTime": "",
            "location": "",
            "salary": "",
            "applicationInfo": "",
            "keywords": _fallback_keywords(jd_text),
        },
        "source": "fallback",
    }


def _normalize_ai_payload(payload: dict[str, Any], jd_text: str) -> dict[str, Any]:
    fallback = _build_fallback(jd_text, "generic")
    normalized_jd = payload.get("normalizedJD") if isinstance(payload.get("normalizedJD"), dict) else {}
    score = payload.get("score")
    try:
        score_number = int(float(score))
    except (TypeError, ValueError):
        score_number = int(fallback["score"])

    return {
        "score": min(100, max(0, score_number)),
        "missingSections": [
            {
                "key": _as_text(item.get("key"), 80) or f"section-{index}",
                "label": _as_text(item.get("label"), 120),
                "reason": _as_text(item.get("reason"), 300),
                "priority": item.get("priority") if item.get("priority") in {"high", "medium", "low"} else "medium",
            }
            for index, item in enumerate(payload.get("missingSections") or [], start=1)
            if isinstance(item, dict)
        ][:10]
        or fallback["missingSections"],
        "weakPoints": [
            {"label": _as_text(item.get("label"), 120), "detail": _as_text(item.get("detail"), 360)}
            for item in payload.get("weakPoints") or []
            if isinstance(item, dict)
        ][:8]
        or fallback["weakPoints"],
        "suggestions": [
            {"label": _as_text(item.get("label"), 120), "detail": _as_text(item.get("detail"), 420)}
            for item in payload.get("suggestions") or []
            if isinstance(item, dict)
        ][:8]
        or fallback["suggestions"],
        "normalizedJD": {
            "title": _as_text(normalized_jd.get("title"), 160) or fallback["normalizedJD"]["title"],
            "overview": _as_text(normalized_jd.get("overview"), 700),
            "responsibilities": _as_list(normalized_jd.get("responsibilities"), 10),
            "requirements": _as_list(normalized_jd.get("requirements"), 10),
            "benefits": _as_list(normalized_jd.get("benefits"), 8),
            "workingTime": _as_text(normalized_jd.get("workingTime"), 180),
            "location": _as_text(normalized_jd.get("location"), 180),
            "salary": _as_text(normalized_jd.get("salary"), 180),
            "applicationInfo": _as_text(normalized_jd.get("applicationInfo"), 260),
            "keywords": _as_list(normalized_jd.get("keywords"), 12) or fallback["normalizedJD"]["keywords"],
        },
        "source": "ai",
    }


def standardize_jd_text(jd_text: str, target_platform: TargetPlatform = "generic") -> dict[str, Any]:
    cleaned_jd = re.sub(r"\r\n?", "\n", jd_text or "").strip()
    if not cleaned_jd:
        raise ValueError("JD không được để trống.")
    cleaned_jd = cleaned_jd[:MAX_JD_LENGTH]
    platform = get_platform_info(target_platform)

    try:
        prompt = render_prompt(
            "mobile_jd/standardize",
            context={
                "raw_jd": cleaned_jd,
                "platform_name": platform["name"],
                "platform_guidance": PLATFORM_GUIDANCE.get(target_platform, PLATFORM_GUIDANCE["generic"]),
            },
        )
        settings = get_settings()
        response_text = generate_content(
            settings.mobile_jd_gemini_model,
            prompt,
            {"response_mime_type": "application/json", "temperature": 0.15, "top_p": 0.5, "top_k": 10},
            api_keys=settings.mobile_jd_gemini_api_keys,
        )
        result = _normalize_ai_payload(_extract_json(response_text), cleaned_jd)
    except Exception:
        result = _build_fallback(cleaned_jd, target_platform)

    result["platform"] = platform
    result["platformUrl"] = platform["url"]
    result["generatedAt"] = datetime.now(timezone.utc).isoformat()
    return result
