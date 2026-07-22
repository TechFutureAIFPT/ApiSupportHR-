from __future__ import annotations

import json
import re
from typing import Any, Iterable

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.ai_contract import rank_from_score
from app.core.config import get_settings
from app.schemas.analysis import QuickCvScoreItem
from app.services.gemini_service import generate_content


MAX_CV_COUNT = 3
MAX_TEXT_CHARS_PER_CV = 14000


def _compact_text(value: str, limit: int = MAX_TEXT_CHARS_PER_CV) -> str:
    normalized = re.sub(r"\n{3,}", "\n\n", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}\n\n[TRUNCATED]"


def _extract_json_array(raw_text: str) -> list[dict[str, Any]]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            raise ValueError("AI response did not contain a JSON array")
        parsed = json.loads(match.group(0))

    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        parsed = parsed["items"]
    if not isinstance(parsed, list):
        raise ValueError("AI response JSON must be an array")
    return [item for item in parsed if isinstance(item, dict)]


def _rank_from_score(score: int) -> str:
    return rank_from_score(score)


def _normalize_item(item: dict[str, Any], file_name: str, extracted_text: str | None) -> QuickCvScoreItem:
    score = item.get("score", 0)
    try:
        score_int = max(0, min(100, int(round(float(score)))))
    except (TypeError, ValueError):
        score_int = 0

    normalized = {
        "file_name": str(item.get("file_name") or file_name),
        "candidate_name": str(item.get("candidate_name") or item.get("candidateName") or ""),
        "target_role": str(item.get("target_role") or item.get("targetRole") or ""),
        "score": score_int,
        "rank": str(item.get("rank") or _rank_from_score(score_int)).upper()[:1],
        "summary": str(item.get("summary") or ""),
        "strengths": [str(value) for value in item.get("strengths", []) if str(value).strip()]
        if isinstance(item.get("strengths"), list)
        else [],
        "weaknesses": [str(value) for value in item.get("weaknesses", []) if str(value).strip()]
        if isinstance(item.get("weaknesses"), list)
        else [],
        "improvements": [str(value) for value in item.get("improvements", []) if str(value).strip()]
        if isinstance(item.get("improvements"), list)
        else [],
        "matched_keywords": [str(value) for value in item.get("matched_keywords", []) if str(value).strip()]
        if isinstance(item.get("matched_keywords"), list)
        else [],
        "missing_keywords": [str(value) for value in item.get("missing_keywords", []) if str(value).strip()]
        if isinstance(item.get("missing_keywords"), list)
        else [],
        "warnings": [str(value) for value in item.get("warnings", []) if str(value).strip()]
        if isinstance(item.get("warnings"), list)
        else [],
        "extracted_text": extracted_text,
    }
    if normalized["rank"] not in {"A", "B", "C"}:
        normalized["rank"] = _rank_from_score(score_int)

    try:
        return QuickCvScoreItem.model_validate(normalized)
    except ValidationError as error:
        raise ValueError(f"Invalid quick CV score payload for {file_name}: {error}") from error


def _build_prompt(entries: list[dict[str, str]], jd_text: str | None) -> str:
    rubric = """
You are Support HR, an AI recruitment assistant. Score each CV quickly but rigorously.

Return ONLY a valid JSON array. Each item must use snake_case keys:
file_name, candidate_name, target_role, score, rank, summary, strengths,
weaknesses, improvements, matched_keywords, missing_keywords, warnings.

Rules:
- score is an integer from 0 to 100.
- rank is A for 80-100, B for 60-79, C for below 60.
- strengths, weaknesses, improvements must each contain 2-4 short Vietnamese bullets.
- If a JD is provided, score CV-to-JD fit. If no JD is provided, score overall CV quality for recruitment screening.
- Do not invent certifications, employers, projects, emails, or phone numbers.
- Mention missing evidence as a weakness instead of guessing.
- Keep output Vietnamese, concise, and recruiter-friendly.
""".strip()

    jd_section = jd_text.strip() if jd_text and jd_text.strip() else "No JD provided. Score general CV quality."
    cv_sections = []
    for index, entry in enumerate(entries, start=1):
        cv_sections.append(
            f"CV {index}\nfile_name: {entry['file_name']}\ntext:\n{_compact_text(entry['text'])}"
        )

    return f"{rubric}\n\nJD CONTEXT:\n{jd_section}\n\nCV INPUTS:\n\n" + "\n\n---\n\n".join(cv_sections)


def score_quick_cvs(
    entries: list[dict[str, str]],
    jd_text: str | None = None,
    include_extracted_text: bool = False,
    api_keys: Iterable[str] | None = None,
) -> list[QuickCvScoreItem]:
    if not entries:
        raise ValueError("At least one CV is required")
    if len(entries) > MAX_CV_COUNT:
        raise ValueError(f"Quick CV scoring supports at most {MAX_CV_COUNT} CVs per request")

    settings = get_settings()
    keys = list(api_keys or settings.quick_cv_gemini_api_keys)
    if not keys:
        raise HTTPException(status_code=500, detail="QUICK_CV_GEMINI_API_KEY not configured on server")

    prompt = _build_prompt(entries, jd_text)
    raw = generate_content(
        settings.quick_cv_gemini_model,
        [{"role": "user", "parts": [{"text": prompt}]}],
        {
            "temperature": 0.15,
            "topP": 0.2,
            "topK": 20,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
        api_keys=keys,
    )

    parsed = _extract_json_array(raw)
    if len(parsed) != len(entries):
        # Keep API predictable for the mobile UI even if the model skips one item.
        parsed_by_name = {str(item.get("file_name") or ""): item for item in parsed}
        parsed = [parsed_by_name.get(entry["file_name"], {}) for entry in entries]

    results: list[QuickCvScoreItem] = []
    for entry, item in zip(entries, parsed):
        extracted_text = entry["text"] if include_extracted_text else None
        results.append(_normalize_item(item, entry["file_name"], extracted_text))
    return results
