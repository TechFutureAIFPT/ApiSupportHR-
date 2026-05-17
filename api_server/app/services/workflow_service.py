from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List

from app.core.config import get_settings
from app.prompts import render_prompt
from app.services.gemini_service import generate_content


def _extract_json(text: str) -> Any:
    cleaned = text.strip()
    start = min([index for index in [cleaned.find("{"), cleaned.find("[")] if index != -1], default=-1)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))

    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]

    cleaned = cleaned.replace(",}", "}").replace(",]", "]")
    return json.loads(cleaned)


def _format_jd_sections(data: Dict[str, Any]) -> str:
    sections = []
    if (data.get("MucDichCongViec") or "").strip():
        sections.append(f"MUC DICH CONG VIEC\n{data['MucDichCongViec'].strip()}")
    if (data.get("MoTaCongViec") or "").strip():
        sections.append(f"MO TA CONG VIEC\n{data['MoTaCongViec'].strip()}")
    if (data.get("YeuCauCongViec") or "").strip():
        sections.append(f"YEU CAU CONG VIEC\n{data['YeuCauCongViec'].strip()}")
    return "\n\n".join(sections).strip()


def _normalize_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _normalize_location_text(value: str) -> str:
    location = re.sub(r"\s+", " ", str(value or "")).strip()
    if not location:
        return ""

    location_map = {
        "hn": "Ha Noi",
        "hanoi": "Ha Noi",
        "ha noi": "Ha Noi",
        "hcm": "Thanh pho Ho Chi Minh",
        "tp hcm": "Thanh pho Ho Chi Minh",
        "tphcm": "Thanh pho Ho Chi Minh",
        "tp ho chi minh": "Thanh pho Ho Chi Minh",
        "ho chi minh": "Thanh pho Ho Chi Minh",
        "sai gon": "Thanh pho Ho Chi Minh",
        "saigon": "Thanh pho Ho Chi Minh",
        "da nang": "Da Nang",
        "danang": "Da Nang",
        "hai phong": "Hai Phong",
        "haiphong": "Hai Phong",
        "wfh": "Remote",
        "work from home": "Remote",
        "lam viec tu xa": "Remote",
        "tu xa": "Remote",
        "remote": "Remote",
    }
    return location_map.get(_normalize_ascii(location), location[:120])


def structure_jd(raw_text: str) -> str:
    prompt = render_prompt(
        "workflow/jd_structure",
        context={"raw_text": raw_text[:4000]},
    )
    settings = get_settings()
    response_text = generate_content(
        settings.gemini_default_model,
        prompt,
        {"response_mime_type": "application/json", "temperature": 0, "top_p": 0, "top_k": 1},
    )
    data = _extract_json(response_text)
    structured = _format_jd_sections(data)
    if not structured:
        raise ValueError("Khong the trich xuat noi dung co y nghia tu JD.")
    return structured


def extract_job_position(jd_text: str) -> str:
    prompt = render_prompt(
        "workflow/extract_job_position",
        context={"jd_text": jd_text[:2000]},
    )
    settings = get_settings()
    text = generate_content(settings.gemini_default_model, prompt, {"temperature": 0.3, "top_p": 0.7, "top_k": 10})
    position = re.sub(r'^["\'`]+|["\'`]+$', "", text.strip())
    position = re.sub(r"^(chuc danh|vi tri|position|job title)[:\s]*", "", position, flags=re.IGNORECASE)
    position = re.sub(r"[\n\r]+", " ", position)
    position = re.sub(r"\s+", " ", position).strip()
    return position if 3 <= len(position) <= 80 else ""


def _convert_language_level_to_cefr(text: str) -> str | None:
    upper_text = text.upper()
    if "IELTS" in upper_text:
        match = re.search(r"IELTS\s*(\d+\.?\d*)", upper_text)
        if match:
            score = float(match.group(1))
            if score >= 8.0:
                return "C2"
            if score >= 7.0:
                return "C1"
            if score >= 5.5:
                return "B2"
            if score >= 4.0:
                return "B1"
    if "TOEIC" in upper_text:
        match = re.search(r"TOEIC\s*(\d+)", upper_text)
        if match:
            score = int(match.group(1))
            if score >= 945:
                return "C2"
            if score >= 785:
                return "C1"
            if score >= 550:
                return "B2"
            if score >= 225:
                return "B1"
    if "TOEFL" in upper_text:
        match = re.search(r"TOEFL\s*(\d+)", upper_text)
        if match:
            score = int(match.group(1))
            if score >= 110:
                return "C2"
            if score >= 87:
                return "C1"
            if score >= 57:
                return "B2"
            if score >= 42:
                return "B1"
    if "CPE" in upper_text or "PROFICIENCY" in upper_text:
        return "C2"
    if "CAE" in upper_text or "ADVANCED" in upper_text:
        return "C1"
    if "FCE" in upper_text or "FIRST" in upper_text:
        return "B2"
    if "PET" in upper_text or "PRELIMINARY" in upper_text:
        return "B1"
    if "THANH THAO" in upper_text or "XUAT SAC" in upper_text:
        return "C1"
    if "GIAO TIEP TOT" in upper_text or "KHA" in upper_text:
        return "B2"
    if "CO BAN" in upper_text or "TRUNG BINH" in upper_text:
        return "B1"
    return None


def extract_hard_filters(jd_text: str) -> Dict[str, str]:
    prompt = render_prompt(
        "workflow/extract_hard_filters",
        context={"jd_text": jd_text[:3000]},
    )
    settings = get_settings()
    response_text = generate_content(
        settings.gemini_default_model,
        prompt,
        {"response_mime_type": "application/json", "temperature": 0.1, "top_p": 0.3, "top_k": 5},
    )
    data = _extract_json(response_text)
    if not isinstance(data, dict):
        return {}

    validated: Dict[str, str] = {}

    location = str(data.get("location", "")).strip()
    normalized_location = _normalize_location_text(location)
    if normalized_location:
        validated["location"] = normalized_location

    min_exp = str(data.get("minExp", "")).strip()
    if min_exp:
        if min_exp in {"1", "2", "3", "5"}:
            validated["minExp"] = min_exp
        else:
            match = re.search(r"(\d+)", min_exp)
            if match:
                years = int(match.group(1))
                if years <= 1:
                    validated["minExp"] = "1"
                elif years == 2:
                    validated["minExp"] = "2"
                elif years in {3, 4}:
                    validated["minExp"] = "3"
                elif years >= 5:
                    validated["minExp"] = "5"

    valid_seniority = {"Intern", "Junior", "Mid-level", "Senior", "Lead"}
    seniority_map = {
        "Fresher": "Junior",
        "Entry": "Junior",
        "Middle": "Mid-level",
        "Mid": "Mid-level",
        "Staff": "Senior",
        "Manager": "Lead",
        "Tech Lead": "Lead",
        "Team Lead": "Lead",
    }
    seniority = str(data.get("seniority", "")).strip()
    if seniority in valid_seniority:
        validated["seniority"] = seniority
    elif seniority in seniority_map:
        validated["seniority"] = seniority_map[seniority]

    valid_education = {"High School", "Associate", "Bachelor", "Master", "PhD"}
    education_map = {
        "THPT": "High School",
        "Cao dang": "Associate",
        "Dai hoc": "Bachelor",
        "Ky su": "Bachelor",
        "Thac si": "Master",
        "Tien si": "PhD",
    }
    education = str(data.get("education", "")).strip()
    if education in valid_education:
        validated["education"] = education
    elif education in education_map:
        validated["education"] = education_map[education]

    language = str(data.get("language", "")).strip()
    language_map = {
        "English": "Tieng Anh",
        "Vietnamese": "Tieng Viet",
        "Japanese": "Tieng Nhat",
        "Korean": "Tieng Han",
        "Chinese": "Tieng Trung",
    }
    if language:
        validated["language"] = language_map.get(language, language)

    language_level = str(data.get("languageLevel", "")).strip().upper()
    if language_level in {"B1", "B2", "C1", "C2"}:
        validated["languageLevel"] = language_level
    else:
        certificates = str(data.get("certificates", "")).strip()
        detected_level = _convert_language_level_to_cefr(certificates) or _convert_language_level_to_cefr(jd_text)
        if detected_level:
            validated["languageLevel"] = detected_level

    certificates = str(data.get("certificates", "")).strip()
    if certificates:
        validated["certificates"] = certificates

    valid_work_formats = {"Onsite", "Hybrid", "Remote"}
    work_format_map = {
        "Office": "Onsite",
        "WFH": "Remote",
        "Flexible": "Hybrid",
        "Linh hoat": "Hybrid",
    }
    work_format = str(data.get("workFormat", "")).strip()
    if work_format in valid_work_formats:
        validated["workFormat"] = work_format
    elif work_format in work_format_map:
        validated["workFormat"] = work_format_map[work_format]

    valid_contract_types = {"Full-time", "Part-time", "Intern", "Contract"}
    contract_map = {
        "Toan thoi gian": "Full-time",
        "Ban thoi gian": "Part-time",
        "Thuc tap": "Intern",
        "Thoi vu": "Contract",
    }
    contract_type = str(data.get("contractType", "")).strip()
    if contract_type in valid_contract_types:
        validated["contractType"] = contract_type
    elif contract_type in contract_map:
        validated["contractType"] = contract_map[contract_type]

    industry = str(data.get("industry", "")).strip()
    if industry:
        validated["industry"] = industry

    return validated


def _candidate_strength_weakness_areas(candidate: Dict[str, Any]) -> tuple[List[str], List[str]]:
    details = (((candidate.get("analysis") or {}).get("Chi tiáº¿t")) or ((candidate.get("analysis") or {}).get("Chi tiÃ¡ÂºÂ¿t")) or [])
    strengths: List[str] = []
    weaknesses: List[str] = []

    for detail in details:
        score_text = detail.get("Äiá»ƒm") or detail.get("Ã„ÂiÃ¡Â»Æ’m") or ""
        criterion = detail.get("TiÃªu chÃ­") or detail.get("TiÃƒÂªu chÃƒÂ­") or ""
        if "/" not in score_text or not criterion:
            continue
        try:
            score, max_score = score_text.split("/", 1)
            percentage = (float(score) / float(max_score)) * 100
        except Exception:
            continue
        if percentage >= 80:
            strengths.append(criterion)
        elif percentage < 50:
            weaknesses.append(criterion)
    return strengths, weaknesses


def _create_general_questions_prompt(analysis_data: Dict[str, Any], stats: Dict[str, Any]) -> str:
    return render_prompt(
        "workflow/interview_general",
        context={
            "job_position": stats.get("jobPosition", ""),
            "location_requirement": ((analysis_data.get("job") or {}).get("locationRequirement", "")),
            "total_candidates": stats.get("totalCandidates", 0),
            "industries": ", ".join(stats.get("industries", [])),
            "levels": ", ".join(stats.get("levels", [])),
            "common_weaknesses": ", ".join(stats.get("commonWeaknesses", [])),
            "skill_gaps": ", ".join(stats.get("skillGaps", [])),
        },
    )


def _create_specific_questions_prompt(analysis_data: Dict[str, Any], stats: Dict[str, Any], candidate: Dict[str, Any]) -> str:
    analysis = candidate.get("analysis") or {}
    strengths, weaknesses = _candidate_strength_weakness_areas(candidate)
    return render_prompt(
        "workflow/interview_specific",
        context={
            "job_position": stats.get("jobPosition", ""),
            "location_requirement": ((analysis_data.get("job") or {}).get("locationRequirement", "")),
            "candidate_name": candidate.get("candidateName", ""),
            "candidate_job_title": candidate.get("jobTitle", ""),
            "candidate_industry": candidate.get("industry", ""),
            "candidate_level": candidate.get("experienceLevel", ""),
            "candidate_score": analysis.get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m", analysis.get("Tá»•ng Ä‘iá»ƒm", 0)),
            "candidate_rank": analysis.get("HÃ¡ÂºÂ¡ng", analysis.get("Háº¡ng", "")),
            "candidate_strengths": ", ".join(analysis.get("Ã„ÂiÃ¡Â»Æ’m mÃ¡ÂºÂ¡nh CV", analysis.get("Äiá»ƒm máº¡nh CV", []))),
            "candidate_weaknesses": ", ".join(analysis.get("Ã„ÂiÃ¡Â»Æ’m yÃ¡ÂºÂ¿u CV", analysis.get("Äiá»ƒm yáº¿u CV", []))),
            "strong_areas": ", ".join(strengths),
            "weak_areas": ", ".join(weaknesses),
        },
    )


def _create_comparative_questions_prompt(analysis_data: Dict[str, Any], stats: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
    profile_lines = []
    for index, candidate in enumerate(candidates, start=1):
        analysis = candidate.get("analysis") or {}
        strengths = ", ".join((analysis.get("Ã„ÂiÃ¡Â»Æ’m mÃ¡ÂºÂ¡nh CV", analysis.get("Äiá»ƒm máº¡nh CV", [])) or [])[:3])
        weaknesses = ", ".join((analysis.get("Ã„ÂiÃ¡Â»Æ’m yÃ¡ÂºÂ¿u CV", analysis.get("Äiá»ƒm yáº¿u CV", [])) or [])[:2])
        profile_lines.append(
            f"{index}. {candidate.get('candidateName', '')} | "
            f"Rank: {analysis.get('HÃ¡ÂºÂ¡ng', analysis.get('Háº¡ng', ''))} | "
            f"Score: {analysis.get('TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m', analysis.get('Tá»•ng Ä‘iá»ƒm', 0))} | "
            f"Title: {candidate.get('jobTitle', '')} | "
            f"Level: {candidate.get('experienceLevel', '')} | "
            f"Strengths: {strengths} | Weaknesses: {weaknesses}"
        )

    return render_prompt(
        "workflow/interview_comparative",
        context={
            "job_position": stats.get("jobPosition", ""),
            "location_requirement": ((analysis_data.get("job") or {}).get("locationRequirement", "")),
            "candidate_profiles": "\n".join(profile_lines),
        },
    )


def generate_interview_questions(
    analysis_data: Dict[str, Any],
    analysis_stats: Dict[str, Any],
    question_type: str,
    candidate_data: Any = None,
) -> List[Dict[str, Any]]:
    if question_type == "general":
        prompt = _create_general_questions_prompt(analysis_data, analysis_stats)
    elif question_type == "specific" and isinstance(candidate_data, dict):
        prompt = _create_specific_questions_prompt(analysis_data, analysis_stats, candidate_data)
    elif question_type == "comparative" and isinstance(candidate_data, list):
        prompt = _create_comparative_questions_prompt(analysis_data, analysis_stats, candidate_data)
    else:
        raise ValueError("Invalid question type or candidate data")

    settings = get_settings()
    response_text = generate_content(
        settings.gemini_default_model,
        prompt,
        {"response_mime_type": "application/json", "temperature": 0.3, "top_p": 0.8, "top_k": 40},
    )
    data = _extract_json(response_text)
    return data.get("questionSets", []) if isinstance(data, dict) else []
