from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List

from app.core.config import get_settings
from app.prompts import render_prompt
from app.services.gemini_service import generate_content


MISSING_DETAIL_EVIDENCE = "AI chua tra ve dan chung cu the cho tieu chi nay."
MISSING_DETAIL_EXPLANATION = "AI chua tra ve phan tich chi tiet cho tieu chi nay."


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


def _normalize_criterion_name(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized).strip().lower()
    return normalized


def _detail_item(title: str, score: str, formula: str, evidence: str, explanation: str) -> Dict[str, str]:
    return {
        "Tieu chi": title,
        "Tiêu chí": title,
        "Diem": score,
        "Điểm": score,
        "Cong thuc": formula,
        "Công thức": formula,
        "Dan chung": evidence,
        "Dẫn chứng": evidence,
        "Giai thich": explanation,
        "Giải thích": explanation,
    }


def _extract_criterion_specs(weights: Dict[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for criterion in weights.values():
        if not isinstance(criterion, dict):
            continue

        name = str(criterion.get("name") or "").strip()
        if not name:
            continue

        total_weight = 0.0
        children = criterion.get("children") or []
        if isinstance(children, list) and children:
            for child in children:
                if isinstance(child, dict):
                    total_weight += float(child.get("weight") or 0)
        else:
            total_weight = float(criterion.get("weight") or 0)

        specs.append(
            {
                "name": name,
                "max_score": total_weight,
                "normalized": _normalize_criterion_name(name),
            }
        )
    return specs


def _format_score_value(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _get_detail_value(record: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _ensure_analysis_shape(candidate: Dict[str, Any], criterion_specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    analysis = candidate.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
        candidate["analysis"] = analysis

    raw_details = analysis.get("Chi tiet") or analysis.get("Chi tiết") or analysis.get("Chi tiáº¿t") or []
    details = [item for item in raw_details if isinstance(item, dict)] if isinstance(raw_details, list) else []

    matched_details: Dict[str, Dict[str, Any]] = {}
    extras: List[Dict[str, Any]] = []
    for item in details:
        criterion_name = _get_detail_value(item, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­")
        normalized_name = _normalize_criterion_name(criterion_name)
        if normalized_name and normalized_name not in matched_details:
            matched_details[normalized_name] = item
        else:
            extras.append(item)

    normalized_details: List[Dict[str, Any]] = []
    matched_names = {spec["normalized"] for spec in criterion_specs}
    for spec in criterion_specs:
        existing = matched_details.get(spec["normalized"])
        if existing:
            score = _get_detail_value(existing, "Diem", "Điểm", "Äiá»ƒm")
            formula = _get_detail_value(existing, "Cong thuc", "Công thức", "CÃ´ng thá»©c")
            evidence = _get_detail_value(existing, "Dan chung", "Dẫn chứng", "Dáº«n chá»©ng")
            explanation = _get_detail_value(existing, "Giai thich", "Giải thích", "Giáº£i thÃ­ch")
            normalized_details.append(
                _detail_item(
                    spec["name"],
                    score or (f"0/{_format_score_value(spec['max_score'])}" if spec["max_score"] > 0 else "0"),
                    formula,
                    evidence or MISSING_DETAIL_EVIDENCE,
                    explanation or MISSING_DETAIL_EXPLANATION,
                )
            )
        else:
            normalized_details.append(
                _detail_item(
                    spec["name"],
                    f"0/{_format_score_value(spec['max_score'])}" if spec["max_score"] > 0 else "0",
                    f"Tieu chi '{spec['name']}' co trong cau hinh backend nhung AI chua tra ve chi tiet.",
                    MISSING_DETAIL_EVIDENCE,
                    MISSING_DETAIL_EXPLANATION,
                )
            )

    for item in details + extras:
        criterion_name = _get_detail_value(item, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­")
        if _normalize_criterion_name(criterion_name) in matched_names:
            continue
        normalized_details.append(
            _detail_item(
                criterion_name or "Tieu chi bo sung",
                _get_detail_value(item, "Diem", "Điểm", "Äiá»ƒm"),
                _get_detail_value(item, "Cong thuc", "Công thức", "CÃ´ng thá»©c"),
                _get_detail_value(item, "Dan chung", "Dẫn chứng", "Dáº«n chá»©ng"),
                _get_detail_value(item, "Giai thich", "Giải thích", "Giáº£i thÃ­ch"),
            )
        )

    analysis["Chi tiet"] = normalized_details
    analysis["Chi tiết"] = normalized_details
    analysis["Chi tiáº¿t"] = normalized_details
    return candidate


def _post_process_candidates(candidates: List[Dict[str, Any]], weights: Dict[str, Any]) -> List[Dict[str, Any]]:
    criterion_specs = _extract_criterion_specs(weights)
    if not criterion_specs:
        return candidates

    return [_ensure_analysis_shape(candidate, criterion_specs) for candidate in candidates if isinstance(candidate, dict)]


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

    return render_prompt(
        "cv_analysis/analyze_entries",
        context={
            "compact_jd": compact_jd,
            "compact_weights": compact_weights,
            "location": hard_filters.get("location") or "Linh hoat",
            "min_exp": hard_filters.get("minExp") or "Khong yeu cau",
            "seniority": hard_filters.get("seniority") or "Linh hoat",
        },
    )


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

    return _post_process_candidates(_extract_json_array(response_text), weights)
