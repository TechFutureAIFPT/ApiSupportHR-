from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from app.core.config import get_settings
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


def structure_jd(raw_text: str) -> str:
    prompt = f"""
You clean and structure a raw Vietnamese job description.

Rules:
1. Keep only 3 sections: MucDichCongViec, MoTaCongViec, YeuCauCongViec.
2. Remove company intro, benefits, salary, contact info, and unrelated noise.
3. Fix obvious OCR and formatting issues but keep the original meaning.
4. Return JSON only with keys: MucDichCongViec, MoTaCongViec, YeuCauCongViec.
5. Use empty strings if a section is missing.

Raw JD:
---
{raw_text[:4000]}
---
"""
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
    prompt = f"""
Extract the exact job title from this Vietnamese job description.

Rules:
1. Return only the job title.
2. Remove labels like Job Title, Position, Chuc danh, Vi tri.
3. Keep the answer between 3 and 80 characters.
4. If unsure, infer from the main JD content.

JD:
---
{jd_text[:2000]}
---
"""
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
    prompt = f"""
Ban la chuyen gia phan tich JD thong minh.
Hay trich xuat va CHUAN HOA cac tieu chi loc tu JD.

Tra ve JSON only voi cac key:
- location
- minExp
- seniority
- education
- language
- languageLevel
- certificates
- workFormat
- contractType
- industry

Quy tac chuan hoa:
1. location chi duoc la: Ha Noi, Hai Phong, Da Nang, Thanh pho Ho Chi Minh, Remote
2. minExp chi duoc la: 1, 2, 3, 5
3. seniority chi duoc la: Intern, Junior, Mid-level, Senior, Lead
4. education chi duoc la: High School, Associate, Bachelor, Master, PhD
5. languageLevel chi duoc la: B1, B2, C1, C2
6. workFormat chi duoc la: Onsite, Hybrid, Remote
7. contractType chi duoc la: Full-time, Part-time, Intern, Contract
8. Neu khong co thong tin thi bo trong bang chuoi rong.

JD:
---
{jd_text[:3000]}
---
"""
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

    valid_locations = {"Ha Noi", "Hai Phong", "Da Nang", "Thanh pho Ho Chi Minh", "Remote"}
    location_map = {
        "HN": "Ha Noi",
        "Hanoi": "Ha Noi",
        "Ha Noi": "Ha Noi",
        "HCM": "Thanh pho Ho Chi Minh",
        "TP.HCM": "Thanh pho Ho Chi Minh",
        "Ho Chi Minh": "Thanh pho Ho Chi Minh",
        "Da Nang": "Da Nang",
        "WFH": "Remote",
    }
    location = str(data.get("location", "")).strip()
    if location in valid_locations:
        validated["location"] = location
    elif location in location_map:
        validated["location"] = location_map[location]

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
    details = (((candidate.get("analysis") or {}).get("Chi tiết")) or ((candidate.get("analysis") or {}).get("Chi tiáº¿t")) or [])
    strengths: List[str] = []
    weaknesses: List[str] = []

    for detail in details:
        score_text = detail.get("Điểm") or detail.get("Äiá»ƒm") or ""
        criterion = detail.get("Tiêu chí") or detail.get("TiÃªu chÃ­") or ""
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
    return f"""
Create high-quality interview question sets in Vietnamese for HR.

Return JSON only:
{{
  "questionSets": [
    {{
      "category": "string",
      "icon": "fa-solid fa-briefcase",
      "color": "text-blue-400",
      "questions": ["string"]
    }}
  ]
}}

Use the real hiring data below.
- Position: {stats.get("jobPosition", "")}
- Location: {((analysis_data.get("job") or {}).get("locationRequirement", ""))}
- Total candidates: {stats.get("totalCandidates", 0)}
- Main industries: {", ".join(stats.get("industries", []))}
- Main levels: {", ".join(stats.get("levels", []))}
- Common weaknesses: {", ".join(stats.get("commonWeaknesses", []))}
- Common skill gaps: {", ".join(stats.get("skillGaps", []))}

Requirements:
1. Create 4 to 5 groups.
2. Each group should have 4 to 6 practical questions.
3. Questions must reflect the real weaknesses and missing skills above.
4. Keep the output concise and professional.
"""


def _create_specific_questions_prompt(analysis_data: Dict[str, Any], stats: Dict[str, Any], candidate: Dict[str, Any]) -> str:
    analysis = candidate.get("analysis") or {}
    strengths, weaknesses = _candidate_strength_weakness_areas(candidate)
    return f"""
Create candidate-specific interview question sets in Vietnamese.

Return JSON only:
{{
  "questionSets": [
    {{
      "category": "string",
      "icon": "fa-solid fa-user-check",
      "color": "text-purple-400",
      "questions": ["string"]
    }}
  ]
}}

Hiring context:
- Position: {stats.get("jobPosition", "")}
- Location: {((analysis_data.get("job") or {}).get("locationRequirement", ""))}

Candidate:
- Name: {candidate.get("candidateName", "")}
- Job title: {candidate.get("jobTitle", "")}
- Industry: {candidate.get("industry", "")}
- Level: {candidate.get("experienceLevel", "")}
- Score: {analysis.get("Tá»•ng Ä‘iá»ƒm", analysis.get("Tổng điểm", 0))}
- Rank: {analysis.get("Háº¡ng", analysis.get("Hạng", ""))}
- Strengths: {", ".join(analysis.get("Äiá»ƒm máº¡nh CV", analysis.get("Điểm mạnh CV", [])))}
- Weaknesses: {", ".join(analysis.get("Äiá»ƒm yáº¿u CV", analysis.get("Điểm yếu CV", [])))}
- Strong areas: {", ".join(strengths)}
- Weak areas: {", ".join(weaknesses)}

Requirements:
1. Create 4 to 5 groups.
2. Each group should have 4 to 5 targeted questions.
3. Questions must validate the strengths and probe the weaknesses.
4. Avoid generic template wording.
"""


def _create_comparative_questions_prompt(analysis_data: Dict[str, Any], stats: Dict[str, Any], candidates: List[Dict[str, Any]]) -> str:
    profile_lines = []
    for index, candidate in enumerate(candidates, start=1):
        analysis = candidate.get("analysis") or {}
        strengths = ", ".join((analysis.get("Äiá»ƒm máº¡nh CV", analysis.get("Điểm mạnh CV", [])) or [])[:3])
        weaknesses = ", ".join((analysis.get("Äiá»ƒm yáº¿u CV", analysis.get("Điểm yếu CV", [])) or [])[:2])
        profile_lines.append(
            f"{index}. {candidate.get('candidateName', '')} | "
            f"Rank: {analysis.get('Háº¡ng', analysis.get('Hạng', ''))} | "
            f"Score: {analysis.get('Tá»•ng Ä‘iá»ƒm', analysis.get('Tổng điểm', 0))} | "
            f"Title: {candidate.get('jobTitle', '')} | "
            f"Level: {candidate.get('experienceLevel', '')} | "
            f"Strengths: {strengths} | Weaknesses: {weaknesses}"
        )

    return f"""
Create comparative interview question sets in Vietnamese for choosing the best candidate.

Return JSON only:
{{
  "questionSets": [
    {{
      "category": "string",
      "icon": "fa-solid fa-scale-balanced",
      "color": "text-cyan-400",
      "questions": ["string"]
    }}
  ]
}}

Hiring context:
- Position: {stats.get("jobPosition", "")}
- Location: {((analysis_data.get("job") or {}).get("locationRequirement", ""))}

Candidates:
{chr(10).join(profile_lines)}

Requirements:
1. Create 4 to 5 groups.
2. Each group should have 4 to 5 comparison-focused questions.
3. Questions should help HR distinguish technical skill, ownership, teamwork, and long-term fit.
"""


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
