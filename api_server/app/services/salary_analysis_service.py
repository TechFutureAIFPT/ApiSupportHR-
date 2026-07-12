from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import get_settings
from app.prompts import render_prompt
from app.services.gemini_service import generate_content
from app.services.salary_market_service import (
    estimate_salary_fallback,
    fetch_market_salary,
    get_experience_level,
    normalize_job_title,
    normalize_location,
)


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


def _format_vnd(amount: float) -> str:
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.1f} tỷ VND"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f} triệu VND"
    return f"{amount:,.0f} VND"


def _market_data_text(market_salary: dict[str, Any], is_estimate: bool) -> str:
    label = "Ước tính nội bộ (không phải dữ liệu thời gian thực)" if is_estimate else "Dữ liệu thực từ job-salary-data API"
    return (
        f"Nguồn: {label}.\n"
        f"P25: {_format_vnd(market_salary['p25'])}\n"
        f"Trung vị: {_format_vnd(market_salary['median'])}\n"
        f"P75: {_format_vnd(market_salary['p75'])}"
    )


def _compare_salary(current_salary: float, market_salary: dict[str, Any]) -> dict[str, Any]:
    median = market_salary["median"]
    difference = current_salary - median
    difference_percent = round((difference / median) * 100, 1) if median else 0.0

    if current_salary < market_salary["p25"]:
        market_position = "below"
    elif current_salary > market_salary["p75"]:
        market_position = "above"
    else:
        market_position = "reasonable"

    return {
        "currentSalary": current_salary,
        "marketPosition": market_position,
        "difference": difference,
        "differencePercent": difference_percent,
    }


def _fallback_result(
    job_title: str,
    location: str,
    market_salary: dict[str, Any],
    is_estimate: bool,
    current_salary: float | None,
) -> dict[str, Any]:
    median = market_salary["median"]
    negotiation_tips = [
        "Đánh giá kỹ năng và kinh nghiệm thực tế so với yêu cầu công việc trước khi đề xuất mức lương.",
        f"Median thị trường ({_format_vnd(median)}) là mức an toàn để bắt đầu đàm phán.",
        f"Nếu có kỹ năng nổi trội, hướng tới P75 ({_format_vnd(market_salary['p75'])}).",
    ]

    if current_salary:
        if current_salary < market_salary["p25"]:
            position_text = "thấp hơn thị trường"
        elif current_salary > market_salary["p75"]:
            position_text = "cao hơn thị trường"
        else:
            position_text = "trong khoảng hợp lý của thị trường"
        summary = (
            f"Mức lương hiện tại ({_format_vnd(current_salary)}) đang {position_text} "
            f"(median: {_format_vnd(median)})."
        )
    else:
        summary = (
            f"Khoảng lương {'ước tính' if is_estimate else 'thị trường'} cho vị trí \"{job_title}\" tại {location} "
            f"là từ {_format_vnd(market_salary['p25'])} đến {_format_vnd(market_salary['p75'])}."
        )

    return {
        "summary": summary,
        "recommendation": (
            f"Mức lương xứng đáng đề xuất khoảng {_format_vnd(median)} (median), tùy kỹ năng và kinh nghiệm cụ thể "
            "có thể đàm phán trong khoảng đã nêu."
        ),
        "negotiationTips": negotiation_tips,
        "confidenceNote": (
            "Dữ liệu ước tính nội bộ, chưa phải số liệu thị trường real-time."
            if is_estimate
            else "Dữ liệu từ job-salary-data API (RapidAPI), thị trường Việt Nam."
        ),
    }


def analyze_salary(
    job_title: str,
    *,
    location: str | None = None,
    years_of_experience: float | None = None,
    current_salary: float | None = None,
    jd_text: str = "",
    cv_text: str = "",
) -> dict[str, Any]:
    normalized_title = normalize_job_title(job_title)
    normalized_location = normalize_location(location)
    exp_level = get_experience_level(years_of_experience)

    market_salary = fetch_market_salary(normalized_title, normalized_location, exp_level["years"])
    is_estimate = market_salary is None
    if market_salary is None:
        market_salary = estimate_salary_fallback(job_title, normalized_location, years_of_experience)

    fallback = _fallback_result(job_title, normalized_location, market_salary, is_estimate, current_salary)
    result = dict(fallback)

    prompt = render_prompt(
        "salary/analyze",
        context={
            "job_title": job_title or "Không nêu rõ",
            "location": normalized_location,
            "experience_level": exp_level["level"],
            "market_data_text": _market_data_text(market_salary, is_estimate),
            "current_salary_text": _format_vnd(current_salary) if current_salary else "Không có thông tin",
            "jd_excerpt": (jd_text or "").strip()[:800] or "Không có",
            "cv_excerpt": (cv_text or "").strip()[:800] or "Không có",
        },
    )

    try:
        response_text = generate_content(
            get_settings().gemini_default_model,
            prompt,
            {"temperature": 0.25, "responseMimeType": "application/json"},
        )
        parsed = _extract_json_payload(response_text)
        if parsed:
            raw_tips = parsed.get("negotiationTips")
            tips = (
                [str(item).strip() for item in raw_tips if str(item).strip()]
                if isinstance(raw_tips, list)
                else []
            )
            result = {
                "summary": _normalize_text(parsed.get("summary")) or fallback["summary"],
                "recommendation": _normalize_text(parsed.get("recommendation")) or fallback["recommendation"],
                "negotiationTips": tips[:5] or fallback["negotiationTips"],
                "confidenceNote": _normalize_text(parsed.get("confidenceNote")) or fallback["confidenceNote"],
            }
    except Exception as error:  # pragma: no cover - network/provider path
        print(f"[Salary Analysis] Gemini synthesis failed, using template fallback: {error}")

    comparison = _compare_salary(current_salary, market_salary) if current_salary else None

    return {
        "summary": result["summary"],
        "marketSalary": market_salary,
        "comparison": comparison,
        "recommendation": result["recommendation"],
        "negotiationTips": result["negotiationTips"],
        "source": (
            "Ước tính dựa trên dữ liệu nội bộ và xu hướng thị trường Việt Nam (API không khả dụng)."
            if is_estimate
            else "Theo dữ liệu từ job-salary-data API (RapidAPI), thị trường Việt Nam."
        ),
        "confidenceNote": result["confidenceNote"],
    }
