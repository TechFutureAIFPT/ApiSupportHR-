from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any, Dict, List


KNOWN_SKILLS = [
    "Python",
    "FastAPI",
    "Django",
    "Flask",
    "Java",
    "Spring",
    "Spring Boot",
    "JavaScript",
    "TypeScript",
    "React",
    "Next.js",
    "Vue",
    "Angular",
    "Node.js",
    "NestJS",
    "Express",
    "REST API",
    "GraphQL",
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
    "Git",
    "CI/CD",
    "Excel",
    "Power BI",
    "Tableau",
    "Sales",
    "Recruitment",
    "Customer service",
]


def _normalize_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9+.#/]+", " ", normalized.lower()).strip()


def _split_sentences(text: str) -> List[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+|[;•]", text or "")
        if len(sentence.strip()) >= 8
    ]


def _extract_required_years(hard_filters: Dict[str, Any], jd_text: str) -> str:
    min_exp = str(hard_filters.get("minExp") or "").strip()
    if min_exp:
        return f"{min_exp} năm"

    normalized = _normalize_ascii(jd_text)
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:nam|year)", normalized)
    if match:
        return f"{match.group(1).replace(',', '.')} năm"
    return "Không nêu rõ trong JD"


def _extract_required_months(required_years_text: str) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)", required_years_text)
    if not match:
        return None
    return int(float(match.group(1)) * 12)


def _format_actual_experience(profile: Dict[str, Any]) -> str:
    months = int(profile.get("relevantExperienceMonths") or profile.get("totalExperienceMonths") or 0)
    if months <= 0:
        return "Chưa đủ dữ liệu để xác định từ CV"
    years = round(months / 12, 1)
    return f"Khoảng {years} năm"


def _experience_conclusion(required_years_text: str, profile: Dict[str, Any]) -> str:
    required_months = _extract_required_months(required_years_text)
    actual_months = int(profile.get("relevantExperienceMonths") or profile.get("totalExperienceMonths") or 0)
    if required_months is None:
        return "Đạt"
    if actual_months <= 0:
        return "Không đạt"
    if actual_months > required_months + 12:
        return "Vượt mức"
    if actual_months >= required_months:
        return "Đạt"
    return "Không đạt"


def _extract_required_skills(jd_text: str, hard_filters: Dict[str, Any]) -> List[str]:
    normalized_jd = _normalize_ascii(jd_text)
    skills: List[str] = []
    for skill in KNOWN_SKILLS:
        if _normalize_ascii(skill) in normalized_jd and skill not in skills:
            skills.append(skill)

    language = str(hard_filters.get("language") or "").strip()
    if language and language not in skills:
        skills.append(language)
    certificates = str(hard_filters.get("certificates") or "").strip()
    if certificates:
        for item in re.split(r"[,/;]+", certificates):
            token = item.strip()
            if token and token not in skills:
                skills.append(token)

    return skills[:8]


def _find_skill_evidence(skill: str, cv_text: str) -> str:
    normalized_skill = _normalize_ascii(skill)
    if not normalized_skill:
        return "Không tìm thấy trong CV"

    for sentence in _split_sentences(cv_text):
        if normalized_skill in _normalize_ascii(sentence):
            return sentence[:220]

    tokens = [token for token in normalized_skill.split() if len(token) >= 3]
    for sentence in _split_sentences(cv_text):
        normalized_sentence = _normalize_ascii(sentence)
        matched = sum(1 for token in tokens if token in normalized_sentence)
        if tokens and matched >= max(1, len(tokens) - 1):
            return sentence[:220]

    return "Không tìm thấy trong CV"


def _skill_status(skill: str, evidence: str) -> str:
    if evidence == "Không tìm thấy trong CV":
        return "Không đạt"
    normalized_skill = _normalize_ascii(skill)
    normalized_evidence = _normalize_ascii(evidence)
    if normalized_skill and normalized_skill in normalized_evidence:
        return "Đạt"
    return "Đạt một phần"


def _detect_job_hopping(cv_text: str) -> str | None:
    """Phát hiện nhảy việc: >3 vị trí trong 5 năm với thời gian trung bình <18 tháng."""
    pattern = re.compile(
        r"(\d{4})\s*[-–—]+\s*(\d{4}|hiện tại|present|nay|now)",
        re.IGNORECASE,
    )
    matches = pattern.findall(cv_text or "")
    if len(matches) < 3:
        return None

    current_year = datetime.datetime.now().year
    tenures: list[int] = []
    for start_str, end_str in matches:
        try:
            start = int(start_str)
            end = current_year if end_str.lower() in ("hiện tại", "present", "nay", "now") else int(end_str)
            if 1990 <= start <= current_year and start <= end <= current_year + 1:
                tenures.append(max(1, (end - start) * 12))
        except ValueError:
            continue

    if len(tenures) < 3:
        return None

    avg_months = sum(tenures) / len(tenures)
    span_years = sum(tenures) / 12

    if avg_months < 18 and span_years <= 6:
        return (
            f"Phát hiện {len(tenures)} vị trí trong ~{span_years:.0f} năm "
            f"(trung bình ~{round(avg_months)} tháng/vị trí) — dấu hiệu hay thay đổi công ty."
        )
    return None


def _detect_career_gap(cv_text: str) -> str | None:
    """Phát hiện khoảng trống nghề nghiệp >12 tháng giữa các vị trí liên tiếp."""
    pattern = re.compile(r"(\d{4})\s*[-–—]+\s*(\d{4})")
    matches = pattern.findall(cv_text or "")
    if len(matches) < 2:
        return None

    current_year = datetime.datetime.now().year
    periods: list[tuple[int, int]] = []
    for start_str, end_str in matches:
        try:
            start, end = int(start_str), int(end_str)
            if 1990 <= start <= current_year and start <= end <= current_year + 1:
                periods.append((start, end))
        except ValueError:
            continue

    if len(periods) < 2:
        return None

    periods_sorted = sorted(set(periods), key=lambda x: x[0])
    max_gap = 0
    gap_label = ""
    for i in range(1, len(periods_sorted)):
        gap = (periods_sorted[i][0] - periods_sorted[i - 1][1]) * 12
        if gap > max_gap:
            max_gap = gap
            gap_label = f"{periods_sorted[i - 1][1]}–{periods_sorted[i][0]}"

    if max_gap > 12:
        yrs, mths = max_gap // 12, max_gap % 12
        duration = f"~{yrs} năm" if mths == 0 else f"~{yrs} năm {mths} tháng"
        return f"Khoảng trống nghề nghiệp {duration} ({gap_label}) — chưa có giải thích trong hồ sơ."
    return None


def _build_red_flags(
    candidate: Dict[str, Any],
    screening_summary: Dict[str, Any],
    required_years_text: str,
    experience_conclusion: str,
    cv_text: str = "",
) -> List[str]:
    red_flags: List[str] = []

    for reason in candidate.get("autoRejectReasons") or []:
        text = str(reason).strip()
        if text and text not in red_flags:
            red_flags.append(text)

    hard_failure = str(candidate.get("hardFilterFailureReason") or "").strip()
    if hard_failure and hard_failure not in red_flags:
        red_flags.append(hard_failure)

    if screening_summary.get("location", {}).get("status") == "fail":
        reason = str(screening_summary.get("location", {}).get("reason") or "").strip()
        if reason and reason not in red_flags:
            red_flags.append(reason)

    if experience_conclusion == "Không đạt" and required_years_text != "Không nêu rõ trong JD":
        message = f"Kinh nghiệm thực tế thấp hơn yêu cầu {required_years_text}."
        if message not in red_flags:
            red_flags.append(message)

    hopping = _detect_job_hopping(cv_text)
    if hopping and hopping not in red_flags:
        red_flags.append(hopping)

    gap = _detect_career_gap(cv_text)
    if gap and gap not in red_flags:
        red_flags.append(gap)

    return red_flags


_VALID_SKILL_STATUS = {"Đạt", "Không đạt", "Đạt một phần"}
_VERDICT_TO_SKILL_STATUS = {
    "strong": "Đạt",
    "partial": "Đạt một phần",
    "weak": "Không đạt",
    "missing": "Không đạt",
}


def _normalize_gemini_red_flags(existing: Dict[str, Any]) -> List[str]:
    """Giữ lại các cảnh báo Gemini đã suy luận (MODULE 1-7 trong prompt) thay vì vứt bỏ."""
    raw = existing.get("canh_bao_red_flag")
    if not isinstance(raw, list):
        return []

    flags: List[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in flags:
            flags.append(text)
    return flags


def _index_gemini_skill_rows(existing: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Index danh_gia_ky_nang do Gemini trả về (đã đúng shape) theo tên kỹ năng đã normalize."""
    raw = existing.get("danh_gia_ky_nang")
    index: Dict[str, Dict[str, str]] = {}
    if not isinstance(raw, list):
        return index

    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("ten_ky_nang") or "").strip()
        status = str(item.get("muc_do_dap_ung") or "").strip()
        evidence = str(item.get("bang_chung_tu_cv") or "").strip()
        if not name or status not in _VALID_SKILL_STATUS or not evidence:
            continue
        key = _normalize_ascii(name)
        if key and key not in index:
            index[key] = {"muc_do_dap_ung": status, "bang_chung_tu_cv": evidence}
    return index


def _lookup_gemini_skill_row(skill: str, gemini_skill_index: Dict[str, Dict[str, str]]) -> Dict[str, str] | None:
    normalized_skill = _normalize_ascii(skill)
    if not normalized_skill:
        return None
    if normalized_skill in gemini_skill_index:
        return gemini_skill_index[normalized_skill]
    for key, row in gemini_skill_index.items():
        if normalized_skill in key or key in normalized_skill:
            return row
    return None


def _lookup_chi_tiet_skill_row(skill: str, chi_tiet: Any) -> Dict[str, str] | None:
    """Fallback: suy ra verdict kỹ năng từ advancedBreakdown.matched_signals/missing_requirements
    của từng tiêu chí trong Chi tiet, khi Gemini không liệt kê skill này trong danh_gia_ky_nang."""
    normalized_skill = _normalize_ascii(skill)
    if not normalized_skill or not isinstance(chi_tiet, list):
        return None

    for item in chi_tiet:
        if not isinstance(item, dict):
            continue
        breakdown = item.get("advancedBreakdown")
        if not isinstance(breakdown, dict):
            continue
        evidence_list = [str(e).strip() for e in (breakdown.get("evidence_highlights") or []) if str(e).strip()]

        for signal in breakdown.get("matched_signals") or []:
            if normalized_skill in _normalize_ascii(str(signal)):
                evidence = evidence_list[0] if evidence_list else str(signal).strip()
                return {"muc_do_dap_ung": "Đạt", "bang_chung_tu_cv": evidence[:220]}

        for gap in breakdown.get("missing_requirements") or []:
            if normalized_skill in _normalize_ascii(str(gap)):
                return {"muc_do_dap_ung": "Không đạt", "bang_chung_tu_cv": "Không tìm thấy trong CV"}

        verdict = str(breakdown.get("verdict") or "").strip().lower()
        tieu_chi = _normalize_ascii(str(item.get("Tieu chi") or ""))
        if verdict in _VERDICT_TO_SKILL_STATUS and normalized_skill and normalized_skill in tieu_chi:
            evidence = evidence_list[0] if evidence_list else "Không tìm thấy trong CV"
            return {"muc_do_dap_ung": _VERDICT_TO_SKILL_STATUS[verdict], "bang_chung_tu_cv": evidence[:220]}

    return None


def _build_overview(
    candidate: Dict[str, Any],
    profile: Dict[str, Any],
    red_flags: List[str],
    skills: List[Dict[str, str]],
) -> str:
    score = int(round(float((candidate.get("analysis") or {}).get("Tổng điểm") or (candidate.get("analysis") or {}).get("Tong diem") or 0)))
    name = str(candidate.get("candidateName") or "Ứng viên").strip() or "Ứng viên"

    matched_skills = [item["ten_ky_nang"] for item in skills if item["muc_do_dap_ung"] == "Đạt"][:2]
    actual_exp = _format_actual_experience(profile)
    if red_flags:
        return f"{name} hiện có mức phù hợp khoảng {score}/100 nhưng còn rủi ro cần chặn hoặc rà soát thêm. Bằng chứng chính ghi nhận {actual_exp} kinh nghiệm và các điểm vướng lớn gồm: {red_flags[0]}."
    if matched_skills:
        return f"{name} đáp ứng khá tốt yêu cầu tuyển dụng với mức phù hợp khoảng {score}/100. CV thể hiện {actual_exp} kinh nghiệm và đã thể hiện rõ các năng lực như {', '.join(matched_skills)}."
    return f"{name} có mức phù hợp khoảng {score}/100 nhưng bằng chứng chuyên môn trong CV chưa dày. Cần rà kỹ thêm kinh nghiệm thực tế và độ khớp với các kỹ năng bắt buộc."


def build_hr_summary(
    candidate: Dict[str, Any],
    cv_text: str,
    jd_text: str,
    hard_filters: Dict[str, Any],
    profile: Dict[str, Any] | None = None,
    screening_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    profile = profile or {}
    screening_summary = screening_summary or {}
    existing = candidate.get("hrSummary") if isinstance(candidate.get("hrSummary"), dict) else {}
    analysis = candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {}

    required_years_text = _extract_required_years(hard_filters, jd_text)
    actual_years_text = _format_actual_experience(profile)
    experience_result = _experience_conclusion(required_years_text, profile)

    required_skills = _extract_required_skills(jd_text, hard_filters)
    gemini_skill_index = _index_gemini_skill_rows(existing)
    chi_tiet = analysis.get("Chi tiet") if isinstance(analysis.get("Chi tiet"), list) else []

    skill_rows = []
    for skill in required_skills:
        gemini_row = _lookup_gemini_skill_row(skill, gemini_skill_index) or _lookup_chi_tiet_skill_row(skill, chi_tiet)
        if gemini_row is not None:
            skill_rows.append({"ten_ky_nang": skill, **gemini_row})
            continue
        evidence = _find_skill_evidence(skill, cv_text)
        skill_rows.append(
            {
                "ten_ky_nang": skill,
                "muc_do_dap_ung": _skill_status(skill, evidence),
                "bang_chung_tu_cv": evidence,
            }
        )

    rule_based_red_flags = _build_red_flags(candidate, screening_summary, required_years_text, experience_result, cv_text)
    red_flags = list(rule_based_red_flags)
    for flag in _normalize_gemini_red_flags(existing):
        if flag not in red_flags:
            red_flags.append(flag)
    red_flags = red_flags[:6]

    overview = _build_overview(candidate, profile, red_flags, skill_rows)
    raw_score = existing.get("tong_diem_phu_hop")
    if isinstance(raw_score, (int, float)):
        score = int(max(0, min(100, round(float(raw_score)))))
    else:
        score = int(max(0, min(100, round(float(analysis.get("Tổng điểm") or analysis.get("Tong diem") or 0)))))

    return {
        "tong_diem_phu_hop": score,
        "nhan_xet_tong_quan": str(existing.get("nhan_xet_tong_quan") or "").strip() or overview,
        "canh_bao_red_flag": red_flags,
        "kinh_nghiem": {
            "so_nam_yeu_cau": required_years_text,
            "so_nam_thuc_te": actual_years_text,
            "ket_luan": experience_result,
        },
        "danh_gia_ky_nang": skill_rows,
    }
