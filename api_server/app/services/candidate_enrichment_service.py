from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.services.gemini_service import embed_text
from app.services.role_profile_service import get_role_requirements, is_generic_role, resolve_role_profile
from app.services.vector_store_service import search_similar_records


IT_KEYWORDS = ["it", "software", "developer", "engineer", "backend", "frontend", "fullstack", "full-stack", "devops", "data engineer", "data scientist", "ky su", "lap trinh", "qa", "tester", "product manager"]
SALES_KEYWORDS = ["sales", "kinh doanh", "ban hang", "thi truong", "business development", "account manager", "tu van", "sale"]
MARKETING_KEYWORDS = ["marketing", "truyen thong", "content", "seo", "social media", "brand", "quang cao", "pr", "digital"]
DESIGN_KEYWORDS = ["design", "thiet ke", "do hoa", "ui/ux", "art", "creative", "sang tao", "artist", "designer"]
SKILL_KEYWORDS = [
    "react", "vue", "angular", "node", "python", "java", "javascript", "typescript", "sql", "docker",
    "kubernetes", "aws", "gcp", "azure", "git", "ci/cd", "machine learning", "html", "css", "sass", "redux",
    "graphql", "mongodb", "postgresql", "mysql", "redis", "nextjs", "nuxt", "django", "flask", "spring",
    "springboot", "golang", "rust", "c++", "flutter", "react native", "swift", "kotlin", "figma", "photoshop",
    "tableau", "power bi", "scrum", "agile", "kanban", "jira", "leadership", "project management",
    "communication", "teamwork", "problem solving", "critical thinking", "nlp", "computer vision", "deep learning",
    "tensorflow", "pytorch", "data analysis", "data science", "statistics", "excel", "r programming",
]
COMPANY_NAME_WORDS = [
    "fpt", "viettel", "vnpt", "vingroup", "vinfast", "vietinbank", "vietcombank", "bidv", "shopee", "lazada",
    "tiki", "grab", "vng", "garena", "sea group", "vccorp", "misa", "haravan", "bkav", "mobifone", "cmc",
    "vietnampost", "google", "meta", "facebook", "apple", "amazon", "microsoft", "netflix", "nvidia", "tesla",
    "uber", "airbnb", "stripe", "salesforce", "adobe", "oracle", "ibm", "intel", "cisco", "sap", "siemens",
    "bosch", "philips", "jpmorgan", "goldman sachs", "morgan stanley", "bloomberg", "blackrock", "mckinsey",
    "bain", "bcg", "pwc", "deloitte", "kpmg", "ey",
]
BIAS_PATTERNS = [
    (re.compile(r"\b(nam|nu|nam gioi|nu gioi|gioi tinh|gender)\b", re.IGNORECASE), "gioi tinh"),
    (re.compile(r"\b(\d{2})\s*(tuoi|years?\s*old)\b", re.IGNORECASE), "tuoi"),
    (re.compile(r"\b(ton giao|religion|faith)\b", re.IGNORECASE), "ton giao"),
    (re.compile(r"\b(dan toc|ethnicity|ethnic)\b", re.IGNORECASE), "dan toc"),
    (re.compile(r"\b(hon nhan|married|marital)\b", re.IGNORECASE), "hon nhan"),
    (re.compile(r"\b(que|quen|hometown|birthplace)\b", re.IGNORECASE), "que quan"),
    (re.compile(r"\b(hinh anh|photo|avatar|image)\b", re.IGNORECASE), "hinh anh"),
]
LEADER_VERBS = ["dan dat", "lanh dao", "sang lap", "found", "established", "built", "created", "founded", "pioneered", "spearheaded", "orchestrated", "championed", "mentored", "coached", "transformed", "dieu phoi", "phoi hop", "mentor", "huan luyen"]
ACTIVE_VERBS = ["phat trien", "develop", "implemented", "improved", "increased", "reduced", "optimized", "streamlined", "designed", "built", "delivered", "achieved", "launched", "managed", "coordinated", "conducted", "analyzed", "created", "giai quyet", "dat duoc", "hoan thanh", "trien khai", "thiet ke", "xay dung", "quan ly", "thuc hien", "toi uu", "tang truong"]
PASSIVE_VERBS = ["duoc giao", "duoc phan cong", "assigned", "participated", "was responsible", "tham gia", "joined", "worked with", "assisted", "helped", "cung voi", "support", "supporting", "aided", "collaborated"]
METRIC_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [r"\d+[%]", r"\$\d+", r"\d+[\.,]\d+[\.,]\d+", r"x\d+", r"\d+[trKMB](?:/|\s)", r"tang\s+\d+", r"giam\s+\d+", r"dat\s+\d+", r"\d+\s*lan"]]
OUTSTANDING_ACHIEVEMENT_KEYWORDS = ["tang truong", "doanh thu", "loi nhuan", "thanh cong", "hoan thanh", "dan dat", "thiet ke", "xay dung", "trien khai", "giai quyet", "dat giai", "top", "best", "winner", "achievement", "exceeded", "performance", "impact", "revenue", "growth", "delivered"]
BREAKTHROUGH_KEYWORDS = ["dot pha", "breakthrough", "record", "ky luc", "revenue boost", "10x", "10 lan", "100%", "thanh lap", "sang lap", "found", "startup", "khoi nghiep", "patent", "bang sang che", "innovation award", "most valuable", "best performer", "champion", "vo dich"]
SKILL_CLUSTERS: Dict[str, List[str]] = {
    "frontend-react": ["react", "reactjs", "nextjs", "next.js", "react native", "redux", "react query", "tanstack query"],
    "frontend-vue": ["vue", "vuejs", "nuxt", "nuxtjs", "vuex", "pinia"],
    "frontend-general": ["html", "css", "sass", "scss", "tailwind", "bootstrap", "tailwindcss", "javascript", "typescript", "jquery"],
    "backend-node": ["node", "nodejs", "express", "expressjs", "nestjs", "nest.js", "koa", "fastify"],
    "backend-python": ["python", "django", "flask", "fastapi", "pyramid"],
    "backend-java": ["java", "spring", "springboot", "spring boot", "spring cloud"],
    "backend-go": ["golang", "go", "go-lang"],
    "backend-dotnet": ["c#", "csharp", ".net", "dotnet", "asp.net", "aspnetcore"],
    "database": ["sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "mariadb", "oracle db", "mssql", "dynamodb", "cassandra", "sqlite", "graphql"],
    "devops": ["docker", "kubernetes", "k8s", "aws", "gcp", "azure", "ci/cd", "jenkins", "gitlab ci", "github actions", "terraform", "ansible", "prometheus", "grafana"],
    "mobile": ["flutter", "react native", "swift", "kotlin", "android", "ios", "xamarin", "ionic"],
    "ai-ml": ["machine learning", "tensorflow", "pytorch", "scikit-learn", "nlp", "computer vision", "deep learning", "data science", "statistics", "r programming", "keras", "pandas", "numpy"],
    "data": ["data analysis", "tableau", "power bi", "excel", "powerbi", "looker", "qlik"],
    "pm": ["scrum", "agile", "kanban", "jira", "project management", "confluence", "asana"],
    "design": ["figma", "sketch", "adobe xd", "photoshop", "illustrator", "ui/ux", "ui design", "ux design", "user research"],
    "security": ["cybersecurity", "penetration testing", "owasp", "iso 27001", "ssl", "oauth", "jwt"],
}
TIER1_GLOBAL = ["google", "meta", "facebook", "apple", "amazon", "microsoft", "netflix", "nvidia", "tesla", "uber", "airbnb", "stripe", "salesforce", "adobe", "oracle", "ibm", "intel", "cisco", "sap", "siemens", "bosch", "philips", "jpmorgan", "goldman sachs", "morgan stanley", "bloomberg", "blackrock", "mckinsey", "bain", "bcg", "pwc", "deloitte", "kpmg", "ey", "accenture", "nike", "cocacola"]
TIER2_GLOBAL = ["shopee", "lazada", "grab", "vng", "garena", "sea group", "vccorp", "misa", "haravan", "bkav", "mobifone", "cmc", "tencent", "alibaba", "bytedance", "ant group", "mastercard", "visa", "paypal", "atlassian", "slack", "zoom", "dropbox", "twilio"]
TIER1_VN = ["fpt", "viettel", "vnpt", "vingroup", "vinfast", "vietinbank", "vietcombank", "bidv", "agribank", "mb bank", "tp bank", "acb", "sacombank", "petrovietnam", "evn", "vnre", "sao do", "mobifone", "vietnammobile"]
TIER2_VN = ["vietnampost", "cuc buu chinh", "cmc", "bkav", "viettel solutions", "vnpt technology", "fpt software", "fpt telecom", "vng", "vccorp", "sendo", "tiki", "haravan", "base", "1975", "gtv", "viec lam 24h", "jobstreet", "mywork", "workbvietnam"]
JD_FIT_CRITERION_LABEL = "Phù hợp JD (Job Fit)"
JD_FIT_CRITERION_ALIASES = [JD_FIT_CRITERION_LABEL, "Phù hợp JD", "Job Fit", "Phu hop JD"]
JD_FIT_MAX_SCORE = 20.0
INDUSTRY_FIT_CRITERION_LABEL = "Phu hop nganh/nghe"
INDUSTRY_FIT_CRITERION_ALIASES = [
    INDUSTRY_FIT_CRITERION_LABEL,
    "Industry Fit",
    "Phu hop nganh nghe",
    "Chuẩn mẫu IT",
    "Chuẩn mẫu SALES",
    "Chuẩn mẫu MARKETING",
    "Chuẩn mẫu DESIGN",
]
INDUSTRY_CLASSIFIER_MAX_SCORE = 3.0
INDUSTRY_VECTOR_MAX_SCORE = 2.0
INDUSTRY_FIT_MAX_SCORE = 5.0
JD_CV_SIMILARITY_FLOOR = 0.45
JD_CV_SIMILARITY_CEILING = 0.90
MAX_EMBEDDING_TEXT_LENGTH = 6000
DETAIL_LIST_ALIASES = [
    "Chi tiet",
    "Chi tiết",
    "Chi tiáº¿t",
    "Chi tiÃ¡ÂºÂ¿t",
    "Chi tiÃƒÂ¡Ã‚ÂºÃ‚Â¿t",
]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _normalize_lookup_key(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _get_record_value(record: Dict[str, Any], aliases: List[str]) -> str:
    alias_set = {_normalize_lookup_key(alias) for alias in aliases}
    for key, value in record.items():
        if value is None or str(value).strip() == "":
            continue
        if _normalize_lookup_key(str(key)) in alias_set:
            return str(value).strip()
    return ""


def _get_analysis_details(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    alias_set = {_normalize_lookup_key(alias) for alias in DETAIL_LIST_ALIASES}
    for key, value in analysis.items():
        if _normalize_lookup_key(str(key)) in alias_set:
            if isinstance(value, list):
                return value
            return []
    return []


def _sync_analysis_detail_aliases(analysis: Dict[str, Any], details: List[Dict[str, Any]]) -> None:
    for alias in DETAIL_LIST_ALIASES:
        analysis[alias] = details


def _parse_numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"[+-]?\d+(?:\.\d+)?", value)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _format_score_value(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _parse_detail_score(value: str) -> tuple[float | None, float | None]:
    ratio_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)", value or "")
    if ratio_match:
        try:
            return float(ratio_match.group(1)), float(ratio_match.group(2))
        except ValueError:
            return None, None
    numeric = _parse_numeric_value(value)
    return numeric, None


def _find_detail_index(details: List[Dict[str, Any]], aliases: List[str]) -> int | None:
    alias_set = {_normalize_lookup_key(alias) for alias in aliases}
    for index, item in enumerate(details):
        if not isinstance(item, dict):
            continue
        criterion = _get_record_value(item, ["Tiêu chí", "Tieu chi", "Criterion"])
        if _normalize_lookup_key(criterion) in alias_set:
            return index
    return None


def _detail_item(title: str, score: str, formula: str, evidence: str, explanation: str) -> Dict[str, str]:
    return {
        "TiÃªu chÃ­": title,
        "TiÃƒÂªu chÃƒÂ­": title,
        "Äiá»ƒm": score,
        "Ã„ÂiÃ¡Â»Æ’m": score,
        "CÃ´ng thá»©c": formula,
        "CÃƒÂ´ng thÃ¡Â»Â©c": formula,
        "Dáº«n chá»©ng": evidence,
        "DÃ¡ÂºÂ«n chÃ¡Â»Â©ng": evidence,
        "Giáº£i thÃ­ch": explanation,
        "GiÃ¡ÂºÂ£i thÃƒÂ­ch": explanation,
    }


def _extract_skills_from_jd(jd_text: str) -> List[str]:
    lower = jd_text.lower()
    return [skill for skill in SKILL_KEYWORDS if skill.lower() in lower]


def _extract_skills_from_candidate(candidate: Dict[str, Any]) -> List[str]:
    analysis = candidate.get("analysis") or {}
    details = _get_analysis_details(analysis)
    strengths = analysis.get("Äiá»ƒm máº¡nh CV") or analysis.get("Ã„ÂiÃ¡Â»Æ’m mÃ¡ÂºÂ¡nh CV") or []
    texts = [
        candidate.get("jobTitle", ""),
        candidate.get("industry", ""),
        candidate.get("department", ""),
        *[str(item.get("Dáº«n chá»©ng") or item.get("DÃ¡ÂºÂ«n chÃ¡Â»Â©ng") or "") for item in details if isinstance(item, dict)],
        *[str(item) for item in strengths],
    ]
    combined = " ".join(texts).lower()
    return [skill for skill in SKILL_KEYWORDS if skill.lower() in combined]


def _extract_companies_from_candidate(candidate: Dict[str, Any]) -> List[str]:
    analysis = candidate.get("analysis") or {}
    details = _get_analysis_details(analysis)
    strengths = analysis.get("Äiá»ƒm máº¡nh CV") or analysis.get("Ã„ÂiÃ¡Â»Æ’m mÃ¡ÂºÂ¡nh CV") or []
    evidence = " ".join([
        str(candidate.get("jobTitle", "")),
        str(candidate.get("industry", "")),
        str(candidate.get("department", "")),
        *[str(item.get("Dáº«n chá»©ng") or item.get("DÃ¡ÂºÂ«n chÃ¡Â»Â©ng") or "") for item in details if isinstance(item, dict)],
        *[str(item) for item in strengths],
    ]).lower()
    return [name for name in COMPANY_NAME_WORDS if name in evidence]


def _contains_lookup_term(text: str, term: str) -> bool:
    normalized_text = f" {_normalize_lookup_key(text)} "
    normalized_term = _normalize_lookup_key(term)
    return bool(normalized_term and f" {normalized_term} " in normalized_text)


def _split_evidence_sentences(text: str) -> List[str]:
    return [
        sentence.strip()[:280]
        for sentence in re.split(r"(?<=[.!?])\s+|\n+|[;•]", text or "")
        if len(sentence.strip()) >= 8
    ][:80]


def _find_best_evidence_sentence(text: str, terms: List[str]) -> str:
    sentences = _split_evidence_sentences(text)
    if not sentences:
        return ""

    normalized_terms = [_normalize_lookup_key(term) for term in terms if _normalize_lookup_key(term)]
    if not normalized_terms:
        return sentences[0]

    ranked: List[Tuple[float, str]] = []
    for sentence in sentences:
        normalized_sentence = f" {_normalize_lookup_key(sentence)} "
        score = 0.0
        for normalized_term in normalized_terms:
            if f" {normalized_term} " in normalized_sentence or normalized_term in normalized_sentence:
                score += max(1.0, len(normalized_term) / 10)
        if score > 0:
            ranked.append((score, sentence))

    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _build_candidate_evidence_corpus(candidate: Dict[str, Any], cv_text: str = "") -> str:
    analysis = candidate.get("analysis") or {}
    details = _get_analysis_details(analysis)
    strengths = analysis.get("Ã„ÂiÃ¡Â»Æ’m mÃ¡ÂºÂ¡nh CV") or analysis.get("Ãƒâ€žÃ‚ÂiÃƒÂ¡Ã‚Â»Ã†â€™m mÃƒÂ¡Ã‚ÂºÃ‚Â¡nh CV") or []
    texts = [
        cv_text,
        candidate.get("jobTitle", ""),
        candidate.get("industry", ""),
        candidate.get("department", ""),
        *[str(item.get("DÃ¡ÂºÂ«n chÃ¡Â»Â©ng") or item.get("DÃƒÂ¡Ã‚ÂºÃ‚Â«n chÃƒÂ¡Ã‚Â»Ã‚Â©ng") or "") for item in details if isinstance(item, dict)],
        *[str(item) for item in strengths],
    ]
    return " ".join(str(text or "") for text in texts if str(text or "").strip())


def _extract_skills_from_jd(jd_text: str, role_profile: Dict[str, Any] | None = None) -> List[str]:
    if role_profile and not is_generic_role(role_profile):
        extracted: List[str] = []
        for requirement in get_role_requirements(role_profile):
            requirement_terms = [
                *list(requirement.get("terms") or []),
                *list(requirement.get("equivalentTerms") or []),
                *list(requirement.get("evidenceTerms") or []),
            ]
            if any(_contains_lookup_term(jd_text, term) for term in requirement_terms):
                extracted.append(str(requirement.get("label") or ""))
        core_requirements = [str(item.get("label") or "") for item in role_profile.get("coreRequirements") or []]
        if extracted:
            return list(dict.fromkeys([item for item in extracted if item]))
        return list(dict.fromkeys([item for item in core_requirements if item]))

    lower = jd_text.lower()
    return [skill for skill in SKILL_KEYWORDS if skill.lower() in lower]


def _extract_skills_from_candidate(
    candidate: Dict[str, Any],
    cv_text: str = "",
    role_profile: Dict[str, Any] | None = None,
) -> List[str]:
    combined = _build_candidate_evidence_corpus(candidate, cv_text).lower()
    if role_profile and not is_generic_role(role_profile):
        extracted: List[str] = []
        for requirement in get_role_requirements(role_profile):
            requirement_terms = [
                *list(requirement.get("terms") or []),
                *list(requirement.get("equivalentTerms") or []),
                *list(requirement.get("evidenceTerms") or []),
            ]
            if any(_contains_lookup_term(combined, term) for term in requirement_terms):
                extracted.append(str(requirement.get("label") or ""))
        return list(dict.fromkeys([item for item in extracted if item]))

    return [skill for skill in SKILL_KEYWORDS if skill.lower() in combined]


def _check_bias_risk(filters: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    age = filters.get("age") or {}
    if isinstance(age, dict) and (age.get("min") is not None or age.get("max") is not None):
        warnings.append(f"Canh bao: Bo loc tuoi ({age.get('min', '?')}â€“{age.get('max', '?')}) co the vi pham Dieu 8 BLLD 2019.")
    if filters.get("gender"):
        warnings.append("Canh bao: Bo loc gioi tinh co the vi pham luat Binh dang lao dong Viet Nam.")
    if filters.get("ethnicity"):
        warnings.append("Canh bao: Bo loc dan toc co the vi pham Dieu 8 BLLD 2019.")
    if filters.get("religion"):
        warnings.append("Canh bao: Bo loc ton giao co the vi pham quyen tu do tin nguong.")
    if filters.get("maritalStatus"):
        warnings.append("Canh bao: Bo loc tinh trang hon nhan co the vi pham Dieu 36 BLLD 2019.")
    if warnings:
        warnings.extend([
            "Dieu 8 BLLD 2019 â€” Nghiem cam phan biet doi xu tren co so gioi tinh, tuoi tac, ton giao, dan toc.",
            "Dieu 36 BLLD 2019 â€” Khong duoc yeu cau xac nhan tinh trang hon nhan khi tuyen dung.",
        ])
    return warnings


def _run_debiasing(cv_text: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    warnings = _check_bias_risk(filters)
    blinded_fields: List[str] = []
    removed: List[str] = []
    for pattern, label in BIAS_PATTERNS:
        matches = pattern.findall(cv_text)
        if matches:
            blinded_fields.append(label)
            if isinstance(matches[0], tuple):
                removed.extend([match[0] for match in matches])
            else:
                removed.extend(matches)
    return {
        "overall_safe": len(warnings) == 0,
        "warnings": warnings,
        "blinded_fields": list(dict.fromkeys(blinded_fields)),
        "removed_patterns": removed,
    }


def _tokenize(text: str) -> List[str]:
    return [token for token in re.sub(r"[^\w\s-]", " ", text.lower()).split() if len(token) > 2]


def _contains_any(text: str, words: List[str]) -> List[str]:
    tokens = _tokenize(text)
    return [word for word in words if any(word.lower() in token for token in tokens)]


def _analyze_soft_skills(cv_text: str) -> Dict[str, Dict[str, Any]]:
    return {}


def _infer_level(title: str) -> int:
    lower = title.lower()
    if re.search(r"director|vp|vice president|cto|ceo|cfo", lower):
        return 6
    if re.search(r"manager|giam doc|truong phong|head", lower):
        return 5
    if re.search(r"lead|team lead|truong nhom", lower):
        return 4
    if re.search(r"senior|sr\.|chuyen gia|expert|cao cap", lower):
        return 3
    if re.search(r"intern|fresher|thuc tap", lower):
        return 0
    return 2


def _analyze_career_velocity(experience_text: str) -> Dict[str, Any]:
    milestones = []
    current_title = ""
    current_level = 2
    current_company = ""
    current_year = 2026
    for line in [line for line in re.split(r"\n|\r", experience_text) if len(line.strip()) > 5]:
        title_match = re.search(r"(?:chá»©c danh|vá»‹ trÃ­|position|role|title)[:\s]*(.+)", line, re.IGNORECASE)
        company_match = re.search(r"(?:cÃ´ng ty|company|doanh nghiá»‡p|táº¡i)[:\s]*(.+)", line, re.IGNORECASE)
        year_match = re.findall(r"(?:20\d{2}|19\d{2})(?:\s*[-â€“]\s*(?:20\d{2}|19\d{2}|nay|hiá»‡n táº¡i|present))?", line, re.IGNORECASE)
        if title_match:
            current_title = title_match.group(1).strip()
            current_level = _infer_level(current_title)
        if company_match:
            current_company = company_match.group(1).strip()
        if year_match:
            years = re.findall(r"\d{4}", " ".join(year_match))
            if years:
                start_year = int(years[0])
                end_year = int(years[1]) if len(years) > 1 else current_year
                months = max(0, (end_year - start_year) * 12)
                is_promotion = len(milestones) > 0 and current_level > milestones[-1]["level"]
                milestones.append({"title": current_title or "Khong ro chuc danh", "level": current_level, "company": current_company, "durationMonths": months, "isPromotion": is_promotion})
                current_title = ""
                current_company = ""
    if not milestones:
        return {"peakLevel": 0, "peakTitle": "Khong ro", "totalMonths": 0, "promotionMonths": 0, "promotionCount": 0, "avgMonthsPerLevel": 0, "potentialScore": 0, "velocityTag": "normal"}
    peak = max(milestones, key=lambda item: item["level"])
    total_months = sum(item["durationMonths"] for item in milestones)
    promotion_months = sum(item["durationMonths"] for item in milestones if item["isPromotion"])
    promotion_count = sum(1 for item in milestones if item["isPromotion"])
    avg_months = round((promotion_months / promotion_count) if promotion_count > 0 else total_months)
    if avg_months <= 18:
        potential_score, tag = 18, "fast"
    elif avg_months <= 36:
        potential_score, tag = 12, "normal"
    else:
        potential_score, tag = 6, "slow"
    if peak["level"] >= 4:
        potential_score = min(20, potential_score + 2)
    if promotion_count >= 3:
        potential_score = min(20, potential_score + 2)
    return {"peakLevel": peak["level"], "peakTitle": peak["title"], "totalMonths": total_months, "promotionMonths": promotion_months, "promotionCount": promotion_count, "avgMonthsPerLevel": avg_months, "potentialScore": potential_score, "velocityTag": tag}


def _score_skill_match_legacy(jd_skills: List[str], candidate_skills: List[str]) -> Dict[str, Any]:
    cand_set = {skill.lower() for skill in candidate_skills}
    matched: List[str] = []
    unmatched: List[str] = []
    transfer_matches: List[str] = []
    clusters: List[str] = []
    for jd_skill in jd_skills:
        jd_lower = jd_skill.lower()
        if jd_lower in cand_set:
            matched.append(jd_skill)
            continue
        cluster_entry = next(((cluster_key, members) for cluster_key, members in SKILL_CLUSTERS.items() if any(member in jd_lower or jd_lower in member for member in members)), None)
        if cluster_entry:
            cluster_key, members = cluster_entry
            member_set = {member.lower() for member in members}
            found = next((skill for skill in candidate_skills if skill.lower() in member_set), None)
            if found:
                transfer_matches.append(f"{jd_skill} -> {found} ({cluster_key})")
                matched.append(jd_skill)
                clusters.append(cluster_key)
            else:
                unmatched.append(jd_skill)
        else:
            unmatched.append(jd_skill)
    total = len(jd_skills) or 1
    match_rate = round(((len(matched) + len(transfer_matches)) / total) * 100)
    return {
        "matchedSkills": matched,
        "unmatchedSkills": unmatched,
        "transferMatches": transfer_matches,
        "familyClusters": list(dict.fromkeys(clusters)),
        "matchRate": match_rate,
    }


def _score_generic_skill_match(jd_skills: List[str], candidate_skills: List[str]) -> Dict[str, Any]:
    base = _score_skill_match_legacy(jd_skills, candidate_skills)
    base["matchedRequirements"] = list(base.get("matchedSkills") or [])
    base["missingRequirements"] = list(base.get("unmatchedSkills") or [])
    base["evidenceMatches"] = []
    base["roleWeightedScore"] = 0.0
    base["uiSections"] = ["General fit"]
    return base


def _score_skill_match(
    jd_skills: List[str],
    candidate_skills: List[str],
    *,
    role_profile: Dict[str, Any] | None = None,
    jd_text: str = "",
    cv_text: str = "",
    candidate: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if not role_profile or is_generic_role(role_profile):
        return _score_generic_skill_match(jd_skills, candidate_skills)

    candidate_payload = candidate or {}
    evidence_corpus = _build_candidate_evidence_corpus(candidate_payload, cv_text)
    requirements = get_role_requirements(role_profile)
    matched: List[str] = []
    unmatched: List[str] = []
    transfer_matches: List[str] = []
    family_clusters: List[str] = []
    evidence_matches: List[Dict[str, Any]] = []
    total_weight = 0.0
    earned_weight = 0.0

    for requirement in requirements:
        requirement_label = str(requirement.get("label") or "").strip()
        if not requirement_label:
            continue

        if jd_skills and requirement_label not in jd_skills:
            continue

        weight = float(requirement.get("weight") or 1.0)
        total_weight += weight
        section = str(requirement.get("section") or "General fit")
        family_clusters.append(section)
        terms = [*list(requirement.get("terms") or []), *list(requirement.get("evidenceTerms") or [])]
        equivalent_terms = list(requirement.get("equivalentTerms") or [])
        jd_terms = [requirement_label, *terms, *equivalent_terms]
        jd_evidence = _find_best_evidence_sentence(jd_text, jd_terms) or f"JD co yeu cau lien quan den {requirement_label}."

        exact_term = next((term for term in terms if _contains_lookup_term(evidence_corpus, term)), "")
        transfer_term = next((term for term in equivalent_terms if _contains_lookup_term(evidence_corpus, term)), "")
        cv_terms = [value for value in [exact_term, transfer_term, requirement_label, *terms, *equivalent_terms] if value]
        cv_evidence = _find_best_evidence_sentence(evidence_corpus, cv_terms)

        if exact_term and cv_evidence:
            matched.append(requirement_label)
            earned_weight += weight
            evidence_matches.append(
                {
                    "section": section,
                    "requirement": requirement_label,
                    "jdEvidence": jd_evidence,
                    "cvEvidence": cv_evidence,
                    "matchType": "exact",
                    "score": 0.94,
                    "reason": f"CV co bang chung truc tiep cho nhom nang luc {requirement_label}.",
                }
            )
        elif transfer_term and cv_evidence:
            matched.append(requirement_label)
            transfer_matches.append(f"{requirement_label} -> {transfer_term}")
            earned_weight += weight * 0.75
            evidence_matches.append(
                {
                    "section": section,
                    "requirement": requirement_label,
                    "jdEvidence": jd_evidence,
                    "cvEvidence": cv_evidence,
                    "matchType": "transfer",
                    "score": 0.78,
                    "reason": f"CV co nang luc tuong duong cho nhom {requirement_label}, nhung cach dien dat khong trung hoan toan voi JD.",
                }
            )
        else:
            unmatched.append(requirement_label)
            evidence_matches.append(
                {
                    "section": section,
                    "requirement": requirement_label,
                    "jdEvidence": jd_evidence,
                    "cvEvidence": f"Khong tim thay bang chung ro rang cho {requirement_label} trong CV da trich xuat.",
                    "matchType": "incorrect",
                    "score": 0.0,
                    "reason": f"Nhom nang luc {requirement_label} chua co bang chung du ro trong CV.",
                }
            )

    if total_weight <= 0:
        return _score_generic_skill_match(jd_skills, candidate_skills)

    role_weighted_score = round((earned_weight / total_weight) * JD_FIT_MAX_SCORE, 1)
    match_rate = round((earned_weight / total_weight) * 100)
    return {
        "matchedSkills": list(dict.fromkeys(matched)),
        "unmatchedSkills": list(dict.fromkeys(unmatched)),
        "transferMatches": list(dict.fromkeys(transfer_matches)),
        "familyClusters": list(dict.fromkeys(family_clusters)),
        "matchRate": match_rate,
        "matchedRequirements": list(dict.fromkeys(matched)),
        "missingRequirements": list(dict.fromkeys(unmatched)),
        "evidenceMatches": evidence_matches,
        "roleWeightedScore": role_weighted_score,
        "uiSections": list(role_profile.get("uiSections") or ["General fit"]),
    }


def _apply_company_tier_multiplier(base_score: float, companies: List[str]) -> Dict[str, Any]:
    if not companies:
        return {"adjustedScore": base_score, "multipliers": {}, "reasoning": "Khong nhan dien duoc cong ty nao trong CV.", "recognizedCompanies": []}
    multipliers: Dict[str, float] = {}
    recognized: List[str] = []
    avg_multiplier = 1.0
    for company in companies:
        lower = company.lower()
        multiplier = 1.0
        if any(name in lower for name in TIER1_GLOBAL + TIER1_VN):
            multiplier = 1.15
            recognized.append(company)
        elif any(name in lower for name in TIER2_GLOBAL + TIER2_VN):
            multiplier = 1.10
            recognized.append(company)
        multipliers[company] = multiplier
        avg_multiplier += multiplier - 1
    avg_multiplier = avg_multiplier / len(companies) + 1
    adjusted = min(100, round(base_score * avg_multiplier, 1))
    return {"adjustedScore": adjusted, "multipliers": multipliers, "reasoning": f"Nhan dien {len(recognized)} cong ty uy tin. He so x{avg_multiplier:.2f} -> +{adjusted - base_score:.1f} diem.", "recognizedCompanies": recognized}


def _detect_boost_level(score: float, evidence: str) -> Optional[str]:
    lower = evidence.lower()
    if score >= 85 or any(keyword in lower for keyword in BREAKTHROUGH_KEYWORDS):
        return "breakthrough"
    if score >= 75 or any(keyword in lower for keyword in OUTSTANDING_ACHIEVEMENT_KEYWORDS):
        return "outstanding"
    return None


def _apply_dynamic_boost(criteria_scores: Dict[str, float], criteria_evidence: Dict[str, str]) -> List[Dict[str, Any]]:
    boost_signals: List[Dict[str, Any]] = []
    for criterion, score in criteria_scores.items():
        boost_type = _detect_boost_level(score, criteria_evidence.get(criterion, ""))
        if not boost_type:
            continue
        deficits = sorted([(key, value) for key, value in criteria_scores.items() if key != criterion and value < 90], key=lambda item: item[1])[:3]
        multiplier = {"outstanding": 1.5, "exceptional": 2.0, "breakthrough": 2.5}[boost_type]
        for target, target_score in deficits:
            deficit = 90 - target_score
            if deficit <= 0 or score < 75:
                continue
            boost = max(0, min(min(score - 75, deficit) * (multiplier - 1) * 0.1, 90 - score))
            if boost > 0:
                boost_signals.append({
                    "type": boost_type,
                    "sourceCriterion": criterion,
                    "boostedCriteria": [target],
                    "boostAmount": boost,
                    "reason": f"Thanh tich noi bat tai '{criterion}' bu dap thieu sot tai '{target}'",
                })
    return boost_signals


def _contains_keyword(value: str, keywords: List[str]) -> bool:
    lower = value.lower()
    return any(keyword in lower for keyword in keywords)


def _prepare_embedding_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())[:MAX_EMBEDDING_TEXT_LENGTH]


def _cosine_similarity(a: List[float], b: List[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def _semantic_similarity_to_job_fit_score(similarity: float) -> float:
    if similarity <= JD_CV_SIMILARITY_FLOOR:
        return 0.0
    span = JD_CV_SIMILARITY_CEILING - JD_CV_SIMILARITY_FLOOR
    scaled = (similarity - JD_CV_SIMILARITY_FLOOR) / span if span > 0 else similarity
    return round(max(0.0, min(JD_FIT_MAX_SCORE, scaled * JD_FIT_MAX_SCORE)), 1)


def _detect_industry(candidate: Dict[str, Any], hard_filters: Dict[str, Any]) -> Optional[str]:
    values = [
        str(candidate.get("industry", "")),
        str(candidate.get("department", "")),
        str(candidate.get("jobTitle", "")),
        str(hard_filters.get("industry", "")),
    ]
    joined = " ".join(values).lower()
    if _contains_keyword(joined, IT_KEYWORDS):
        return "it"
    if _contains_keyword(joined, SALES_KEYWORDS):
        return "sales"
    if _contains_keyword(joined, MARKETING_KEYWORDS):
        return "marketing"
    if _contains_keyword(joined, DESIGN_KEYWORDS):
        return "design"
    return None


def _compute_industry_similarity(
    industry: str,
    cv_text: str,
    owner_uid: str | None = None,
    file_name: str | None = None,
    query_vector: List[float] | None = None,
) -> Optional[Dict[str, Any]]:
    result = search_similar_records(
        industry,
        cv_text,
        top_k=3,
        min_similarity=0.0,
        owner_uid=owner_uid,
        exclude_file_names=[file_name] if file_name else None,
        query_vector=query_vector,
    )
    if not result:
        return None
    return {
        "industry": industry,
        "provider": result.get("provider"),
        "collectionKey": result.get("collectionKey"),
        "queryModel": result.get("queryModel"),
        "recordCount": result.get("recordCount"),
        "averageSimilarity": result.get("averageSimilarity"),
        "topMatches": result.get("topMatches"),
        "bonusPoints": result.get("bonusPoints"),
    }


def _pipeline_metadata(candidate: Dict[str, Any]) -> Dict[str, Any]:
    metadata = candidate.get("pipelineMetadata")
    return metadata if isinstance(metadata, dict) else {}


def _normalized_collection_keys(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    keys: List[str] = []
    for value in values:
        normalized = _normalize_lookup_key(str(value))
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _resolve_target_industry(candidate: Dict[str, Any], hard_filters: Dict[str, Any]) -> Tuple[str | None, str]:
    detected = _detect_industry(candidate, hard_filters)
    if detected:
        return detected, "candidate_or_filter"

    collection_keys = _normalized_collection_keys(_pipeline_metadata(candidate).get("collectionKeys"))
    if collection_keys:
        return collection_keys[0], "classifier_inferred"

    return None, "unknown"


def _classifier_signal_for_industry(
    candidate: Dict[str, Any],
    target_industry: str,
    target_source: str,
) -> Dict[str, Any]:
    metadata = _pipeline_metadata(candidate)
    classifier = metadata.get("classifier") if isinstance(metadata.get("classifier"), dict) else {}
    collection_keys = _normalized_collection_keys(metadata.get("collectionKeys"))
    confidence = float(_parse_numeric_value(classifier.get("confidence")) or 0.0)
    top_predictions = classifier.get("top_predictions") if isinstance(classifier.get("top_predictions"), list) else []
    prediction_summary = [
        f"{str(item.get('label') or '').strip()}:{float(item.get('score') or 0.0):.2f}"
        for item in top_predictions[:3]
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    ]
    matched = bool(target_industry and target_industry in collection_keys)

    if target_source == "classifier_inferred":
        score = round(min(1.5, 0.5 + confidence), 1) if collection_keys else 0.0
    elif matched:
        if confidence >= 0.85:
            score = 3.0
        elif confidence >= 0.75:
            score = 2.5
        elif confidence >= 0.60:
            score = 2.0
        else:
            score = 1.0
    elif collection_keys:
        score = 0.5 if confidence < 0.60 else 0.0
    else:
        score = 0.0

    return {
        "score": round(min(INDUSTRY_CLASSIFIER_MAX_SCORE, max(0.0, score)), 1),
        "matched": matched,
        "confidence": confidence,
        "collectionKeys": collection_keys,
        "predictionSummary": prediction_summary,
        "modelSource": str(classifier.get("model_source") or metadata.get("classifierSource") or "").strip(),
    }


def _compute_industry_fit(
    candidate: Dict[str, Any],
    hard_filters: Dict[str, Any],
    cv_text: str,
    *,
    owner_uid: str | None,
    query_vector: List[float] | None,
) -> Optional[Dict[str, Any]]:
    target_industry, target_source = _resolve_target_industry(candidate, hard_filters)
    if not target_industry:
        return None

    classifier_signal = _classifier_signal_for_industry(candidate, target_industry, target_source)
    vector_insight = _compute_industry_similarity(
        target_industry,
        cv_text,
        owner_uid=owner_uid,
        file_name=str(candidate.get("fileName") or ""),
        query_vector=query_vector,
    )
    vector_bonus = float(vector_insight.get("bonusPoints") or 0.0) if vector_insight else 0.0
    vector_score = round(min(INDUSTRY_VECTOR_MAX_SCORE, (vector_bonus / 5.0) * INDUSTRY_VECTOR_MAX_SCORE), 1)
    final_score = round(min(INDUSTRY_FIT_MAX_SCORE, classifier_signal["score"] + vector_score), 1)

    evidence_parts: List[str] = [f"Nganh muc tieu: {target_industry.upper()}"]
    if classifier_signal["predictionSummary"]:
        evidence_parts.append(f"Classifier: {', '.join(classifier_signal['predictionSummary'])}")
    if vector_insight and vector_insight.get("topMatches"):
        evidence_parts.append(
            "Vector matches: "
            + "; ".join(
                f"{item.get('name') or item.get('role') or item.get('id')} {float(item.get('similarity') or 0.0) * 100:.1f}%"
                for item in list(vector_insight.get("topMatches") or [])[:3]
                if isinstance(item, dict)
            )
        )
    evidence = " | ".join(part for part in evidence_parts if part)

    if target_source == "classifier_inferred":
        explanation = (
            "Khong thay du manh dau hieu nganh o phan cau hinh vao, nen he thong tam suy ra "
            "nganh muc tieu tu classifier roi doi chieu them voi vector similarity."
        )
    elif classifier_signal["matched"]:
        explanation = (
            f"Classifier va vector similarity deu nghieng ve nhom {target_industry.upper()}, "
            "vi vay CV duoc cong diem phu hop nganh/nghe."
        )
    else:
        explanation = (
            f"Classifier chua xac nhan ro nhom {target_industry.upper()} nen diem phu hop nganh/nghe bi gioi han."
        )

    return {
        "targetIndustry": target_industry,
        "targetSource": target_source,
        "classifierScore": classifier_signal["score"],
        "classifierMatched": classifier_signal["matched"],
        "classifierConfidence": classifier_signal["confidence"],
        "classifierCollectionKeys": classifier_signal["collectionKeys"],
        "classifierPredictionSummary": classifier_signal["predictionSummary"],
        "classifierModelSource": classifier_signal["modelSource"],
        "vectorScore": vector_score,
        "vectorInsight": vector_insight,
        "finalScore": final_score,
        "maxScore": INDUSTRY_FIT_MAX_SCORE,
        "formula": (
            f"Classifier {_format_score_value(classifier_signal['score'])}/{_format_score_value(INDUSTRY_CLASSIFIER_MAX_SCORE)} + "
            f"Vector {_format_score_value(vector_score)}/{_format_score_value(INDUSTRY_VECTOR_MAX_SCORE)} = "
            f"{_format_score_value(final_score)}/{_format_score_value(INDUSTRY_FIT_MAX_SCORE)}"
        ),
        "evidence": evidence,
        "explanation": explanation,
    }


def _upsert_industry_fit_detail(
    details: List[Dict[str, Any]],
    *,
    analysis: Dict[str, Any],
    candidate: Dict[str, Any],
    hard_filters: Dict[str, Any],
    cv_text: str,
    owner_uid: str | None,
    query_vector: List[float] | None,
) -> None:
    detail_index = _find_detail_index(details, INDUSTRY_FIT_CRITERION_ALIASES)
    previous_score = 0.0
    if detail_index is not None:
        score_text = _get_record_value(details[detail_index], ["Äiá»ƒm", "Diem", "Score"])
        previous_score = _parse_detail_score(score_text)[0] or 0.0

    fit_payload = _compute_industry_fit(
        candidate,
        hard_filters,
        cv_text,
        owner_uid=owner_uid,
        query_vector=query_vector,
    )
    if not fit_payload:
        return

    candidate["industryFitInsights"] = fit_payload
    vector_insight = fit_payload.get("vectorInsight") if isinstance(fit_payload.get("vectorInsight"), dict) else None
    if vector_insight:
        candidate["embeddingInsights"] = vector_insight

    detail_payload = _detail_item(
        INDUSTRY_FIT_CRITERION_LABEL,
        f"{_format_score_value(float(fit_payload['finalScore']))}/{_format_score_value(INDUSTRY_FIT_MAX_SCORE)}",
        str(fit_payload["formula"]),
        str(fit_payload["evidence"]),
        str(fit_payload["explanation"]),
    )
    if detail_index is None:
        details.insert(1 if details else 0, detail_payload)
    else:
        details[detail_index] = detail_payload

    current_total = (
        _parse_numeric_value(analysis.get("Tá»•ng Ä‘iá»ƒm"))
        or _parse_numeric_value(analysis.get("Tong diem"))
        or _parse_numeric_value(analysis.get("TÃƒÂ¡Ã‚Â»Ã¢â‚¬Â¢ng Ãƒâ€žÃ¢â‚¬ËœiÃƒÂ¡Ã‚Â»Ã†â€™m"))
        or _parse_numeric_value(analysis.get("TÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ng ÃƒÆ’Ã¢â‚¬Å¾ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“iÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€ Ã¢â‚¬â„¢m"))
    )
    if current_total is not None:
        updated_total = max(0.0, min(100.0, current_total + (float(fit_payload["finalScore"]) - previous_score)))
        analysis["Tá»•ng Ä‘iá»ƒm"] = round(updated_total, 1)
        analysis["Tong diem"] = round(updated_total, 1)
        analysis["TÃƒÂ¡Ã‚Â»Ã¢â‚¬Â¢ng Ãƒâ€žÃ¢â‚¬ËœiÃƒÂ¡Ã‚Â»Ã†â€™m"] = analysis["Tá»•ng Ä‘iá»ƒm"]
        analysis["TÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ng ÃƒÆ’Ã¢â‚¬Å¾ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“iÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€ Ã¢â‚¬â„¢m"] = analysis["Tá»•ng Ä‘iá»ƒm"]


def _compute_jd_cv_embedding_match(
    jd_text: str,
    cv_text: str,
    *,
    jd_vector: List[float] | None = None,
    cv_vector: List[float] | None = None,
) -> Dict[str, Any] | None:
    cleaned_jd = _prepare_embedding_text(jd_text)
    cleaned_cv = _prepare_embedding_text(cv_text)
    if not cleaned_jd or not cleaned_cv:
        return None

    settings = get_settings()
    try:
        resolved_jd_vector = jd_vector or embed_text(cleaned_jd, settings.gemini_embedding_model)
        resolved_cv_vector = cv_vector or embed_text(cleaned_cv, settings.gemini_embedding_model)
    except Exception:
        return None

    similarity = _cosine_similarity(resolved_jd_vector, resolved_cv_vector)
    if similarity is None:
        return None

    return {
        "similarity": similarity,
        "weightedScore": _semantic_similarity_to_job_fit_score(similarity),
        "maxScore": JD_FIT_MAX_SCORE,
        "queryModel": settings.gemini_embedding_model,
    }


def _upsert_jd_fit_detail(
    details: List[Dict[str, Any]],
    *,
    analysis: Dict[str, Any],
    candidate: Dict[str, Any],
    jd_text: str,
    semantic_match: Dict[str, Any] | None,
) -> None:
    detail_index = _find_detail_index(details, JD_FIT_CRITERION_ALIASES)
    previous_score = 0.0
    if detail_index is not None:
        score_text = _get_record_value(details[detail_index], ["Điểm", "Diem", "Score"])
        previous_score = _parse_detail_score(score_text)[0] or 0.0

    jd_skills = _extract_skills_from_jd(jd_text)
    candidate_skills = _extract_skills_from_candidate(candidate)
    skill_match = _score_skill_match(jd_skills, candidate_skills) if jd_skills else {
        "matchedSkills": [],
        "unmatchedSkills": [],
        "transferMatches": [],
        "familyClusters": [],
        "matchRate": 0,
    }

    vector_score = float(semantic_match.get("weightedScore") or 0.0) if semantic_match else 0.0
    final_score = min(JD_FIT_MAX_SCORE, max(previous_score, vector_score))

    evidence_parts: List[str] = []
    if skill_match["matchedSkills"]:
        evidence_parts.append(f"Kỹ năng khớp: {', '.join(skill_match['matchedSkills'][:6])}")
    if skill_match["transferMatches"]:
        evidence_parts.append(f"Khớp chuyển đổi: {'; '.join(skill_match['transferMatches'][:3])}")
    if skill_match["unmatchedSkills"]:
        evidence_parts.append(f"Còn thiếu: {', '.join(skill_match['unmatchedSkills'][:4])}")
    if semantic_match:
        evidence_parts.append(
            f"Embedding JD/CV {semantic_match['similarity'] * 100:.1f}% ({semantic_match['queryModel']})"
        )
    evidence = " | ".join(evidence_parts) or "Chưa có đủ dữ liệu để suy ra phần so khớp JD/CV."

    if semantic_match:
        explanation = (
            f"So khớp JD/CV lấy mức cao hơn giữa điểm AI gốc "
            f"{_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)} và "
            f"điểm semantic embedding {_format_score_value(vector_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}."
        )
        formula = (
            f"max(AI Job Fit {_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}, "
            f"Vector semantic {_format_score_value(vector_score)}/{_format_score_value(JD_FIT_MAX_SCORE)})"
        )
        candidate["jdCvMatchInsights"] = {
            "similarity": semantic_match["similarity"],
            "weightedScore": vector_score,
            "maxScore": JD_FIT_MAX_SCORE,
            "queryModel": semantic_match["queryModel"],
            "matchedSkills": skill_match["matchedSkills"],
            "missingSkills": skill_match["unmatchedSkills"],
            "transferMatches": skill_match["transferMatches"],
        }
    else:
        explanation = "Giữ lại điểm Job Fit hiện có vì chưa tạo được semantic embedding ổn định cho JD/CV."
        formula = f"AI Job Fit {_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}"

    detail_payload = _detail_item(
        JD_FIT_CRITERION_LABEL,
        f"{_format_score_value(final_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}",
        formula,
        evidence,
        explanation,
    )
    if detail_index is None:
        details.insert(0, detail_payload)
    else:
        details[detail_index] = detail_payload

    current_total = (
        _parse_numeric_value(analysis.get("Tổng điểm"))
        or _parse_numeric_value(analysis.get("Tong diem"))
        or _parse_numeric_value(analysis.get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m"))
        or _parse_numeric_value(analysis.get("TÃƒÂ¡Ã‚Â»Ã¢â‚¬Â¢ng Ãƒâ€žÃ¢â‚¬ËœiÃƒÂ¡Ã‚Â»Ã†â€™m"))
    )
    if current_total is not None:
        updated_total = max(0.0, min(100.0, current_total + (final_score - previous_score)))
        analysis["Tổng điểm"] = round(updated_total, 1)
        analysis["Tong diem"] = round(updated_total, 1)
        analysis["TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m"] = analysis["Tổng điểm"]
        analysis["TÃƒÂ¡Ã‚Â»Ã¢â‚¬Â¢ng Ãƒâ€žÃ¢â‚¬ËœiÃƒÂ¡Ã‚Â»Ã†â€™m"] = analysis["Tổng điểm"]


def _upsert_jd_fit_detail(
    details: List[Dict[str, Any]],
    *,
    analysis: Dict[str, Any],
    candidate: Dict[str, Any],
    jd_text: str,
    cv_text: str,
    hard_filters: Dict[str, Any],
    semantic_match: Dict[str, Any] | None,
) -> None:
    detail_index = _find_detail_index(details, JD_FIT_CRITERION_ALIASES)
    previous_score = 0.0
    if detail_index is not None:
        score_text = _get_record_value(details[detail_index], ["Äiá»ƒm", "Diem", "Score"])
        previous_score = _parse_detail_score(score_text)[0] or 0.0

    role_profile = resolve_role_profile(
        jd_text=jd_text,
        job_position=str(hard_filters.get("jobTitle") or hard_filters.get("position") or ""),
        hard_filters=hard_filters,
        industry_hint=str(candidate.get("industry") or hard_filters.get("industry") or ""),
        candidate_job_title=str(candidate.get("jobTitle") or ""),
    )
    jd_skills = _extract_skills_from_jd(jd_text, role_profile)
    candidate_skills = _extract_skills_from_candidate(candidate, cv_text, role_profile)
    skill_match = _score_skill_match(
        jd_skills,
        candidate_skills,
        role_profile=role_profile,
        jd_text=jd_text,
        cv_text=cv_text,
        candidate=candidate,
    ) if jd_skills else {
        "matchedSkills": [],
        "unmatchedSkills": [],
        "transferMatches": [],
        "familyClusters": [],
        "matchRate": 0,
        "matchedRequirements": [],
        "missingRequirements": [],
        "evidenceMatches": [],
        "roleWeightedScore": 0.0,
        "uiSections": list(role_profile.get("uiSections") or ["General fit"]),
    }

    vector_score = float(semantic_match.get("weightedScore") or 0.0) if semantic_match else 0.0
    role_score = float(skill_match.get("roleWeightedScore") or 0.0)
    if role_profile and not is_generic_role(role_profile):
        blended_score = role_score if not semantic_match else round((role_score * 0.65) + (vector_score * 0.35), 1)
        final_score = min(JD_FIT_MAX_SCORE, max(previous_score, blended_score))
    else:
        final_score = min(JD_FIT_MAX_SCORE, max(previous_score, vector_score))

    evidence_parts: List[str] = []
    if role_profile and not is_generic_role(role_profile):
        evidence_parts.append(f"Vi tri muc tieu: {role_profile['label']}")
    if skill_match["matchedSkills"]:
        evidence_parts.append(f"Ká»¹ nÄƒng khá»›p: {', '.join(skill_match['matchedSkills'][:6])}")
    if skill_match["transferMatches"]:
        evidence_parts.append(f"Khá»›p chuyá»ƒn Ä‘á»•i: {'; '.join(skill_match['transferMatches'][:3])}")
    if skill_match["unmatchedSkills"]:
        evidence_parts.append(f"CÃ²n thiáº¿u: {', '.join(skill_match['unmatchedSkills'][:4])}")
    if semantic_match:
        evidence_parts.append(
            f"Embedding JD/CV {semantic_match['similarity'] * 100:.1f}% ({semantic_match['queryModel']})"
        )
    evidence = " | ".join(evidence_parts) or "ChÆ°a cÃ³ Ä‘á»§ dá»¯ liá»‡u Ä‘á»ƒ suy ra pháº§n so khá»›p JD/CV."

    if semantic_match and role_profile and not is_generic_role(role_profile):
        explanation = (
            f"So khop Job Fit uu tien nang luc chuyen mon cua {role_profile['label']}, "
            f"sau do doi chieu voi do tuong dong embedding JD/CV."
        )
        formula = (
            f"max(AI Job Fit {_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}, "
            f"Role fit {_format_score_value(role_score)}/{_format_score_value(JD_FIT_MAX_SCORE)} * 65% + "
            f"Vector semantic {_format_score_value(vector_score)}/{_format_score_value(JD_FIT_MAX_SCORE)} * 35%)"
        )
    elif semantic_match:
        explanation = (
            f"So khá»›p JD/CV láº¥y má»©c cao hÆ¡n giá»¯a Ä‘iá»ƒm AI gá»‘c "
            f"{_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)} vÃ  "
            f"Ä‘iá»ƒm semantic embedding {_format_score_value(vector_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}."
        )
        formula = (
            f"max(AI Job Fit {_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}, "
            f"Vector semantic {_format_score_value(vector_score)}/{_format_score_value(JD_FIT_MAX_SCORE)})"
        )
    elif role_profile and not is_generic_role(role_profile):
        explanation = f"Khong tao duoc semantic embedding on dinh, nen Job Fit duoc suy ra tu bang chung chuyen mon cua {role_profile['label']}."
        formula = f"max(AI Job Fit {_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}, Role fit {_format_score_value(role_score)}/{_format_score_value(JD_FIT_MAX_SCORE)})"
    else:
        explanation = "Giá»¯ láº¡i Ä‘iá»ƒm Job Fit hiá»‡n cÃ³ vÃ¬ chÆ°a táº¡o Ä‘Æ°á»£c semantic embedding á»•n Ä‘á»‹nh cho JD/CV."
        formula = f"AI Job Fit {_format_score_value(previous_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}"

    candidate["jdCvMatchInsights"] = {
        "similarity": float(semantic_match.get("similarity") or 0.0) if semantic_match else 0.0,
        "weightedScore": final_score,
        "semanticWeightedScore": vector_score,
        "maxScore": JD_FIT_MAX_SCORE,
        "queryModel": semantic_match.get("queryModel") if semantic_match else None,
        "roleKey": role_profile.get("roleKey") or "generic",
        "roleLabel": role_profile.get("label") or "General Specialist",
        "matchedSkills": skill_match["matchedSkills"],
        "missingSkills": skill_match["unmatchedSkills"],
        "transferMatches": skill_match["transferMatches"],
        "matchedRequirements": skill_match.get("matchedRequirements") or skill_match["matchedSkills"],
        "missingRequirements": skill_match.get("missingRequirements") or skill_match["unmatchedSkills"],
        "evidenceMatches": skill_match.get("evidenceMatches") or [],
        "uiSections": skill_match.get("uiSections") or list(role_profile.get("uiSections") or ["General fit"]),
    }

    detail_payload = _detail_item(
        JD_FIT_CRITERION_LABEL,
        f"{_format_score_value(final_score)}/{_format_score_value(JD_FIT_MAX_SCORE)}",
        formula,
        evidence,
        explanation,
    )
    if detail_index is None:
        details.insert(0, detail_payload)
    else:
        details[detail_index] = detail_payload

    current_total = (
        _parse_numeric_value(analysis.get("Tá»•ng Ä‘iá»ƒm"))
        or _parse_numeric_value(analysis.get("Tong diem"))
        or _parse_numeric_value(analysis.get("TÃƒÂ¡Ã‚Â»Ã¢â‚¬Â¢ng Ãƒâ€žÃ¢â‚¬ËœiÃƒÂ¡Ã‚Â»Ã†â€™m"))
        or _parse_numeric_value(analysis.get("TÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ng ÃƒÆ’Ã¢â‚¬Å¾ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“iÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€ Ã¢â‚¬â„¢m"))
    )
    if current_total is not None:
        updated_total = max(0.0, min(100.0, current_total + (final_score - previous_score)))
        analysis["Tá»•ng Ä‘iá»ƒm"] = round(updated_total, 1)
        analysis["Tong diem"] = round(updated_total, 1)
        analysis["TÃƒÂ¡Ã‚Â»Ã¢â‚¬Â¢ng Ãƒâ€žÃ¢â‚¬ËœiÃƒÂ¡Ã‚Â»Ã†â€™m"] = analysis["Tá»•ng Ä‘iá»ƒm"]
        analysis["TÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ng ÃƒÆ’Ã¢â‚¬Å¾ÃƒÂ¢Ã¢â€šÂ¬Ã‹Å“iÃƒÆ’Ã‚Â¡Ãƒâ€šÃ‚Â»Ãƒâ€ Ã¢â‚¬â„¢m"] = analysis["Tá»•ng Ä‘iá»ƒm"]


def enrich_candidates(
    candidates: List[Dict[str, Any]],
    cv_text_map: Dict[str, str],
    jd_text: str,
    hard_filters: Dict[str, Any],
    owner_uid: str | None = None,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    settings = get_settings()
    jd_vector: List[float] | None = None
    cleaned_jd_for_embedding = _prepare_embedding_text(jd_text)
    if cleaned_jd_for_embedding:
        try:
            jd_vector = embed_text(cleaned_jd_for_embedding, settings.gemini_embedding_model)
        except Exception:
            jd_vector = None
    for candidate in candidates:
        cv_text = cv_text_map.get(str(candidate.get("fileName", "")), "")
        analysis = candidate.get("analysis") or {}
        details = _get_analysis_details(analysis)
        _sync_analysis_detail_aliases(analysis, details)

        cv_vector: List[float] | None = None
        if cv_text:
            cleaned_cv_for_embedding = _prepare_embedding_text(cv_text)
            if cleaned_cv_for_embedding:
                try:
                    cv_vector = embed_text(cleaned_cv_for_embedding, settings.gemini_embedding_model)
                except Exception:
                    cv_vector = None
        semantic_match = _compute_jd_cv_embedding_match(
            jd_text,
            cv_text,
            jd_vector=jd_vector,
            cv_vector=cv_vector,
        ) if cv_text else None
        _upsert_jd_fit_detail(
            details,
            analysis=analysis,
            candidate=candidate,
            jd_text=jd_text,
            cv_text=cv_text,
            hard_filters=hard_filters,
            semantic_match=semantic_match,
        )

        if cv_text:
            debias_result = _run_debiasing(cv_text, hard_filters)
            if debias_result["warnings"]:
                candidate["debiasingWarnings"] = debias_result["warnings"]

            for key, val in _analyze_soft_skills(cv_text).items():
                details.append(_detail_item(key, f"{val['score']}/{val['maxScore']}", "", str(val["reasoning"])[:200], val["reasoning"]))

        companies = _extract_companies_from_candidate(candidate)
        if companies:
            base_score = analysis.get("Tá»•ng Ä‘iá»ƒm") or analysis.get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m") or 50
            tiered = _apply_company_tier_multiplier(float(base_score), companies)
            if tiered["adjustedScore"] != base_score:
                analysis["Tá»•ng Ä‘iá»ƒm"] = min(100, tiered["adjustedScore"])
                analysis["TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m"] = analysis["Tá»•ng Ä‘iá»ƒm"]
                details.append(_detail_item(
                    "Há»‡ sá»‘ uy tÃ­n cÃ´ng ty",
                    f"{'+' if tiered['adjustedScore'] - base_score > 0 else ''}{tiered['adjustedScore'] - base_score:.1f}",
                    tiered["reasoning"],
                    ", ".join([f"{name} (x{multiplier})" for name, multiplier in tiered["multipliers"].items() if multiplier > 1]),
                    tiered["reasoning"],
                ))

        if details:
            criteria_scores: Dict[str, float] = {}
            criteria_evidence: Dict[str, str] = {}
            for item in details:
                score_text = str(item.get("Äiá»ƒm") or item.get("Ã„ÂiÃ¡Â»Æ’m") or "0")
                criteria = str(item.get("TiÃªu chÃ­") or item.get("TiÃƒÂªu chÃƒÂ­") or "")
                evidence = str(item.get("Dáº«n chá»©ng") or item.get("DÃ¡ÂºÂ«n chÃ¡Â»Â©ng") or "")
                try:
                    criteria_scores[criteria] = float(score_text.split("/")[0].replace("+", ""))
                except Exception:
                    criteria_scores[criteria] = 0.0
                criteria_evidence[criteria] = evidence
            boost_signals = _apply_dynamic_boost(criteria_scores, criteria_evidence)
            if boost_signals:
                total_boost = 0.0
                for signal in boost_signals:
                    total_boost += signal["boostAmount"]
                    details.append(_detail_item(
                        f"Dynamic Boost: {signal['sourceCriterion']}",
                        f"+{signal['boostAmount']:.1f}",
                        signal["reason"],
                        signal["reason"],
                        signal["reason"],
                    ))
                current_score = analysis.get("Tá»•ng Ä‘iá»ƒm") or analysis.get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m")
                if isinstance(current_score, (int, float)):
                    analysis["Tá»•ng Ä‘iá»ƒm"] = min(100, current_score + total_boost)
                    analysis["TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m"] = analysis["Tá»•ng Ä‘iá»ƒm"]

        if cv_text:
            _upsert_industry_fit_detail(
                details,
                analysis=analysis,
                candidate=candidate,
                hard_filters=hard_filters,
                cv_text=cv_text,
                owner_uid=owner_uid,
                query_vector=cv_vector,
            )

        if False and cv_text:
            industry = _detect_industry(candidate, hard_filters)
            if industry:
                insight = _compute_industry_similarity(
                    industry,
                    cv_text,
                    owner_uid=owner_uid,
                    file_name=str(candidate.get("fileName") or ""),
                    query_vector=cv_vector,
                )
                if insight:
                    candidate["embeddingInsights"] = insight
                    details.insert(0, _detail_item(
                        f"Chuáº©n máº«u {industry.upper()}",
                        f"{insight['bonusPoints']:.1f}/5",
                        f"Similarity {insight['averageSimilarity'] * 100:.1f}% => +{insight['bonusPoints']:.1f} diem",
                        "; ".join([f"{item.get('name') or item.get('role') or item.get('id')} {item['similarity'] * 100:.1f}%" for item in insight["topMatches"][:3]]),
                        f"CV tuong dong thu vien CV {industry.upper()} chuan.",
                    ))
                    current_score = analysis.get("Tá»•ng Ä‘iá»ƒm") or analysis.get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m")
                    if isinstance(current_score, (int, float)):
                        analysis["Tá»•ng Ä‘iá»ƒm"] = min(100, current_score + insight["bonusPoints"])
                        analysis["TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m"] = analysis["Tá»•ng Ä‘iá»ƒm"]

        score = analysis.get("Tá»•ng Ä‘iá»ƒm") or analysis.get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m")
        if isinstance(score, (int, float)):
            analysis["Háº¡ng"] = "A" if score >= 75 else "B" if score >= 50 else "C"
            analysis["HÃ¡ÂºÂ¡ng"] = analysis["Háº¡ng"]
        candidate["analysis"] = analysis
        enriched.append(candidate)

    enriched.sort(
        key=lambda candidate: (
            -float((candidate.get("analysis") or {}).get("Tá»•ng Ä‘iá»ƒm") or (candidate.get("analysis") or {}).get("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m") or -1),
            str(candidate.get("fileName") or ""),
        )
    )
    return enriched
