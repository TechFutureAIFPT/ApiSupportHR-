from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

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


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _detail_item(title: str, score: str, formula: str, evidence: str, explanation: str) -> Dict[str, str]:
    return {
        "Tiêu chí": title,
        "TiÃªu chÃ­": title,
        "Điểm": score,
        "Äiá»ƒm": score,
        "Công thức": formula,
        "CÃ´ng thá»©c": formula,
        "Dẫn chứng": evidence,
        "Dáº«n chá»©ng": evidence,
        "Giải thích": explanation,
        "Giáº£i thÃ­ch": explanation,
    }


def _extract_skills_from_jd(jd_text: str) -> List[str]:
    lower = jd_text.lower()
    return [skill for skill in SKILL_KEYWORDS if skill.lower() in lower]


def _extract_skills_from_candidate(candidate: Dict[str, Any]) -> List[str]:
    analysis = candidate.get("analysis") or {}
    details = analysis.get("Chi tiết") or analysis.get("Chi tiáº¿t") or []
    strengths = analysis.get("Điểm mạnh CV") or analysis.get("Äiá»ƒm máº¡nh CV") or []
    texts = [
        candidate.get("jobTitle", ""),
        candidate.get("industry", ""),
        candidate.get("department", ""),
        *[str(item.get("Dẫn chứng") or item.get("Dáº«n chá»©ng") or "") for item in details if isinstance(item, dict)],
        *[str(item) for item in strengths],
    ]
    combined = " ".join(texts).lower()
    return [skill for skill in SKILL_KEYWORDS if skill.lower() in combined]


def _extract_companies_from_candidate(candidate: Dict[str, Any]) -> List[str]:
    analysis = candidate.get("analysis") or {}
    details = analysis.get("Chi tiết") or analysis.get("Chi tiáº¿t") or []
    strengths = analysis.get("Điểm mạnh CV") or analysis.get("Äiá»ƒm máº¡nh CV") or []
    evidence = " ".join([
        str(candidate.get("jobTitle", "")),
        str(candidate.get("industry", "")),
        str(candidate.get("department", "")),
        *[str(item.get("Dẫn chứng") or item.get("Dáº«n chá»©ng") or "") for item in details if isinstance(item, dict)],
        *[str(item) for item in strengths],
    ]).lower()
    return [name for name in COMPANY_NAME_WORDS if name in evidence]


def _check_bias_risk(filters: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    age = filters.get("age") or {}
    if isinstance(age, dict) and (age.get("min") is not None or age.get("max") is not None):
        warnings.append(f"Canh bao: Bo loc tuoi ({age.get('min', '?')}–{age.get('max', '?')}) co the vi pham Dieu 8 BLLD 2019.")
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
            "Dieu 8 BLLD 2019 — Nghiem cam phan biet doi xu tren co so gioi tinh, tuoi tac, ton giao, dan toc.",
            "Dieu 36 BLLD 2019 — Khong duoc yeu cau xac nhan tinh trang hon nhan khi tuyen dung.",
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
    lower = cv_text.lower()
    leader = _contains_any(lower, LEADER_VERBS)
    active = _contains_any(lower, ACTIVE_VERBS)
    passive = _contains_any(lower, PASSIVE_VERBS)

    score = 5 + len(leader) * 1.5 + len(active) * 0.8 - len(passive) * 1.0
    score = max(0, min(10, score))
    if leader or score >= 8:
        label = "Chu dong cao (Lanh dao)"
    elif len(passive) > len(active):
        label = "Thu dong"
    elif active:
        label = "Chu dong"
    else:
        label = "Chua ro"

    action_reasoning_parts = []
    if leader:
        action_reasoning_parts.append(f"Dong tu lanh dao: {', '.join(leader[:3])}")
    if active:
        action_reasoning_parts.append(f"Dong tu chu dong: {', '.join(active[:5])}")
    if passive:
        action_reasoning_parts.append(f"Dong tu thu dong: {', '.join(passive[:3])}")
    action_reasoning = ". ".join(action_reasoning_parts) or "Khong phat hien mau hanh vi ro rang."

    paragraphs = [p for p in re.split(r"\n\n|\n(?=[A-Z])", cv_text) if len(p.strip()) > 20]
    s = t = a = r = 0
    s_ind = ["trước đó", "trong bối cảnh", "khi đó", "thời điểm đó", "challenge", "thach thuc", "van de", "bối cảnh"]
    t_ind = ["nhiệm vụ", "trách nhiệm", "task", "mission", "goal", "mục tiêu", "objective", "required to"]
    a_ind = ["đã", "implemented", "developed", "designed", "created", "managed", "led", "coordinated", "analyzed", "triển khai", "xây dựng", "thiết kế", "quản lý", "thực hiện"]
    r_ind = ["kết quả", "result", "outcome", "achieved", "delivered", "improved", "increased", "reduced", "thành công", "đạt được", "tăng", "hiệu quả"]
    has_numbers = False
    has_metrics = False
    for para in paragraphs:
        pl = para.lower()
        s += sum(1 for indicator in s_ind if indicator in pl) > 0
        t += sum(1 for indicator in t_ind if indicator in pl) > 0
        a += sum(1 for indicator in a_ind if indicator in pl) > 0
        r += sum(1 for indicator in r_ind if indicator in pl) > 0
        has_numbers = has_numbers or bool(re.search(r"\d+", para))
        has_metrics = has_metrics or any(pattern.search(para) for pattern in METRIC_PATTERNS)
    s, t, a, r = min(3, s), min(3, t), min(3, a), min(3, r)
    total = s + t + a + r
    if total >= 8:
        star_reasoning = "CV co cau truc STAR ro rang, kem so lieu chung minh."
    elif total >= 5:
        star_reasoning = "CV co mot so yeu to STAR, can cai thien ket qua va so lieu."
    elif total >= 3:
        star_reasoning = "CV thien ve liet ke trach nhiem, thieu ket qua cu the."
    else:
        star_reasoning = "CV rat so luoc, kho danh gia nang luc thuc te."
    if has_metrics:
        star_reasoning += " Phat hien so lieu dinh luong."
    star_score = round((total / 12) * 10, 1)

    jobs = []
    current_title = ""
    current_company = ""
    is_promotion = False
    loyalty_keywords = ["thăng tiến", "thăng chức", "promotion", "promoted", "advance", "lên cấp", "tăng chức"]
    for line in [line for line in re.split(r"\n|\r", cv_text) if len(line.strip()) > 5]:
        title_match = re.search(r"(?:chức danh|vị trí|position|role)[:\s]*(.+)", line, re.IGNORECASE)
        company_match = re.search(r"(?:công ty|company|doanh nghiệp)[:\s]*(.+)", line, re.IGNORECASE)
        year_match = re.findall(r"(?:20\d{2}|19\d{2})", line)
        if title_match:
            current_title = title_match.group(1).strip()
            is_promotion = any(keyword in line.lower() for keyword in loyalty_keywords)
        if company_match:
            current_company = company_match.group(1).strip()
        if len(year_match) >= 2:
            years = [int(value) for value in year_match[:2]]
            jobs.append({
                "title": current_title,
                "company": current_company,
                "months": max(1, (years[1] - years[0]) * 12),
                "promotion": is_promotion,
            })
            current_title = ""
            current_company = ""
            is_promotion = False

    if jobs:
        total_jobs = len(jobs)
        total_months = sum(job["months"] for job in jobs)
        avg_tenure = round(total_months / total_jobs)
        promotions = sum(1 for job in jobs if job["promotion"])
        flat_hops = max(0, total_jobs - 1 - promotions)
        loyalty_index = 10 if avg_tenure >= 36 else 8 if avg_tenure >= 24 else 6 if avg_tenure >= 18 else 4 if avg_tenure >= 12 else 2 if avg_tenure >= 6 else 0
        loyalty_index = min(10, loyalty_index + promotions)
        loyalty_index = max(0, loyalty_index - flat_hops if flat_hops >= 3 else loyalty_index)
        loyalty_tag = "stable" if loyalty_index >= 7 else "moderate" if loyalty_index >= 4 else "frequent"
        tenure_reasoning = [f"Trung binh {avg_tenure} thang/vi tri."]
        if promotions:
            tenure_reasoning.append(f"{promotions} lan nhay kem thang chuc (tich cuc).")
        if flat_hops:
            tenure_reasoning.append(f"{flat_hops} lan nhay khong kem thang chuc (can luu y).")
        tenure_text = " ".join(tenure_reasoning)
    else:
        loyalty_index = 10
        loyalty_tag = "stable"
        tenure_text = "Khong du du lieu de phan tich su on dinh."

    return {
        "Kỹ năng hành động & chủ động": {"score": round(score, 1), "maxScore": 10, "reasoning": f"{label}. {action_reasoning}"},
        "Trình bày STAR & Kết quả": {"score": star_score, "maxScore": 10, "reasoning": star_reasoning},
        "Sự ổn định & Trung thành": {"score": loyalty_index, "maxScore": 10, "reasoning": ("On dinh" if loyalty_tag == "stable" else "Kha linh hoat" if loyalty_tag == "moderate" else "Nhay viec thuong xuyen") + f". {tenure_text}"},
    }


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
        title_match = re.search(r"(?:chức danh|vị trí|position|role|title)[:\s]*(.+)", line, re.IGNORECASE)
        company_match = re.search(r"(?:công ty|company|doanh nghiệp|tại)[:\s]*(.+)", line, re.IGNORECASE)
        year_match = re.findall(r"(?:20\d{2}|19\d{2})(?:\s*[-–]\s*(?:20\d{2}|19\d{2}|nay|hiện tại|present))?", line, re.IGNORECASE)
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


def _score_skill_match(jd_skills: List[str], candidate_skills: List[str]) -> Dict[str, Any]:
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
) -> Optional[Dict[str, Any]]:
    result = search_similar_records(
        industry,
        cv_text,
        top_k=3,
        min_similarity=0.0,
        owner_uid=owner_uid,
        exclude_file_names=[file_name] if file_name else None,
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


def enrich_candidates(
    candidates: List[Dict[str, Any]],
    cv_text_map: Dict[str, str],
    jd_text: str,
    hard_filters: Dict[str, Any],
    owner_uid: str | None = None,
) -> List[Dict[str, Any]]:
    jd_skills = _extract_skills_from_jd(jd_text)
    enriched: List[Dict[str, Any]] = []
    for candidate in candidates:
        cv_text = cv_text_map.get(str(candidate.get("fileName", "")), "")
        analysis = candidate.get("analysis") or {}
        details = analysis.get("Chi tiết") or analysis.get("Chi tiáº¿t")
        if not isinstance(details, list):
            details = []
        analysis["Chi tiết"] = details
        analysis["Chi tiáº¿t"] = details

        if cv_text:
            debias_result = _run_debiasing(cv_text, hard_filters)
            if debias_result["warnings"]:
                candidate["debiasingWarnings"] = debias_result["warnings"]

            for key, val in _analyze_soft_skills(cv_text).items():
                details.append(_detail_item(key, f"{val['score']}/{val['maxScore']}", "", str(val["reasoning"])[:200], val["reasoning"]))

            velocity = _analyze_career_velocity(cv_text)
            if velocity["totalMonths"] > 0:
                details.append(_detail_item(
                    "Tiềm năng phát triển (Career Velocity)",
                    f"{velocity['potentialScore']}/20",
                    f"Bac cao nhat: {velocity['peakTitle']} (cap {velocity['peakLevel']}) | {velocity['promotionCount']} lan thang tien",
                    f"{velocity['avgMonthsPerLevel']} thang/bac — {velocity['velocityTag']}",
                    f"Toc do thang tien {'nhanh' if velocity['velocityTag'] == 'fast' else 'cham' if velocity['velocityTag'] == 'slow' else 'binh thuong'}.",
                ))

        skill_match = _score_skill_match(jd_skills, _extract_skills_from_candidate(candidate))
        if skill_match["matchRate"] > 0:
            details.append(_detail_item(
                "Kỹ năng chuyển đổi (Skill Graph)",
                f"{skill_match['matchRate']}/100",
                f"{len(skill_match['matchedSkills'])}/{len(jd_skills) or 1} skills khop",
                f"Clusters: {', '.join(skill_match['familyClusters'][:3]) or 'Khong ro'}",
                f"Ty le khop ky nang: {skill_match['matchRate']}%. Unmatched: {', '.join(skill_match['unmatchedSkills'][:3]) or 'Khong'}.",
            ))

        companies = _extract_companies_from_candidate(candidate)
        if companies:
            base_score = analysis.get("Tổng điểm") or analysis.get("Tá»•ng Ä‘iá»ƒm") or 50
            tiered = _apply_company_tier_multiplier(float(base_score), companies)
            if tiered["adjustedScore"] != base_score:
                analysis["Tổng điểm"] = min(100, tiered["adjustedScore"])
                analysis["Tá»•ng Ä‘iá»ƒm"] = analysis["Tổng điểm"]
                details.append(_detail_item(
                    "Hệ số uy tín công ty",
                    f"{'+' if tiered['adjustedScore'] - base_score > 0 else ''}{tiered['adjustedScore'] - base_score:.1f}",
                    tiered["reasoning"],
                    ", ".join([f"{name} (x{multiplier})" for name, multiplier in tiered["multipliers"].items() if multiplier > 1]),
                    tiered["reasoning"],
                ))

        if details:
            criteria_scores: Dict[str, float] = {}
            criteria_evidence: Dict[str, str] = {}
            for item in details:
                score_text = str(item.get("Điểm") or item.get("Äiá»ƒm") or "0")
                criteria = str(item.get("Tiêu chí") or item.get("TiÃªu chÃ­") or "")
                evidence = str(item.get("Dẫn chứng") or item.get("Dáº«n chá»©ng") or "")
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
                current_score = analysis.get("Tổng điểm") or analysis.get("Tá»•ng Ä‘iá»ƒm")
                if isinstance(current_score, (int, float)):
                    analysis["Tổng điểm"] = min(100, current_score + total_boost)
                    analysis["Tá»•ng Ä‘iá»ƒm"] = analysis["Tổng điểm"]

        if cv_text:
            industry = _detect_industry(candidate, hard_filters)
            if industry:
                insight = _compute_industry_similarity(
                    industry,
                    cv_text,
                    owner_uid=owner_uid,
                    file_name=str(candidate.get("fileName") or ""),
                )
                if insight:
                    candidate["embeddingInsights"] = insight
                    details.insert(0, _detail_item(
                        f"Chuẩn mẫu {industry.upper()}",
                        f"{insight['bonusPoints']:.1f}/5",
                        f"Similarity {insight['averageSimilarity'] * 100:.1f}% => +{insight['bonusPoints']:.1f} diem",
                        "; ".join([f"{item.get('name') or item.get('role') or item.get('id')} {item['similarity'] * 100:.1f}%" for item in insight["topMatches"][:3]]),
                        f"CV tuong dong thu vien CV {industry.upper()} chuan.",
                    ))
                    current_score = analysis.get("Tổng điểm") or analysis.get("Tá»•ng Ä‘iá»ƒm")
                    if isinstance(current_score, (int, float)):
                        analysis["Tổng điểm"] = min(100, current_score + insight["bonusPoints"])
                        analysis["Tá»•ng Ä‘iá»ƒm"] = analysis["Tổng điểm"]

        score = analysis.get("Tổng điểm") or analysis.get("Tá»•ng Ä‘iá»ƒm")
        if isinstance(score, (int, float)):
            analysis["Hạng"] = "A" if score >= 75 else "B" if score >= 50 else "C"
            analysis["Háº¡ng"] = analysis["Hạng"]
        candidate["analysis"] = analysis
        enriched.append(candidate)

    enriched.sort(
        key=lambda candidate: (
            -float((candidate.get("analysis") or {}).get("Tổng điểm") or (candidate.get("analysis") or {}).get("Tá»•ng Ä‘iá»ƒm") or -1),
            str(candidate.get("fileName") or ""),
        )
    )
    return enriched
