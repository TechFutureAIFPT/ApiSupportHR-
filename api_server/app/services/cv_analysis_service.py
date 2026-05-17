from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from typing import Any, Dict, List

from app.core.config import get_settings
from app.prompts import render_prompt
from app.schemas.analysis import StructuredCandidateOutputList
from app.services.gemini_service import generate_content


MISSING_DETAIL_EVIDENCE = "AI chua tra ve dan chung cu the cho tieu chi nay."
MISSING_DETAIL_EXPLANATION = "AI chua tra ve phan tich chi tiet cho tieu chi nay."
TECH_KEYWORDS = (
    "React",
    "Next.js",
    "Vue",
    "Angular",
    "Node.js",
    "Express",
    "NestJS",
    "Python",
    "FastAPI",
    "Django",
    "Flask",
    "Java",
    "Spring",
    "C#",
    ".NET",
    "Go",
    "Golang",
    "TypeScript",
    "JavaScript",
    "HTML",
    "CSS",
    "Tailwind",
    "GraphQL",
    "REST API",
    "SQL",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "Docker",
    "Kubernetes",
    "AWS",
    "GCP",
    "Azure",
    "CI/CD",
    "Git",
    "Machine Learning",
    "Deep Learning",
    "NLP",
    "TensorFlow",
    "PyTorch",
    "Pandas",
    "Scikit-learn",
    "Power BI",
    "Tableau",
    "Figma",
    "SEO",
    "Google Analytics",
)

LANGUAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "English": ("english", "tieng anh", "anh van"),
    "IELTS": ("ielts",),
    "TOEIC": ("toeic",),
    "TOEFL": ("toefl",),
    "Japanese": ("japanese", "tieng nhat", "nhat ngu", "jlpt", "n1", "n2", "n3", "n4", "n5"),
    "JLPT": ("jlpt", "n1", "n2", "n3", "n4", "n5"),
    "Korean": ("korean", "tieng han", "han ngu", "topik"),
    "TOPIK": ("topik",),
}

NEGATION_TERMS = (
    "khong co",
    "khong dat",
    "chua co",
    "chua dat",
    "khong biet",
    "no",
    "not",
    "without",
)


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


def _analysis_response_schema() -> dict[str, Any]:
    return StructuredCandidateOutputList.model_json_schema(by_alias=True)


def _normalize_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9+#.]+", " ", normalized.lower()).strip()


def _keyword_aliases(keyword: str) -> tuple[str, ...]:
    aliases = LANGUAGE_KEYWORDS.get(keyword)
    if aliases:
        return aliases
    normalized = _normalize_lookup(keyword)
    return (normalized,) if normalized else ()


def _has_alias(text: str, keyword: str) -> bool:
    normalized_text = f" {_normalize_lookup(text)} "
    for alias in _keyword_aliases(keyword):
        normalized_alias = _normalize_lookup(alias)
        if normalized_alias and normalized_alias in normalized_text:
            return True
    return False


def _is_negated_keyword(text: str, keyword: str) -> bool:
    normalized_text = f" {_normalize_lookup(text)} "
    for alias in _keyword_aliases(keyword):
        normalized_alias = _normalize_lookup(alias)
        if not normalized_alias:
            continue
        start = normalized_text.find(normalized_alias)
        if start < 0:
            continue
        prefix = normalized_text[max(0, start - 36) : start]
        if any(term in prefix for term in NEGATION_TERMS):
            return True
    return False


def _contains_keyword(text: str, keyword: str) -> bool:
    return _has_alias(text, keyword) and not _is_negated_keyword(text, keyword)


def _is_language_criterion(criterion_name: str) -> bool:
    normalized = _normalize_lookup(criterion_name)
    return "ngon ngu" in normalized or "language" in normalized


def _is_skill_or_fit_criterion(criterion_name: str) -> bool:
    normalized = _normalize_lookup(criterion_name)
    return any(term in normalized for term in ("ky nang", "skill", "job fit", "phu hop jd"))


def _extract_required_keywords(jd_text: str, criterion_name: str = "") -> list[str]:
    if _is_language_criterion(criterion_name):
        return [keyword for keyword in LANGUAGE_KEYWORDS if _has_alias(jd_text, keyword)]

    if criterion_name and not _is_skill_or_fit_criterion(criterion_name):
        return []

    matches: list[str] = []
    seen: set[str] = set()
    for keyword in TECH_KEYWORDS:
        if _has_alias(jd_text, keyword):
            key = _normalize_lookup(keyword)
            if key not in seen:
                seen.add(key)
                matches.append(keyword)
    return matches[:24]


def _find_keyword_context(text: str, keyword: str) -> str:
    if not text or not keyword:
        return ""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+|[•;]", text)
        if sentence.strip()
    ]
    for sentence in sentences:
        if _contains_keyword(sentence, keyword):
            return sentence[:260]
    return ""


def _keyword_metrics(jd_text: str, cv_text: str, criterion_name: str = "") -> dict[str, Any]:
    required_keywords = _extract_required_keywords(jd_text, criterion_name)
    keyword_rows: list[dict[str, Any]] = []
    matched_count = 0

    for keyword in required_keywords:
        matched = _contains_keyword(cv_text, keyword)
        if matched:
            matched_count += 1
        keyword_rows.append(
            {
                "keyword": keyword,
                "status": "matched" if matched else "missing",
                "context_sentence": _find_keyword_context(cv_text, keyword) if matched else "",
            }
        )

    total = len(required_keywords)
    return {
        "total_required_keywords": total,
        "matched_keywords_count": matched_count,
        "match_percentage": round((matched_count / total) * 100, 1) if total else 0.0,
        "keywords_list": keyword_rows,
    }


def _extract_numeric_score(value: str) -> float | None:
    match = re.search(r"[+-]?\d+(?:\.\d+)?", value or "")
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_score_pair(score_text: str, formula_text: str = "") -> tuple[int, int]:
    ratio_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)", score_text or "")
    if ratio_match:
        try:
            return max(0, round(float(ratio_match.group(1)))), max(0, round(float(ratio_match.group(2))))
        except ValueError:
            pass

    raw = _extract_numeric_score(score_text) or 0.0
    max_match = re.search(r"(?:/|max|toi da|tối đa)\s*([+-]?\d+(?:\.\d+)?)", formula_text or "", flags=re.I)
    max_score = raw
    if max_match:
        try:
            max_score = float(max_match.group(1))
        except ValueError:
            max_score = raw
    return max(0, round(raw)), max(0, round(max_score or raw))


def _as_advanced_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_deductions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    deductions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "").strip()
        points_lost = int(_extract_numeric_score(str(item.get("points_lost") or item.get("pointsLost") or 0)) or 0)
        if reason or points_lost:
            deductions.append({"reason": reason, "points_lost": max(0, points_lost)})
    return deductions


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _build_deductions(
    *,
    points_lost: int,
    missing_keywords: list[str],
    explanation: str,
) -> list[dict[str, Any]]:
    if points_lost <= 0:
        return []
    if missing_keywords:
        per_keyword = max(1, round(points_lost / max(1, len(missing_keywords))))
        remaining = points_lost
        deductions: list[dict[str, Any]] = []
        for keyword in missing_keywords[:8]:
            lost = min(per_keyword, remaining)
            remaining -= lost
            deductions.append(
                {
                    "reason": f"Thieu tu khoa cot loi trong JD: {keyword}",
                    "points_lost": lost,
                }
            )
            if remaining <= 0:
                break
        if remaining > 0:
            deductions.append({"reason": explanation or "Chua du bang chung de dat diem toi da.", "points_lost": remaining})
        return deductions
    return [{"reason": explanation or "Chua du bang chung de dat diem toi da.", "points_lost": points_lost}]


def _build_bonus_notes(formula: str, explanation: str) -> list[str]:
    combined = f"{formula} {explanation}".strip()
    normalized = _normalize_lookup(combined)
    if any(token in normalized for token in ("bonus", "cong diem", "diem cong", "boost", "multiplier")) or "+" in combined:
        return [combined[:220]]
    return []


def _merge_keyword_metrics(existing: Any, computed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        return computed
    keywords = existing.get("keywords_list")
    if not isinstance(keywords, list) or not keywords:
        return computed
    total = int(existing.get("total_required_keywords") or len(keywords) or 0)
    matched = int(existing.get("matched_keywords_count") or sum(1 for item in keywords if isinstance(item, dict) and item.get("status") == "matched"))
    return {
        "total_required_keywords": total,
        "matched_keywords_count": matched,
        "match_percentage": float(existing.get("match_percentage") or (matched / total * 100 if total else 0)),
        "keywords_list": [
            {
                "keyword": str(item.get("keyword") or "").strip(),
                "status": "matched" if item.get("status") == "matched" else "missing",
                "context_sentence": str(item.get("context_sentence") or "").strip(),
            }
            for item in keywords
            if isinstance(item, dict) and str(item.get("keyword") or "").strip()
        ],
    }


def _is_weak_formula(value: str) -> bool:
    normalized = _normalize_lookup(value)
    if not normalized:
        return True
    return "trong so" in normalized and not any(symbol in value for symbol in ("-", "+", "="))


def build_advanced_score_breakdown(detail: dict[str, Any], *, jd_text: str, cv_text: str) -> dict[str, Any]:
    existing = _as_advanced_dict(detail.get("advancedBreakdown") or detail.get("advanced_breakdown"))
    criterion_name = _get_detail_value(detail, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­", "Criterion")
    score_text = _get_detail_value(detail, "Diem", "Điểm", "Äiá»ƒm", "Score")
    formula = _get_detail_value(detail, "Cong thuc", "Công thức", "CÃ´ng thá»©c", "Formula")
    explanation = _get_detail_value(detail, "Giai thich", "Giải thích", "Giáº£i thÃ­ch", "Explanation")
    raw_score, max_score = _parse_score_pair(score_text, formula)
    max_score = max(max_score, raw_score)
    points_lost = max(0, max_score - raw_score)
    computed_metrics = _keyword_metrics(jd_text, cv_text, criterion_name)
    if computed_metrics.get("total_required_keywords"):
        metrics = computed_metrics
    elif _is_skill_or_fit_criterion(criterion_name) or _is_language_criterion(criterion_name):
        metrics = _merge_keyword_metrics(existing.get("keyword_metrics"), computed_metrics)
    else:
        metrics = computed_metrics
    missing_keywords = [
        str(item.get("keyword"))
        for item in metrics.get("keywords_list", [])
        if isinstance(item, dict) and item.get("status") == "missing"
    ]

    mathematical_formula = str(existing.get("mathematical_formula") or "").strip()
    if _is_weak_formula(mathematical_formula):
        if formula and not _is_weak_formula(formula):
            mathematical_formula = formula
        elif points_lost:
            mathematical_formula = f"{max_score}d (toi da) - {points_lost}d (cac diem chua dat) = {raw_score}d"
        else:
            mathematical_formula = f"{max_score}d (toi da) - 0d = {raw_score}d"

    deductions = _as_deductions(existing.get("deductions"))
    if not deductions:
        deductions = _build_deductions(
            points_lost=points_lost,
            missing_keywords=missing_keywords,
            explanation=explanation,
        )

    bonuses = _as_string_list(existing.get("bonuses_earned"))
    if not bonuses:
        bonuses = _build_bonus_notes(formula, explanation)

    return {
        "max_possible_score": int(existing.get("max_possible_score") or max_score),
        "raw_score_earned": int(existing.get("raw_score_earned") or raw_score),
        "mathematical_formula": mathematical_formula,
        "deductions": deductions,
        "bonuses_earned": bonuses,
        "keyword_metrics": metrics,
    }


def _normalize_core_score(score: str, max_score: float) -> str:
    if max_score <= 0:
        return score or "0"

    numeric = _extract_numeric_score(score)
    if not score:
        return f"0/{_format_score_value(max_score)}"

    ratio_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)", score)
    if ratio_match:
        try:
            current = float(ratio_match.group(1))
            current_max = float(ratio_match.group(2))
        except ValueError:
            current = numeric if numeric is not None else 0.0
            current_max = 0.0
        if current_max > 0:
            return f"{_format_score_value(current)}/{_format_score_value(current_max)}"
        return f"{_format_score_value(current)}/{_format_score_value(max_score)}"

    if numeric is not None:
        return f"{_format_score_value(numeric)}/{_format_score_value(max_score)}"

    return f"0/{_format_score_value(max_score)}"


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
            score = _normalize_core_score(
                _get_detail_value(existing, "Diem", "Điểm", "Äiá»ƒm"),
                float(spec["max_score"] or 0),
            )
            formula = _get_detail_value(existing, "Cong thuc", "Công thức", "CÃ´ng thá»©c")
            evidence = _get_detail_value(existing, "Dan chung", "Dẫn chứng", "Dáº«n chá»©ng")
            explanation = _get_detail_value(existing, "Giai thich", "Giải thích", "Giáº£i thÃ­ch")
            normalized_details.append(
                _detail_item(
                    spec["name"],
                    score,
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


def attach_advanced_score_breakdowns(
    candidates: List[Dict[str, Any]],
    cv_text_map: Dict[str, str],
    jd_text: str,
) -> List[Dict[str, Any]]:
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        file_name = str(candidate.get("fileName") or candidate.get("file_name") or "")
        cv_text = cv_text_map.get(file_name) or cv_text_map.get(file_name.lower()) or str(candidate.get("_cvText") or "")
        analysis = candidate.get("analysis")
        if not isinstance(analysis, dict):
            continue
        raw_details = analysis.get("Chi tiet") or analysis.get("Chi tiết") or analysis.get("Chi tiáº¿t") or []
        details = [item for item in raw_details if isinstance(item, dict)] if isinstance(raw_details, list) else []
        for detail in details:
            detail["advancedBreakdown"] = build_advanced_score_breakdown(detail, jd_text=jd_text, cv_text=cv_text)
        analysis["Chi tiet"] = details
        analysis["Chi tiết"] = details
        analysis["Chi tiáº¿t"] = details
    return candidates


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


def _create_analysis_prompt(
    jd_text: str,
    weights: Dict[str, Any],
    hard_filters: Dict[str, Any],
    *,
    context_notes: str = "",
) -> str:
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
            "context_notes": context_notes or "Khong co boi canh bo sung.",
        },
    )


def _build_prompt_sections(
    jd_text: str,
    weights: Dict[str, Any],
    hard_filters: Dict[str, Any],
    cv_entries: List[Dict[str, str]],
    *,
    entry_contexts: Dict[str, Dict[str, Any]] | None = None,
    context_notes: str = "",
) -> List[str]:
    prompt = _create_analysis_prompt(
        jd_text,
        weights,
        hard_filters,
        context_notes=context_notes,
    )
    prompt_sections: List[str] = [prompt]

    for entry in cv_entries:
        file_name = entry.get("file_name", "unknown-file")
        text = (entry.get("text", "") or "").strip()
        if not text:
            continue
        context_payload = (entry_contexts or {}).get(str(file_name), {})
        analysis_text = str(context_payload.get("analysis_text") or text).strip()
        entry_note = str(context_payload.get("entry_note") or "").strip()
        few_shot_examples = str(context_payload.get("few_shot_examples") or "").strip()

        if entry_note:
            prompt_sections.append(f"--- PIPELINE CONTEXT: {file_name} ---\n{entry_note}")
        if few_shot_examples:
            prompt_sections.append(f"--- FEW-SHOT GROUNDING: {file_name} ---\n{few_shot_examples}")

        if analysis_text.startswith("--- CV:"):
            prompt_sections.append(analysis_text)
        else:
            prompt_sections.append(f"--- CV: {file_name} ---\n{analysis_text}")

    return prompt_sections


def analyze_cv_entries(
    jd_text: str,
    weights: Dict[str, Any],
    hard_filters: Dict[str, Any],
    cv_entries: List[Dict[str, str]],
    *,
    entry_contexts: Dict[str, Dict[str, Any]] | None = None,
    context_notes: str = "",
) -> List[Dict[str, Any]]:
    settings = get_settings()
    prompt_sections = _build_prompt_sections(
        jd_text,
        weights,
        hard_filters,
        cv_entries,
        entry_contexts=entry_contexts,
        context_notes=context_notes,
    )
    response_text = generate_content(
        settings.gemini_cv_analysis_model,
        "\n\n".join(prompt_sections),
        {
            "responseMimeType": "application/json",
            "responseSchema": _analysis_response_schema(),
            "temperature": 0.1,
            "topP": 0.8,
            "topK": 40,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    )

    return _post_process_candidates(_extract_json_array(response_text), weights)


async def analyze_cv_entries_async(
    jd_text: str,
    weights: Dict[str, Any],
    hard_filters: Dict[str, Any],
    cv_entries: List[Dict[str, str]],
    *,
    entry_contexts: Dict[str, Dict[str, Any]] | None = None,
    context_notes: str = "",
) -> List[Dict[str, Any]]:
    settings = get_settings()
    prompt_sections = _build_prompt_sections(
        jd_text,
        weights,
        hard_filters,
        cv_entries,
        entry_contexts=entry_contexts,
        context_notes=context_notes,
    )
    response_text = await asyncio.to_thread(
        generate_content,
        settings.gemini_cv_analysis_model,
        "\n\n".join(prompt_sections),
        {
            "responseMimeType": "application/json",
            "responseSchema": _analysis_response_schema(),
            "temperature": 0.1,
            "topP": 0.8,
            "topK": 40,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    )
    return _post_process_candidates(_extract_json_array(response_text), weights)
