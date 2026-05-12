from __future__ import annotations

import json
import re
from typing import Any, Dict

from app.core.config import get_settings
from app.prompts import render_prompt
from app.services.gemini_service import generate_content


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    cleaned = cleaned.replace(",}", "}").replace(",]", "]")
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("AI did not return a JSON object")
    return data


def refine_cv_profile(cv_text: str, current_education: str | None, current_name: str | None) -> Dict[str, Any]:
    settings = get_settings()

    education_prompt = render_prompt(
        "candidate_refinement/education_validation",
        context={
            "cv_text": cv_text[:4000],
            "current_education": current_education or "Chua co",
        },
    )
    education_text = generate_content(
        settings.gemini_default_model,
        education_prompt,
        {"response_mime_type": "application/json", "temperature": 0, "top_p": 0, "top_k": 1},
    )
    education_data = _extract_json_object(education_text)

    name_prompt = render_prompt(
        "candidate_refinement/refine_name",
        context={
            "cv_text": cv_text[:2000],
            "current_name": current_name or "",
        },
    )
    refined_name_text = generate_content(
        settings.gemini_default_model,
        name_prompt,
        {"temperature": 0.1, "top_p": 0.1, "top_k": 1},
    )
    refined_name = re.sub(r'^["\'`]+|["\'`]+$', "", refined_name_text.strip())
    if not refined_name or refined_name.lower() in {"null", "khong tim thay"} or len(refined_name) < 2:
        refined_name = None

    warnings = education_data.get("warnings")
    return {
        "standardized_education": education_data.get("standardizedEducation"),
        "validation_note": education_data.get("validationNote"),
        "warnings": warnings if isinstance(warnings, list) else [],
        "refined_name": refined_name,
    }
