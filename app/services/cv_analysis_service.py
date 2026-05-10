from __future__ import annotations

import json
from typing import Any, Dict, List

from app.core.config import get_settings
from app.services.gemini_service import generate_content


def _build_compact_criteria(weights: Dict[str, Any]) -> str:
    lines: List[str] = []
    for criterion in weights.values():
        if not isinstance(criterion, dict):
            continue
        name = criterion.get("name")
        if not name:
            continue
        children = criterion.get("children") or []
        total_weight = 0
        if isinstance(children, list) and children:
            for child in children:
                if isinstance(child, dict):
                    total_weight += child.get("weight", 0) or 0
        else:
            total_weight = criterion.get("weight", 0) or 0
        lines.append(f"{name}: {total_weight}%")
    return "\n".join(lines)


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    cleaned = text.strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    cleaned = cleaned.replace(",}", "}").replace(",]", "]").replace("}\n{", "},{")
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("AI did not return a JSON array")
    return data


def _create_analysis_prompt(jd_text: str, weights: Dict[str, Any], hard_filters: Dict[str, Any]) -> str:
    compact_jd = " ".join(jd_text.split())[:5000]
    compact_weights = _build_compact_criteria(weights)

    return f"""
ADVANCED CV ANALYSIS SYSTEM.
Language: Vietnamese only.
Output: strict JSON array only.

NHIEM VU:
- Phan tich CV theo muc do phu hop voi JD.
- Tra ve du lieu co cau truc de frontend tiep tuc xu ly.

JOB DESCRIPTION:
{compact_jd}

TIEU CHI DANH GIA & TRONG SO:
{compact_weights}

BO LOC CUNG:
- Dia diem: {hard_filters.get('location') or 'Linh hoat'}
- Kinh nghiem toi thieu: {hard_filters.get('minExp') or 'Khong yeu cau'} nam
- Cap do: {hard_filters.get('seniority') or 'Linh hoat'}

YEU CAU OUTPUT:
Tra ve JSON array.
Moi phan tu trong array can co:
- candidateName
- phone
- email
- fileName
- jobTitle
- industry
- department
- experienceLevel
- hardFilterFailureReason
- softFilterWarnings
- detectedLocation
- analysis

Truong analysis can co:
- Tong diem
- Hang
- Chi tiet
- Diem manh CV
- Diem yeu CV
- educationValidation

Truong Chi tiet la array object gom:
- Tieu chi
- Diem
- Cong thuc
- Dan chung
- Giai thich

QUY TAC:
1. Tong diem tu 0 den 100.
2. Hang: A neu >=75, B neu >=50, C neu <50.
3. Neu khong doc duoc CV, van tra ve mot item voi fileName va thong tin loi hop ly.
4. Khong them markdown, khong them giai thich ngoai JSON.
"""


def analyze_cv_entries(
    jd_text: str,
    weights: Dict[str, Any],
    hard_filters: Dict[str, Any],
    cv_entries: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    settings = get_settings()
    prompt = _create_analysis_prompt(jd_text, weights, hard_filters)
    prompt_sections: List[str] = [prompt]

    for entry in cv_entries:
        file_name = entry.get("file_name", "unknown-file")
        text = (entry.get("text", "") or "").strip()
        if not text:
            continue
        if text.startswith("--- CV:"):
            prompt_sections.append(text)
        else:
            prompt_sections.append(f"--- CV: {file_name} ---\n{text}")

    response_text = generate_content(
        settings.gemini_default_model,
        "\n\n".join(prompt_sections),
        {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "topP": 0.8,
            "topK": 40,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    )

    return _extract_json_array(response_text)
