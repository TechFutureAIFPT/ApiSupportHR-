from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List


def _normalize_lookup(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9+#.]+", " ", normalized.lower()).strip()


def _unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = _normalize_lookup(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
    return items


def _requirement(
    key: str,
    label: str,
    section: str,
    terms: list[str],
    *,
    equivalent_terms: list[str] | None = None,
    evidence_terms: list[str] | None = None,
    weight: float = 1.0,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "section": section,
        "terms": _unique_strings([label, *terms]),
        "equivalentTerms": _unique_strings(equivalent_terms or []),
        "evidenceTerms": _unique_strings(evidence_terms or []),
        "weight": float(weight),
    }


ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "backend_developer": {
        "roleKey": "backend_developer",
        "label": "Backend Developer",
        "aliases": ["backend developer", "backend engineer", "server-side developer", "api developer"],
        "collectionKey": "it",
        "uiSections": ["Core stack", "Database/API", "DevOps/Cloud", "Security/Performance"],
        "negativeSignals": ["thiếu triển khai api", "không có database", "không có devops"],
        "coreRequirements": [
            _requirement("backend_api", "REST API / GraphQL", "Database/API", ["rest api", "graphql", "api", "endpoint", "microservice"]),
            _requirement("backend_db", "Database design", "Database/API", ["sql", "postgresql", "mysql", "mongodb", "database", "schema", "query optimization"]),
            _requirement("backend_core_stack", "Backend language/framework", "Core stack", ["python", "java", "node", "golang", "c#", "django", "fastapi", "spring", "nestjs", "express"]),
            _requirement("backend_devops", "Docker / Cloud / CI", "DevOps/Cloud", ["docker", "aws", "gcp", "azure", "ci/cd", "kubernetes", "deploy", "terraform"], equivalent_terms=["jenkins", "github actions"]),
        ],
        "secondaryRequirements": [
            _requirement("backend_security", "Auth / Security", "Security/Performance", ["oauth", "jwt", "authentication", "authorization", "security", "ssl"]),
            _requirement("backend_perf", "Performance / Monitoring", "Security/Performance", ["performance", "caching", "redis", "monitoring", "logging", "grafana", "prometheus"]),
        ],
    },
    "frontend_developer": {
        "roleKey": "frontend_developer",
        "label": "Frontend Developer",
        "aliases": ["frontend developer", "frontend engineer", "ui developer", "web frontend"],
        "collectionKey": "it",
        "uiSections": ["Core stack", "State/UI", "Integration", "Quality/Performance"],
        "negativeSignals": ["thiếu framework frontend", "không có responsive", "không có test ui"],
        "coreRequirements": [
            _requirement("frontend_framework", "Frontend framework", "Core stack", ["react", "vue", "angular", "nextjs", "nuxt", "typescript", "javascript"]),
            _requirement("frontend_ui", "Responsive / Accessibility", "State/UI", ["responsive", "accessibility", "a11y", "html", "css", "tailwind", "scss"]),
            _requirement("frontend_state", "State management", "State/UI", ["redux", "zustand", "context api", "pinia", "vuex", "state management"]),
            _requirement("frontend_api", "API integration", "Integration", ["rest api", "graphql", "axios", "fetch", "api integration"]),
        ],
        "secondaryRequirements": [
            _requirement("frontend_quality", "Testing", "Quality/Performance", ["jest", "vitest", "cypress", "playwright", "testing library", "unit test"]),
            _requirement("frontend_perf", "Performance optimization", "Quality/Performance", ["performance", "lazy loading", "bundle", "web vitals", "optimization"]),
        ],
    },
    "fullstack_developer": {
        "roleKey": "fullstack_developer",
        "label": "Fullstack Developer",
        "aliases": ["fullstack developer", "full-stack developer", "fullstack engineer", "full stack engineer"],
        "collectionKey": "it",
        "uiSections": ["Frontend", "Backend", "Database/API", "Deployment"],
        "negativeSignals": ["thiếu một nửa stack", "không có triển khai end-to-end"],
        "coreRequirements": [
            _requirement("fullstack_frontend", "Frontend stack", "Frontend", ["react", "vue", "angular", "typescript", "javascript", "html", "css"]),
            _requirement("fullstack_backend", "Backend stack", "Backend", ["node", "python", "java", "golang", "nestjs", "express", "fastapi", "spring"]),
            _requirement("fullstack_api", "API / Database", "Database/API", ["rest api", "graphql", "sql", "postgresql", "mysql", "mongodb", "redis"]),
            _requirement("fullstack_deploy", "Deployment ownership", "Deployment", ["docker", "aws", "gcp", "azure", "ci/cd", "deploy", "kubernetes"]),
        ],
        "secondaryRequirements": [
            _requirement("fullstack_testing", "Testing", "Deployment", ["jest", "vitest", "cypress", "playwright", "unit test", "integration test"]),
        ],
    },
    "qa_engineer": {
        "roleKey": "qa_engineer",
        "label": "QA Engineer",
        "aliases": ["qa engineer", "quality assurance", "tester", "test engineer", "software tester"],
        "collectionKey": "it",
        "uiSections": ["Manual QA", "Automation", "API/UI testing", "Process/CI"],
        "negativeSignals": ["thiếu test case", "không có automation", "không có regression"],
        "coreRequirements": [
            _requirement("qa_manual", "Test case / Test plan", "Manual QA", ["test case", "test plan", "manual testing", "uat", "functional test"]),
            _requirement("qa_automation", "Automation testing", "Automation", ["selenium", "cypress", "playwright", "automation", "robot framework"]),
            _requirement("qa_api_ui", "API / UI testing", "API/UI testing", ["postman", "api testing", "ui testing", "regression", "smoke test"]),
            _requirement("qa_bug", "Bug lifecycle", "Process/CI", ["bug report", "jira", "defect", "bug tracking", "test report"]),
        ],
        "secondaryRequirements": [
            _requirement("qa_ci", "CI / Quality process", "Process/CI", ["ci/cd", "jenkins", "github actions", "quality gate", "release testing"]),
        ],
    },
    "data_analyst": {
        "roleKey": "data_analyst",
        "label": "Data Analyst",
        "aliases": ["data analyst", "business analyst", "bi analyst", "analytics specialist"],
        "collectionKey": "it",
        "uiSections": ["SQL/Data prep", "BI/Visualization", "Metrics/Insight", "Stakeholder reporting"],
        "negativeSignals": ["thiếu sql", "không có dashboard", "không có business insight"],
        "coreRequirements": [
            _requirement("data_sql", "SQL / Data processing", "SQL/Data prep", ["sql", "postgresql", "mysql", "bigquery", "etl", "data cleaning"]),
            _requirement("data_bi", "Dashboard / BI tools", "BI/Visualization", ["tableau", "power bi", "looker", "dashboard", "visualization", "excel"]),
            _requirement("data_metrics", "Metrics / Business insight", "Metrics/Insight", ["kpi", "metric", "cohort", "funnel", "retention", "forecast", "business insight"]),
            _requirement("data_reporting", "Stakeholder communication", "Stakeholder reporting", ["reporting", "presentation", "stakeholder", "cross-functional", "insight"]),
        ],
        "secondaryRequirements": [
            _requirement("data_python", "Analytical tooling", "SQL/Data prep", ["python", "pandas", "numpy", "statistics", "a/b testing"]),
        ],
    },
    "digital_marketing": {
        "roleKey": "digital_marketing",
        "label": "Digital Marketing",
        "aliases": ["digital marketing", "marketing executive", "performance marketing", "growth marketing", "marketing specialist"],
        "collectionKey": "marketing",
        "uiSections": ["Channels", "Campaign execution", "Performance metrics", "Analytics/Tooling"],
        "negativeSignals": ["thiếu nền tảng quảng cáo", "không có roas", "không có campaign"],
        "coreRequirements": [
            _requirement("mkt_channels", "Ads platforms", "Channels", ["facebook ads", "google ads", "tiktok ads", "meta ads", "digital ads"]),
            _requirement("mkt_campaign", "Campaign execution", "Campaign execution", ["campaign", "media buying", "budget", "creative testing", "funnel"]),
            _requirement("mkt_metrics", "ROAS / CAC / CTR / CPC", "Performance metrics", ["roas", "cac", "ctr", "cpc", "cpm", "conversion rate", "cost per lead"]),
            _requirement("mkt_tools", "Analytics tooling", "Analytics/Tooling", ["google analytics", "ga4", "looker studio", "utm", "tracking", "crm"]),
        ],
        "secondaryRequirements": [
            _requirement("mkt_content", "Content / SEO support", "Channels", ["seo", "content", "landing page", "copywriting", "social media"]),
        ],
    },
    "sales_executive": {
        "roleKey": "sales_executive",
        "label": "Sales Executive",
        "aliases": ["sales executive", "sales representative", "account executive", "business development executive", "sale executive"],
        "collectionKey": "sales",
        "uiSections": ["Lead generation", "Pipeline/CRM", "Closing", "Revenue/KPI"],
        "negativeSignals": ["thiếu doanh số", "không có crm", "không có lead/pipeline"],
        "coreRequirements": [
            _requirement("sales_lead", "Lead generation", "Lead generation", ["lead generation", "prospecting", "outbound", "inbound lead", "khach hang tiem nang"]),
            _requirement("sales_pipeline", "Pipeline / CRM", "Pipeline/CRM", ["crm", "salesforce", "hubspot", "pipeline", "opportunity", "account management"]),
            _requirement("sales_closing", "Negotiation / Closing", "Closing", ["closing", "negotiation", "proposal", "quotation", "deal", "contract"]),
            _requirement("sales_kpi", "Revenue / KPI", "Revenue/KPI", ["revenue", "sales target", "quota", "gmv", "doanh so", "tang truong"]),
        ],
        "secondaryRequirements": [
            _requirement("sales_reporting", "Forecast / Reporting", "Revenue/KPI", ["forecast", "reporting", "weekly report", "monthly report"]),
        ],
    },
    "ui_ux_designer": {
        "roleKey": "ui_ux_designer",
        "label": "UI/UX Designer",
        "aliases": ["ui ux designer", "ux ui designer", "product designer", "ui designer", "ux designer"],
        "collectionKey": "design",
        "uiSections": ["Design tooling", "User flow/Research", "Prototype/System", "Handoff"],
        "negativeSignals": ["thiếu figma", "không có prototype", "không có user research"],
        "coreRequirements": [
            _requirement("design_tooling", "Figma / design tooling", "Design tooling", ["figma", "sketch", "adobe xd", "photoshop", "illustrator"]),
            _requirement("design_flow", "User flow / Research", "User flow/Research", ["user flow", "user research", "wireframe", "persona", "usability", "interview"]),
            _requirement("design_system", "Prototype / Design system", "Prototype/System", ["prototype", "design system", "component", "interaction design", "information architecture"]),
            _requirement("design_handoff", "Developer handoff", "Handoff", ["handoff", "developer handoff", "spec", "responsive design", "collaboration"]),
        ],
        "secondaryRequirements": [
            _requirement("design_metrics", "Outcome / usability impact", "User flow/Research", ["conversion", "engagement", "ab testing", "drop-off", "usability testing"]),
        ],
    },
    "generic": {
        "roleKey": "generic",
        "label": "General Specialist",
        "aliases": [],
        "collectionKey": "generic",
        "uiSections": ["General fit"],
        "negativeSignals": [],
        "coreRequirements": [],
        "secondaryRequirements": [],
    },
}


COLLECTION_DEFAULT_ROLE = {
    "it": "fullstack_developer",
    "marketing": "digital_marketing",
    "sales": "sales_executive",
    "design": "ui_ux_designer",
}


def get_role_profile(role_key: str | None) -> dict[str, Any]:
    return ROLE_PROFILES.get(str(role_key or "").strip(), ROLE_PROFILES["generic"])


def get_role_requirements(role_profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *list(role_profile.get("coreRequirements") or []),
        *list(role_profile.get("secondaryRequirements") or []),
    ]


def is_generic_role(role_profile: dict[str, Any] | None) -> bool:
    return str((role_profile or {}).get("roleKey") or "generic") == "generic"


def infer_collection_key(industry_hint: str) -> str | None:
    normalized = _normalize_lookup(industry_hint)
    if not normalized:
        return None
    if any(term in normalized for term in ("marketing", "truyen thong", "seo", "content", "brand", "digital")):
        return "marketing"
    if any(term in normalized for term in ("sales", "sale", "kinh doanh", "business development", "account executive")):
        return "sales"
    if any(term in normalized for term in ("design", "designer", "ui ux", "ux ui", "creative", "figma")):
        return "design"
    if any(term in normalized for term in ("it", "software", "developer", "engineer", "data", "qa", "tester", "lap trinh", "cong nghe")):
        return "it"
    return None


def _match_alias_score(text: str, aliases: list[str]) -> float:
    normalized_text = f" {_normalize_lookup(text)} "
    if normalized_text.strip() == "":
        return 0.0

    best = 0.0
    for alias in aliases:
        normalized_alias = _normalize_lookup(alias)
        if not normalized_alias:
            continue
        wrapped_alias = f" {normalized_alias} "
        if normalized_text == wrapped_alias:
            best = max(best, 100.0 + len(normalized_alias) / 10)
        elif wrapped_alias in normalized_text:
            best = max(best, 70.0 + len(normalized_alias) / 10)
        elif normalized_alias in normalized_text:
            best = max(best, 45.0 + len(normalized_alias) / 10)
    return best


def _count_profile_signals(profile: dict[str, Any], jd_text: str, collection_hint: str | None) -> float:
    if is_generic_role(profile):
        return 0.0

    if collection_hint and profile.get("collectionKey") not in {collection_hint, "generic"}:
        return 0.0

    normalized_jd = f" {_normalize_lookup(jd_text)} "
    if normalized_jd.strip() == "":
        return 0.0

    score = 1.0 if collection_hint and profile.get("collectionKey") == collection_hint else 0.0
    score += _match_alias_score(jd_text, [str(profile.get("label") or ""), *list(profile.get("aliases") or [])]) / 40.0

    for requirement in get_role_requirements(profile):
        terms = [*list(requirement.get("terms") or []), *list(requirement.get("equivalentTerms") or [])]
        weight = float(requirement.get("weight") or 1.0)
        if any(f" {_normalize_lookup(term)} " in normalized_jd for term in terms if _normalize_lookup(term)):
            score += 1.4 * weight
    return score


def resolve_role_profile(
    *,
    jd_text: str = "",
    job_position: str = "",
    hard_filters: dict[str, Any] | None = None,
    industry_hint: str = "",
    candidate_job_title: str = "",
) -> dict[str, Any]:
    hard_filters = hard_filters or {}
    explicit_signals = [
        job_position,
        str(hard_filters.get("jobTitle") or ""),
        str(hard_filters.get("position") or ""),
        candidate_job_title,
    ]

    profiles = [profile for key, profile in ROLE_PROFILES.items() if key != "generic"]

    explicit_match: dict[str, Any] | None = None
    explicit_score = 0.0
    for signal in explicit_signals:
        for profile in profiles:
            score = _match_alias_score(signal, [str(profile.get("label") or ""), *list(profile.get("aliases") or [])])
            if score > explicit_score:
                explicit_score = score
                explicit_match = profile
    if explicit_match and explicit_score >= 45.0:
        return explicit_match

    collection_hint = infer_collection_key(industry_hint or str(hard_filters.get("industry") or ""))

    scored_profiles = sorted(
        (
            (_count_profile_signals(profile, jd_text, collection_hint), profile)
            for profile in profiles
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if scored_profiles and scored_profiles[0][0] >= 2.5:
        return scored_profiles[0][1]

    if collection_hint:
        return get_role_profile(COLLECTION_DEFAULT_ROLE.get(collection_hint))

    return ROLE_PROFILES["generic"]


def build_role_profile_summary(role_profile: dict[str, Any]) -> str:
    if is_generic_role(role_profile):
        return (
            "Khong xac dinh duoc vi tri cu the. "
            "Hay phan tich theo JD thuc te, uu tien keyword, KPI va bang chung truc tiep trong CV."
        )

    core = [str(item.get("label") or "") for item in role_profile.get("coreRequirements") or [] if str(item.get("label") or "").strip()]
    secondary = [str(item.get("label") or "") for item in role_profile.get("secondaryRequirements") or [] if str(item.get("label") or "").strip()]
    sections = [str(item).strip() for item in role_profile.get("uiSections") or [] if str(item).strip()]

    lines = [
        f"Role target: {role_profile.get('label') or 'Unknown'}",
        f"Collection: {role_profile.get('collectionKey') or 'generic'}",
        f"Core requirements: {', '.join(core) if core else 'Khong co'}",
        f"Secondary requirements: {', '.join(secondary) if secondary else 'Khong co'}",
        f"Display sections: {', '.join(sections) if sections else 'General fit'}",
    ]
    return "\n".join(lines)
