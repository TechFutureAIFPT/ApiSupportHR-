from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from typing import Any, Dict, List, Tuple


EDUCATION_LEVEL_ORDER = {
    "High School": 1,
    "Associate": 2,
    "Bachelor": 3,
    "Master": 4,
    "PhD": 5,
}

EDUCATION_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("PhD", ("tiến sĩ", "tien si", "phd", "doctor of philosophy", "doctoral")),
    ("Master", ("thạc sĩ", "thac si", "master", "mba")),
    ("Bachelor", ("đại học", "dai hoc", "cử nhân", "cu nhan", "bachelor", "kỹ sư", "ky su", "engineer degree")),
    ("Associate", ("cao đẳng", "cao dang", "associate", "college diploma")),
    ("High School", ("thpt", "trung học phổ thông", "trung hoc pho thong", "high school")),
]

MAJOR_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business-administration": (
        "quản trị kinh doanh",
        "quan tri kinh doanh",
        "business administration",
        "business management",
    ),
    "economics": (
        "kinh tế",
        "kinh te",
        "economics",
        "economic development",
    ),
    "accounting-finance": (
        "kế toán",
        "ke toan",
        "kiểm toán",
        "kiem toan",
        "tài chính",
        "tai chinh",
        "accounting",
        "finance",
        "financial management",
        "banking",
        "ngân hàng",
        "ngan hang",
    ),
    "human-resources": (
        "nhân sự",
        "nhan su",
        "quản trị nhân lực",
        "quan tri nhan luc",
        "human resources",
        "recruitment",
        "talent acquisition",
    ),
    "sales-marketing": (
        "marketing",
        "digital marketing",
        "truyền thông",
        "truyen thong",
        "sales",
        "kinh doanh",
        "ban hang",
        "business development",
        "thương mại",
        "thuong mai",
    ),
    "information-technology": (
        "công nghệ thông tin",
        "cong nghe thong tin",
        "cntt",
        "computer science",
        "information technology",
        "software engineering",
        "kỹ thuật phần mềm",
        "ky thuat phan mem",
        "data science",
    ),
    "operations-supply-chain": (
        "vận hành",
        "van hanh",
        "supply chain",
        "logistics",
        "chuỗi cung ứng",
        "chuoi cung ung",
        "operations management",
    ),
}

MAJOR_GROUP_KNOWLEDGE_AREAS: dict[str, list[str]] = {
    "business-administration": ["sales fundamentals", "customer management", "business operations"],
    "economics": ["market analysis", "business finance", "commercial reasoning"],
    "accounting-finance": ["accounting principles", "financial reporting", "budget control"],
    "human-resources": ["recruitment operations", "candidate screening", "people processes"],
    "sales-marketing": ["customer acquisition", "pipeline management", "campaign operations"],
    "information-technology": ["software development", "systems thinking", "technical tooling"],
    "operations-supply-chain": ["process optimization", "vendor coordination", "operational planning"],
}

DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sales": ("sales", "kinh doanh", "ban hang", "account manager", "business development", "customer success"),
    "hr": ("recruiter", "recruitment", "talent acquisition", "nhan su", "tuyen dung", "hr"),
    "marketing": ("marketing", "seo", "content", "brand", "social media", "performance marketing"),
    "finance": ("accounting", "finance", "ke toan", "tai chinh", "auditor", "controller"),
    "tech": ("developer", "engineer", "software", "backend", "frontend", "fullstack", "data"),
    "operations": ("operations", "van hanh", "logistics", "supply chain", "procurement", "planning"),
}

LOCATION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Remote", ("remote", "work from home", "wfh", "lam viec tu xa", "tu xa")),
    ("Ha Noi", ("ha noi", "hanoi")),
    ("Thanh pho Ho Chi Minh", ("ho chi minh", "tp hcm", "tphcm", "hcm", "sai gon", "saigon")),
    ("Da Nang", ("da nang", "danang")),
    ("Hai Phong", ("hai phong", "haiphong")),
)

PRESENT_MARKERS = ("present", "current", "hien tai", "nay", "den nay")
RANGE_SEPARATORS = r"(?:-|–|—|to|tới|toi|đến|den)"


def normalize_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9/]+", " ", normalized.lower()).strip()


def canonical_location(value: str) -> str:
    normalized = normalize_ascii(value)
    if not normalized:
        return ""
    for canonical, patterns in LOCATION_PATTERNS:
        if normalized == normalize_ascii(canonical):
            return canonical
        if any(pattern in normalized for pattern in patterns):
            return canonical
    return re.sub(r"\s+", " ", value).strip()[:120]


def extract_age_range(value: str) -> Dict[str, int]:
    text = normalize_ascii(value)
    patterns = [
        re.compile(rf"tuoi\s*(?:tu|from)?\s*(\d{{2}})\s*{RANGE_SEPARATORS}\s*(\d{{2}})"),
        re.compile(rf"(\d{{2}})\s*{RANGE_SEPARATORS}\s*(\d{{2}})\s*tuoi"),
        re.compile(r"tuoi\s*(?:tu|from)?\s*(\d{2})\s+(\d{2})"),
        re.compile(r"(\d{2})\s+(\d{2})\s*tuoi"),
        re.compile(r"toi da\s*(\d{2})\s*tuoi"),
        re.compile(r"duoi\s*(\d{2})\s*tuoi"),
        re.compile(r"tren\s*(\d{2})\s*tuoi"),
    ]

    for index, pattern in enumerate(patterns):
        match = pattern.search(text)
        if not match:
            continue
        if index < 4:
            min_age = int(match.group(1))
            max_age = int(match.group(2))
            if min_age <= max_age:
                return {"min": min_age, "max": max_age}
            return {"min": max_age, "max": min_age}
        if index in {4, 5}:
            return {"max": int(match.group(1))}
        return {"min": int(match.group(1))}
    return {}


def normalize_major_groups(value: Any) -> list[str]:
    if isinstance(value, list):
        tokens = [str(item or "").strip() for item in value]
    else:
        tokens = re.split(r"[,\n;/]+", str(value or ""))

    normalized_groups: list[str] = []
    for token in tokens:
        if not token.strip():
            continue
        group = classify_major_group(token)
        if group and group not in normalized_groups:
            normalized_groups.append(group)
    return normalized_groups


def classify_major_group(value: str) -> str:
    normalized = normalize_ascii(value)
    if not normalized:
        return ""
    for group, keywords in MAJOR_GROUP_KEYWORDS.items():
        if any(keyword in normalized for keyword in map(normalize_ascii, keywords)):
            return group
    return ""


def extract_major_groups_from_text(value: str) -> list[str]:
    groups: list[str] = []
    normalized = normalize_ascii(value)
    if not normalized:
        return groups
    for group, keywords in MAJOR_GROUP_KEYWORDS.items():
        if any(normalize_ascii(keyword) in normalized for keyword in keywords):
            groups.append(group)
    return list(dict.fromkeys(groups))


def _extract_birth_year_and_age(cv_text: str) -> tuple[int | None, int | None, list[str]]:
    warnings: list[str] = []
    now = datetime.now(timezone.utc)
    text = cv_text or ""
    normalized = normalize_ascii(text)

    birth_year: int | None = None
    birth_match = re.search(
        r"(?:ngay sinh|nam sinh|date of birth|birth year|dob)[:\s]*(?:\d{1,2}[/-]\d{1,2}[/-])?(19\d{2}|20\d{2})",
        normalized,
    )
    if birth_match:
        birth_year = int(birth_match.group(1))
    else:
        year_candidates = [int(value) for value in re.findall(r"\b(19\d{2}|20\d{2})\b", normalized)]
        plausible = [value for value in year_candidates if now.year - 65 <= value <= now.year - 16]
        if plausible:
            birth_year = plausible[0]

    age: int | None = None
    age_match = re.search(r"\b(\d{2})\s*(?:tuoi|years old|yrs old)\b", normalized)
    if age_match:
        age = int(age_match.group(1))
    elif birth_year:
        age = now.year - birth_year

    if birth_year and age and not (16 <= age <= 65):
        warnings.append("Tuổi trích xuất nằm ngoài ngưỡng hợp lý, cần HR kiểm tra lại.")

    return birth_year, age, warnings


def _extract_current_location(cv_text: str) -> str:
    text = cv_text or ""
    location_patterns = [
        r"(?:dia chi|địa chỉ|address|current location|noi o|nơi ở)[:\s]+([^\n,;]+(?:,\s*[^\n,;]+)?)",
        r"(?:song tai|living in|lam viec tai|working in)[:\s]*([^\n,;]+)",
    ]
    for pattern in location_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return canonical_location(match.group(1))
    return canonical_location(text)


def _extract_education_level(cv_text: str) -> tuple[str, list[str]]:
    normalized = normalize_ascii(cv_text)
    matched_levels: list[str] = []
    for level, keywords in EDUCATION_PATTERNS:
        if any(normalize_ascii(keyword) in normalized for keyword in keywords):
            matched_levels.append(level)
    if not matched_levels:
        return "", []
    matched_levels.sort(key=lambda item: EDUCATION_LEVEL_ORDER.get(item, 0), reverse=True)
    return matched_levels[0], matched_levels


def _extract_major_lines(cv_text: str) -> list[str]:
    lines = [line.strip() for line in re.split(r"[\n\r]+", cv_text or "") if line.strip()]
    major_lines: list[str] = []
    for line in lines:
        normalized = normalize_ascii(line)
        if any(keyword in normalized for keywords in MAJOR_GROUP_KEYWORDS.values() for keyword in map(normalize_ascii, keywords)):
            major_lines.append(line[:200])
    return major_lines[:8]


def _month_index(year: int, month: int) -> int:
    return year * 12 + month


def _month_count(start_year: int, start_month: int, end_year: int, end_month: int) -> int:
    return max(0, _month_index(end_year, end_month) - _month_index(start_year, start_month) + 1)


def _merge_month_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges = sorted(ranges, key=lambda item: item[0])
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _parse_work_periods(cv_text: str) -> tuple[list[dict[str, Any]], int]:
    now = datetime.now(timezone.utc)
    lines = [line.strip() for line in re.split(r"[\n\r]+", cv_text or "") if line.strip()]
    periods: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []
    patterns = [
        re.compile(
            rf"(?P<start_month>\d{{1,2}})[/-](?P<start_year>20\d{{2}}|19\d{{2}})\s*{RANGE_SEPARATORS}\s*(?:(?P<end_month>\d{{1,2}})[/-](?P<end_year>20\d{{2}}|19\d{{2}})|(?P<end_present>{'|'.join(PRESENT_MARKERS)}))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<start_year>20\d{{2}}|19\d{{2}})\s*{RANGE_SEPARATORS}\s*(?:(?P<end_year>20\d{{2}}|19\d{{2}})|(?P<end_present>{'|'.join(PRESENT_MARKERS)}))",
            re.IGNORECASE,
        ),
    ]

    for line in lines:
        for pattern in patterns:
            for match in pattern.finditer(line):
                start_year = int(match.group("start_year"))
                start_month = int(match.groupdict().get("start_month") or 1)
                end_present = match.groupdict().get("end_present")
                end_year = now.year if end_present else int(match.group("end_year"))
                end_month = now.month if end_present else int(match.groupdict().get("end_month") or 12)
                if _month_index(end_year, end_month) < _month_index(start_year, start_month):
                    continue

                periods.append(
                    {
                        "start": f"{start_year:04d}-{start_month:02d}",
                        "end": f"{end_year:04d}-{end_month:02d}",
                        "isCurrent": bool(end_present),
                        "evidence": line[:220],
                    }
                )
                ranges.append((_month_index(start_year, start_month), _month_index(end_year, end_month)))

    merged_ranges = _merge_month_ranges(ranges)
    total_months = sum((end - start + 1) for start, end in merged_ranges)
    return periods, total_months


def _extract_domains(text: str) -> list[str]:
    normalized = normalize_ascii(text)
    matched: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(normalize_ascii(keyword) in normalized for keyword in keywords):
            matched.append(domain)
    return matched


def _infer_target_domains(jd_text: str, hard_filters: Dict[str, Any]) -> list[str]:
    sources = [
        str(hard_filters.get("industry") or ""),
        str(hard_filters.get("jobTitle") or ""),
        jd_text,
    ]
    combined = " ".join(part for part in sources if part).strip()
    return _extract_domains(combined)


def build_candidate_profile(candidate: Dict[str, Any], cv_text: str, jd_text: str, hard_filters: Dict[str, Any]) -> Dict[str, Any]:
    birth_year, age, age_warnings = _extract_birth_year_and_age(cv_text)
    education_level, _matched_levels = _extract_education_level(cv_text)
    major_lines = _extract_major_lines(cv_text)
    major_groups = list(dict.fromkeys(group for line in major_lines for group in extract_major_groups_from_text(line)))
    inferred_knowledge = list(
        dict.fromkeys(
            area
            for group in major_groups
            for area in MAJOR_GROUP_KNOWLEDGE_AREAS.get(group, [])
        )
    )
    work_periods, total_experience_months = _parse_work_periods(cv_text)
    target_domains = _infer_target_domains(jd_text, hard_filters)
    experience_domains = list(dict.fromkeys(_extract_domains(cv_text)))

    relevant_periods = [
        period
        for period in work_periods
        if not target_domains or any(domain in _extract_domains(period.get("evidence", "")) for domain in target_domains)
    ]
    relevant_experience_months = sum(
        _month_count(
            int(period["start"].split("-")[0]),
            int(period["start"].split("-")[1]),
            int(period["end"].split("-")[0]),
            int(period["end"].split("-")[1]),
        )
        for period in relevant_periods
    ) if relevant_periods else total_experience_months

    extraction_warnings = age_warnings[:]
    if not work_periods:
        extraction_warnings.append("Không đọc được mốc thời gian kinh nghiệm rõ ràng từ CV.")
    if not education_level:
        extraction_warnings.append("Không xác định chắc chắn bằng cấp cao nhất từ CV.")

    return {
        "birthYear": birth_year,
        "age": age,
        "currentLocation": _extract_current_location(cv_text),
        "educationLevel": education_level,
        "educationMajors": major_groups,
        "inferredKnowledgeAreas": inferred_knowledge,
        "workPeriods": work_periods,
        "totalExperienceMonths": total_experience_months,
        "relevantExperienceMonths": relevant_experience_months,
        "experienceDomains": experience_domains,
        "extractionWarnings": extraction_warnings,
    }


def _screening_factor(
    key: str,
    *,
    status: str,
    mandatory: bool,
    expected: Any,
    observed: Any,
    evidence: str,
    reason: str,
) -> tuple[str, Dict[str, Any]]:
    return (
        key,
        {
            "status": status,
            "mandatory": mandatory,
            "expected": expected,
            "observed": observed,
            "evidence": evidence,
            "reason": reason,
        },
    )


def _format_months_as_years(months: int) -> str:
    years = months / 12 if months else 0
    return f"{years:.1f} năm" if years else "0 năm"


def build_screening_summary(profile: Dict[str, Any], jd_text: str, hard_filters: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    screening: Dict[str, Dict[str, Any]] = {}
    auto_reject_reasons: list[str] = []

    age_rule = hard_filters.get("age") if isinstance(hard_filters.get("age"), dict) else {}
    age_mandatory = bool(hard_filters.get("ageMandatory"))
    age_value = profile.get("age")
    if age_rule and (age_rule.get("min") is not None or age_rule.get("max") is not None):
        min_age = age_rule.get("min")
        max_age = age_rule.get("max")
        expected = {"min": min_age, "max": max_age}
        if age_value is None:
            factor = _screening_factor(
                "age",
                status="review",
                mandatory=age_mandatory,
                expected=expected,
                observed=None,
                evidence="Không tìm thấy năm sinh/tuổi chắc chắn trong CV.",
                reason="Thiếu dữ liệu tuổi để đối chiếu với yêu cầu JD.",
            )
        else:
            passed = (min_age is None or age_value >= min_age) and (max_age is None or age_value <= max_age)
            factor = _screening_factor(
                "age",
                status="pass" if passed else "fail",
                mandatory=age_mandatory,
                expected=expected,
                observed=age_value,
                evidence=f"Tuổi suy ra từ CV: {age_value}.",
                reason="Tuổi nằm trong khoảng yêu cầu." if passed else "Tuổi nằm ngoài khoảng yêu cầu của vị trí.",
            )
    else:
        factor = _screening_factor(
            "age",
            status="na",
            mandatory=age_mandatory,
            expected=None,
            observed=age_value,
            evidence="Không bật rule tuổi cho vị trí này.",
            reason="Không có điều kiện tuổi để sàng lọc.",
        )
    screening[factor[0]] = factor[1]

    education_expected = str(hard_filters.get("education") or "").strip()
    education_mandatory = bool(hard_filters.get("educationMandatory"))
    education_observed = str(profile.get("educationLevel") or "").strip()
    if education_expected:
        if not education_observed:
            factor = _screening_factor(
                "education",
                status="review",
                mandatory=education_mandatory,
                expected=education_expected,
                observed=None,
                evidence="Không đọc được bậc học rõ ràng từ CV.",
                reason="Thiếu dữ liệu học vấn để đối chiếu.",
            )
        else:
            passed = EDUCATION_LEVEL_ORDER.get(education_observed, 0) >= EDUCATION_LEVEL_ORDER.get(education_expected, 0)
            factor = _screening_factor(
                "education",
                status="pass" if passed else "fail",
                mandatory=education_mandatory,
                expected=education_expected,
                observed=education_observed,
                evidence=f"Bậc học cao nhất suy ra: {education_observed}.",
                reason="Đạt mức bằng cấp tối thiểu." if passed else "Bằng cấp hiện có thấp hơn yêu cầu tối thiểu.",
            )
    else:
        factor = _screening_factor(
            "education",
            status="na",
            mandatory=education_mandatory,
            expected=None,
            observed=education_observed or None,
            evidence="JD chưa đặt ngưỡng bằng cấp cụ thể.",
            reason="Không có rule học vấn để chấm.",
        )
    screening[factor[0]] = factor[1]

    major_expected = normalize_major_groups(hard_filters.get("majorGroups") or [])
    major_mandatory = bool(hard_filters.get("majorMandatory"))
    observed_major_groups = list(profile.get("educationMajors") or [])
    if major_expected:
        if not observed_major_groups:
            factor = _screening_factor(
                "major",
                status="review",
                mandatory=major_mandatory,
                expected=major_expected,
                observed=[],
                evidence="Không tìm thấy chuyên ngành phù hợp trong CV.",
                reason="Thiếu dữ liệu chuyên ngành để đối chiếu.",
            )
        else:
            matched_groups = [group for group in observed_major_groups if group in major_expected]
            passed = bool(matched_groups)
            factor = _screening_factor(
                "major",
                status="pass" if passed else "fail",
                mandatory=major_mandatory,
                expected=major_expected,
                observed=observed_major_groups,
                evidence=f"Nhóm ngành suy ra: {', '.join(observed_major_groups)}.",
                reason="Có chuyên ngành phù hợp với vị trí." if passed else "Chuyên ngành không khớp với nhóm ngành yêu cầu.",
            )
    else:
        factor = _screening_factor(
            "major",
            status="na",
            mandatory=major_mandatory,
            expected=[],
            observed=observed_major_groups,
            evidence="JD chưa chốt nhóm chuyên ngành cụ thể.",
            reason="Không có rule chuyên ngành để chấm.",
        )
    screening[factor[0]] = factor[1]

    expected_knowledge = list(
        dict.fromkeys(
            area
            for group in major_expected
            for area in MAJOR_GROUP_KNOWLEDGE_AREAS.get(group, [])
        )
    )
    observed_knowledge = list(profile.get("inferredKnowledgeAreas") or [])
    knowledge_mandatory = major_mandatory
    if expected_knowledge:
        if not observed_knowledge:
            factor = _screening_factor(
                "knowledge",
                status="review",
                mandatory=knowledge_mandatory,
                expected=expected_knowledge,
                observed=[],
                evidence="Chưa suy ra được vùng kiến thức từ chuyên ngành trong CV.",
                reason="Thiếu dữ liệu để xác nhận nền tảng kiến thức liên quan.",
            )
        else:
            matched_knowledge = [area for area in observed_knowledge if area in expected_knowledge]
            passed = bool(matched_knowledge)
            factor = _screening_factor(
                "knowledge",
                status="pass" if passed else "review",
                mandatory=knowledge_mandatory,
                expected=expected_knowledge,
                observed=observed_knowledge,
                evidence=f"Kiến thức suy ra theo rule map: {', '.join(observed_knowledge)}.",
                reason="Nền tảng kiến thức phù hợp với nhóm ngành yêu cầu." if passed else "Cần HR xác minh thêm nền tảng kiến thức liên quan.",
            )
    else:
        factor = _screening_factor(
            "knowledge",
            status="na",
            mandatory=knowledge_mandatory,
            expected=[],
            observed=observed_knowledge,
            evidence="Không có rule suy luận kiến thức được kích hoạt.",
            reason="Không áp dụng factor kiến thức cho JD này.",
        )
    screening[factor[0]] = factor[1]

    min_exp = str(hard_filters.get("minExp") or "").strip()
    exp_mandatory = bool(hard_filters.get("minExpMandatory"))
    total_exp_months = int(profile.get("totalExperienceMonths") or 0)
    relevant_exp_months = int(profile.get("relevantExperienceMonths") or 0)
    if min_exp:
        try:
            required_months = int(min_exp) * 12
        except ValueError:
            required_months = 0
        if relevant_exp_months <= 0 and total_exp_months <= 0:
            factor = _screening_factor(
                "experience",
                status="review",
                mandatory=exp_mandatory,
                expected={"minMonths": required_months},
                observed={"totalMonths": total_exp_months, "relevantMonths": relevant_exp_months},
                evidence="Không đọc được đủ timeline kinh nghiệm từ CV.",
                reason="Thiếu dữ liệu mốc thời gian kinh nghiệm để kết luận.",
            )
        else:
            passed = relevant_exp_months >= required_months
            factor = _screening_factor(
                "experience",
                status="pass" if passed else "fail",
                mandatory=exp_mandatory,
                expected={"minMonths": required_months},
                observed={"totalMonths": total_exp_months, "relevantMonths": relevant_exp_months},
                evidence=f"Kinh nghiệm liên quan ước tính {_format_months_as_years(relevant_exp_months)}; tổng {_format_months_as_years(total_exp_months)}.",
                reason="Đạt yêu cầu kinh nghiệm tối thiểu." if passed else "Kinh nghiệm liên quan thấp hơn ngưỡng JD yêu cầu.",
            )
    else:
        factor = _screening_factor(
            "experience",
            status="na",
            mandatory=exp_mandatory,
            expected=None,
            observed={"totalMonths": total_exp_months, "relevantMonths": relevant_exp_months},
            evidence="JD chưa đặt ngưỡng số năm kinh nghiệm.",
            reason="Không có rule kinh nghiệm để chấm.",
        )
    screening[factor[0]] = factor[1]

    required_location = canonical_location(str(hard_filters.get("location") or ""))
    location_mandatory = bool(hard_filters.get("locationMandatory"))
    observed_location = canonical_location(str(profile.get("currentLocation") or ""))
    if required_location:
        if not observed_location:
            factor = _screening_factor(
                "location",
                status="review",
                mandatory=location_mandatory,
                expected=required_location,
                observed=None,
                evidence="Không tìm thấy nơi ở/làm việc hiện tại rõ ràng trong CV.",
                reason="Thiếu dữ liệu địa điểm để đối chiếu.",
            )
        else:
            passed = normalize_ascii(required_location) in normalize_ascii(observed_location) or normalize_ascii(observed_location) in normalize_ascii(required_location)
            factor = _screening_factor(
                "location",
                status="pass" if passed else "fail",
                mandatory=location_mandatory,
                expected=required_location,
                observed=observed_location,
                evidence=f"Địa điểm hiện tại suy ra: {observed_location}.",
                reason="Địa điểm phù hợp với yêu cầu công việc." if passed else "Địa điểm hiện tại không khớp yêu cầu vị trí.",
            )
    else:
        factor = _screening_factor(
            "location",
            status="na",
            mandatory=location_mandatory,
            expected=None,
            observed=observed_location or None,
            evidence="JD không đặt điều kiện địa điểm cụ thể.",
            reason="Không có rule địa điểm để chấm.",
        )
    screening[factor[0]] = factor[1]

    for key, item in screening.items():
        if item["mandatory"] and item["status"] == "fail":
            auto_reject_reasons.append(str(item["reason"]))
        elif key == "location":
            # Keep backward-compatible reject reason for strict location mismatch.
            if bool(item["mandatory"]) and item["status"] == "fail":
                auto_reject_reasons.append(f"Không đạt điều kiện địa điểm: {item['observed']} so với {item['expected']}.")

    return screening, list(dict.fromkeys(auto_reject_reasons))
