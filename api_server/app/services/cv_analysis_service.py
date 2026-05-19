from __future__ import annotations

import asyncio
import json
import math
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
GENERIC_EXPLANATION_TERMS = (
    "chua tra ve",
    "can cai thien",
    "chua du thong tin",
    "can xem them",
    "co tiem nang",
    "kha phu hop",
    "chua phu hop hoan toan",
)
GENERIC_EVIDENCE_TERMS = (
    "khong tim thay bang chung",
    "chua tra ve",
    "chua du bang chung",
)
VERDICT_ORDER = {"missing": 0, "weak": 1, "partial": 2, "strong": 3}


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


def _to_float_vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    vector: list[float] = []
    for item in value:
        try:
            vector.append(float(item))
        except (TypeError, ValueError):
            return []
    return vector


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _extract_exemplar_embedding(record: dict[str, Any]) -> list[float]:
    for key in ("embedding", "embeddingVector", "cv_embedding", "redacted_cv_embedding"):
        vector = _to_float_vector(record.get(key))
        if vector:
            return vector
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in ("embedding", "vector"):
            vector = _to_float_vector(metadata.get(key))
            if vector:
                return vector
    return []


def _format_rag_exemplar(record: dict[str, Any], similarity: float) -> dict[str, Any]:
    return {
        "industry": str(record.get("industry") or "Unknown"),
        "seniority": str(record.get("seniority") or "Junior"),
        "redacted_cv_text": str(record.get("redacted_cv_text") or record.get("redactedCvText") or ""),
        "jd_snapshot": str(record.get("jd_snapshot") or record.get("jdSnapshot") or ""),
        "analysis_json": record.get("analysis_json") if isinstance(record.get("analysis_json"), dict) else {},
        "similarity": round(float(similarity), 4),
        "source_dataset": str(record.get("source_dataset") or "kaggle-job-resume-fit"),
    }


async def get_rag_exemplars(
    predicted_industry: str,
    predicted_seniority: str,
    cv_embedding: list,
) -> list[dict[str, Any]]:
    """Fetch approved few-shot exemplars with strict metadata filters and a similarity gate.

    This function is intentionally defensive: any Firestore, schema, or vector issue returns
    an empty list so the caller can continue with the normal zero-shot scoring flow.
    """
    industry = str(predicted_industry or "").strip()
    seniority = str(predicted_seniority or "").strip()
    query_vector = _to_float_vector(cv_embedding)
    if not industry or not seniority or not query_vector:
        return []

    settings = get_settings()
    collection_name = settings.approved_exemplars_collection or "approvedExemplars"

    def _query_firestore() -> list[dict[str, Any]]:
        from app.integrations.firebase_admin import get_firestore_client

        client = get_firestore_client()
        query = (
            client.collection(collection_name)
            .where("industry", "==", industry)
            .where("seniority", "==", seniority)
            .limit(2)
        )
        return [snapshot.to_dict() or {} for snapshot in query.stream()]

    try:
        records = await asyncio.to_thread(_query_firestore)
    except Exception as error:  # pragma: no cover - runtime fallback path
        print(f"[RAG Exemplars] Firestore query failed: {error}")
        return []

    gated: list[dict[str, Any]] = []
    for record in records:
        exemplar_vector = _extract_exemplar_embedding(record)
        similarity = _cosine_similarity(query_vector, exemplar_vector)
        if similarity > 0.75:
            formatted = _format_rag_exemplar(record, similarity)
            if formatted["redacted_cv_text"] and formatted["jd_snapshot"]:
                gated.append(formatted)

    return sorted(gated, key=lambda item: item["similarity"], reverse=True)[:2]


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


def _parse_score_pair(score_text: str, formula_text: str = "") -> tuple[float, float]:
    ratio_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)", score_text or "")
    if ratio_match:
        try:
            return max(0.0, float(ratio_match.group(1))), max(0.0, float(ratio_match.group(2)))
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
    return max(0.0, raw), max(0.0, max_score or raw)


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
        points_lost = float(_extract_numeric_score(str(item.get("points_lost") or item.get("pointsLost") or 0)) or 0)
        if reason or points_lost:
            deductions.append({"reason": reason, "points_lost": round(max(0.0, points_lost), 1)})
    return deductions


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _build_deductions(
    *,
    points_lost: float,
    missing_keywords: list[str],
    explanation: str,
) -> list[dict[str, Any]]:
    if points_lost <= 0:
        return []
    if missing_keywords:
        per_keyword = round(points_lost / max(1, len(missing_keywords)), 1)
        remaining = round(points_lost, 1)
        deductions: list[dict[str, Any]] = []
        for keyword in missing_keywords[:8]:
            lost = round(min(per_keyword, remaining), 1)
            remaining = round(remaining - lost, 1)
            deductions.append(
                {
                    "reason": f"Thieu tu khoa cot loi trong JD: {keyword}",
                    "points_lost": lost,
                }
            )
            if remaining <= 0:
                break
        if remaining > 0:
            deductions.append(
                {
                    "reason": explanation or "Chua du bang chung de dat diem toi da.",
                    "points_lost": round(remaining, 1),
                }
            )
        return deductions
    return [
        {
            "reason": explanation or "Chua du bang chung de dat diem toi da.",
            "points_lost": round(points_lost, 1),
        }
    ]


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


def _score_ratio(raw_score: float, max_score: float) -> float:
    if max_score <= 0:
        return 0.0
    return max(0.0, min(1.0, raw_score / max_score))


def _criterion_family(criterion_name: str) -> str:
    normalized = _normalize_lookup(criterion_name)
    if any(term in normalized for term in ("phu hop jd", "job fit", "industry", "nganh", "role fit")):
        return "fit"
    if any(term in normalized for term in ("ky nang", "skill", "framework", "technology")):
        return "skill"
    if any(term in normalized for term in ("kinh nghiem", "experience", "seniority")):
        return "experience"
    if any(term in normalized for term in ("hoc van", "education", "degree", "chung chi", "certification")):
        return "education"
    if any(term in normalized for term in ("ngon ngu", "language", "ielts", "toeic", "jlpt", "topik")):
        return "language"
    if any(term in normalized for term in ("thanh tuu", "kpi", "achievement", "impact", "ket qua")):
        return "achievement"
    if any(term in normalized for term in ("van hoa", "culture", "thai do", "professional", "chuyen nghiep")):
        return "behavior"
    return "general"


def _split_text_fragments(value: str, *, limit_count: int = 4) -> list[str]:
    fragments: list[str] = []
    for piece in re.split(r"[|\n;]+", value or ""):
        cleaned = " ".join(str(piece).split()).strip(" -")
        if len(cleaned) < 6:
            continue
        if cleaned not in fragments:
            fragments.append(cleaned[:220])
        if len(fragments) >= limit_count:
            break
    return fragments


def _looks_generic_explanation(value: str) -> bool:
    normalized = _normalize_lookup(value)
    if not normalized:
        return True
    return any(term in normalized for term in GENERIC_EXPLANATION_TERMS)


def _looks_generic_evidence(value: str) -> bool:
    normalized = _normalize_lookup(value)
    if not normalized:
        return True
    return any(term in normalized for term in GENERIC_EVIDENCE_TERMS)


def _build_evidence_highlights(
    evidence_text: str,
    metrics: dict[str, Any],
) -> list[str]:
    highlights = _split_text_fragments(evidence_text, limit_count=4)
    if len(highlights) >= 2:
        return highlights

    for item in metrics.get("keywords_list", []):
        if not isinstance(item, dict) or item.get("status") != "matched":
            continue
        context_sentence = str(item.get("context_sentence") or "").strip()
        if context_sentence and context_sentence not in highlights:
            highlights.append(context_sentence[:220])
        if len(highlights) >= 4:
            break
    return highlights


def _build_matched_signals(
    criterion_name: str,
    metrics: dict[str, Any],
    evidence_highlights: list[str],
) -> list[str]:
    signals: list[str] = []
    for item in metrics.get("keywords_list", []):
        if not isinstance(item, dict) or item.get("status") != "matched":
            continue
        keyword = str(item.get("keyword") or "").strip()
        if keyword and keyword not in signals:
            signals.append(keyword)
        if len(signals) >= 4:
            break

    if signals:
        return signals

    family = _criterion_family(criterion_name)
    if evidence_highlights:
        if family == "experience":
            return ["Co mo ta kinh nghiem lien quan trong CV."]
        if family == "achievement":
            return ["Co bang chung ve ket qua/anh huong trong CV."]
        if family == "education":
            return ["Co thong tin hoc van/chung chi lien quan."]
        if family == "language":
            return ["Co thong tin ve trinh do ngon ngu."]
        return [evidence_highlights[0]]
    return []


def _build_missing_requirements(
    criterion_name: str,
    metrics: dict[str, Any],
    deductions: list[dict[str, Any]],
    evidence_quality: str,
) -> list[str]:
    missing: list[str] = []
    for item in metrics.get("keywords_list", []):
        if not isinstance(item, dict) or item.get("status") != "missing":
            continue
        keyword = str(item.get("keyword") or "").strip()
        if keyword and keyword not in missing:
            missing.append(keyword)
        if len(missing) >= 4:
            break

    if missing:
        return missing

    for deduction in deductions:
        reason = str(deduction.get("reason") or "").strip()
        if reason and reason not in missing:
            missing.append(reason[:120])
        if len(missing) >= 3:
            break

    if not missing and evidence_quality in {"weak", "missing"}:
        family = _criterion_family(criterion_name)
        fallback_map = {
            "fit": "Chua thay bang chung so khop voi vai tro/JD.",
            "skill": "Chua thay ky nang bat buoc duoc neu ro.",
            "experience": "Chua thay so nam hoac scope kinh nghiem ro rang.",
            "education": "Chua thay hoc van/chung chi dung yeu cau.",
            "language": "Chua thay muc do ngon ngu duoc xac nhan.",
            "achievement": "Chua thay ket qua dinh luong de chung minh tac dong.",
            "behavior": "Chua thay bang chung cho tac phong/phu hop van hoa.",
            "general": "Chua thay bang chung ro rang de dat diem cao.",
        }
        missing.append(fallback_map.get(family, fallback_map["general"]))
    return missing


def _build_verdict(raw_score: float, max_score: float) -> str:
    ratio = _score_ratio(raw_score, max_score)
    if max_score <= 0 and raw_score <= 0:
        return "missing"
    if ratio >= 0.8:
        return "strong"
    if ratio >= 0.5:
        return "partial"
    if ratio > 0:
        return "weak"
    return "missing"


def _merge_verdict(primary: str, secondary: str) -> str:
    return primary if VERDICT_ORDER.get(primary, -1) >= VERDICT_ORDER.get(secondary, -1) else secondary


def _build_evidence_quality(
    evidence_text: str,
    evidence_highlights: list[str],
    metrics: dict[str, Any],
) -> str:
    if evidence_highlights and len(evidence_highlights) >= 2:
        return "strong"
    if evidence_highlights:
        return "partial"
    if evidence_text and not _looks_generic_evidence(evidence_text):
        return "partial"
    matched_count = int(metrics.get("matched_keywords_count") or 0)
    if matched_count > 0:
        return "weak"
    return "missing"


def _build_quality_flags(
    *,
    formula_text: str,
    evidence_text: str,
    explanation_text: str,
    evidence_quality: str,
    matched_signals: list[str],
    missing_requirements: list[str],
) -> list[str]:
    flags: list[str] = []
    if _is_weak_formula(formula_text):
        flags.append("weak_formula")
    if evidence_quality in {"weak", "missing"}:
        flags.append("weak_evidence")
    if _looks_generic_explanation(explanation_text):
        flags.append("generic_explanation")
    if not matched_signals and not missing_requirements:
        flags.append("thin_reasoning")
    return flags


def _build_evidence_summary(
    criterion_name: str,
    evidence_highlights: list[str],
    matched_signals: list[str],
    missing_requirements: list[str],
) -> str:
    if evidence_highlights:
        return " | ".join(evidence_highlights[:3])
    if matched_signals:
        return f"Bang chung chinh: {', '.join(matched_signals[:3])}."
    if missing_requirements:
        family = _criterion_family(criterion_name)
        if family == "skill":
            return f"Chua thay bang chung cho: {', '.join(missing_requirements[:3])}."
        return f"Khong tim thay bang chung ro rang; con thieu {', '.join(missing_requirements[:2])}."
    return "Khong tim thay bang chung ro rang trong CV hien tai."


def _build_detail_explanation(
    *,
    criterion_name: str,
    verdict: str,
    matched_signals: list[str],
    missing_requirements: list[str],
) -> str:
    matched_text = ", ".join(matched_signals[:3])
    missing_text = ", ".join(missing_requirements[:3])
    if verdict == "strong":
        if matched_text:
            return f"Tieu chi {criterion_name} dat tot nho da the hien ro {matched_text}."
        return f"Tieu chi {criterion_name} dat tot va co bang chung ro trong CV."
    if verdict == "partial":
        if matched_text and missing_text:
            return f"Tieu chi {criterion_name} dat mot phan: co {matched_text}, nhung con thieu {missing_text}."
        if matched_text:
            return f"Tieu chi {criterion_name} dat mot phan dua tren {matched_text}."
        return f"Tieu chi {criterion_name} dat mot phan nhung bang chung con mong."
    if verdict == "weak":
        if missing_text:
            return f"Tieu chi {criterion_name} dat thap vi con thieu {missing_text}."
        return f"Tieu chi {criterion_name} dat thap do bang chung trong CV chua du ro."
    if missing_text:
        return f"Tieu chi {criterion_name} chua dat vi khong tim thay bang chung cho {missing_text}."
    return f"Tieu chi {criterion_name} chua dat vi khong tim thay bang chung ro rang trong CV."


def _build_improvement_suggestion(
    criterion_name: str,
    missing_requirements: list[str],
    evidence_quality: str,
) -> str:
    if missing_requirements:
        return f"Bo sung bang chung cu the cho: {', '.join(missing_requirements[:3])}."

    family = _criterion_family(criterion_name)
    family_defaults = {
        "fit": "Neu ro du an/ky nang gan truc tiep voi JD va ket qua da dat duoc.",
        "skill": "Bo sung cong nghe, framework, tool va pham vi da su dung.",
        "experience": "Neu ro so nam kinh nghiem, scope du an va vai tro dam nhiem.",
        "education": "Bo sung bang cap, chung chi hoac mon hoc lien quan.",
        "language": "Neu ro trinh do, chung chi va tinh huong da su dung ngon ngu.",
        "achievement": "Them KPI, metric, doanh thu, toc do tang truong hoac impact dinh luong.",
        "behavior": "Bo sung vi du ve ownership, teamwork, communication hoac leadership.",
        "general": "Bo sung bang chung cu the va ket qua do luong duoc cho tieu chi nay.",
    }
    if evidence_quality in {"weak", "missing"}:
        return family_defaults.get(family, family_defaults["general"])
    return "Duy tri bang chung cu the va neu ro hon tac dong thuc te de giu diem cao."

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
    evidence = _get_detail_value(detail, "Dan chung", "Dẫn chứng", "Dáº«n chá»©ng", "Evidence")
    explanation = _get_detail_value(detail, "Giai thich", "Giải thích", "Giáº£i thÃ­ch", "Explanation")
    raw_score, max_score = _parse_score_pair(score_text, formula)
    max_score = max(max_score, raw_score)
    points_lost = max(0.0, max_score - raw_score)
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
            mathematical_formula = (
                f"{_format_score_value(max_score)}d (toi da) - "
                f"{_format_score_value(points_lost)}d (cac diem chua dat) = "
                f"{_format_score_value(raw_score)}d"
            )
        else:
            mathematical_formula = f"{_format_score_value(max_score)}d (toi da) - 0d = {_format_score_value(raw_score)}d"

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

    evidence_highlights = _as_string_list(existing.get("evidence_highlights")) or _build_evidence_highlights(
        evidence,
        metrics,
    )
    matched_signals = _as_string_list(existing.get("matched_signals")) or _build_matched_signals(
        criterion_name,
        metrics,
        evidence_highlights,
    )
    evidence_quality = str(existing.get("evidence_quality") or "").strip().lower()
    if evidence_quality not in VERDICT_ORDER:
        evidence_quality = _build_evidence_quality(evidence, evidence_highlights, metrics)
    missing_requirements = _as_string_list(existing.get("missing_requirements")) or _build_missing_requirements(
        criterion_name,
        metrics,
        deductions,
        evidence_quality,
    )
    verdict = str(existing.get("verdict") or "").strip().lower()
    if verdict not in VERDICT_ORDER:
        verdict = _build_verdict(raw_score, max_score)
    if evidence_quality == "missing" and verdict == "strong":
        verdict = "partial"
    if not matched_signals and verdict == "strong":
        verdict = "partial"
    improvement_suggestion = str(existing.get("improvement_suggestion") or "").strip() or _build_improvement_suggestion(
        criterion_name,
        missing_requirements,
        evidence_quality,
    )
    quality_flags = _as_string_list(existing.get("quality_flags")) or _build_quality_flags(
        formula_text=mathematical_formula,
        evidence_text=evidence,
        explanation_text=explanation,
        evidence_quality=evidence_quality,
        matched_signals=matched_signals,
        missing_requirements=missing_requirements,
    )

    return {
        "max_possible_score": round(float(existing.get("max_possible_score") or max_score), 1),
        "raw_score_earned": round(float(existing.get("raw_score_earned") or raw_score), 1),
        "mathematical_formula": mathematical_formula,
        "deductions": deductions,
        "bonuses_earned": bonuses,
        "keyword_metrics": metrics,
        "verdict": verdict,
        "evidence_quality": evidence_quality,
        "matched_signals": matched_signals,
        "missing_requirements": missing_requirements,
        "evidence_highlights": evidence_highlights,
        "improvement_suggestion": improvement_suggestion,
        "quality_flags": quality_flags,
    }


def _set_detail_field(detail: dict[str, Any], field: str, value: str) -> None:
    aliases = {
        "Tieu chi": ("Tieu chi", "Tiêu chí", "TiÃªu chÃ­"),
        "Diem": ("Diem", "Điểm", "Äiá»ƒm"),
        "Cong thuc": ("Cong thuc", "Công thức", "CÃ´ng thá»©c"),
        "Dan chung": ("Dan chung", "Dẫn chứng", "Dáº«n chá»©ng"),
        "Giai thich": ("Giai thich", "Giải thích", "Giáº£i thÃ­ch"),
    }
    for key in aliases.get(field, (field,)):
        detail[key] = value


def _repair_detail_content(detail: dict[str, Any], breakdown: dict[str, Any]) -> None:
    criterion_name = _get_detail_value(detail, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­", "Criterion")
    formula = _get_detail_value(detail, "Cong thuc", "Công thức", "CÃ´ng thá»©c", "Formula")
    evidence = _get_detail_value(detail, "Dan chung", "Dẫn chứng", "Dáº«n chá»©ng", "Evidence")
    explanation = _get_detail_value(detail, "Giai thich", "Giải thích", "Giáº£i thÃ­ch", "Explanation")
    matched_signals = _as_string_list(breakdown.get("matched_signals"))
    missing_requirements = _as_string_list(breakdown.get("missing_requirements"))
    evidence_highlights = _as_string_list(breakdown.get("evidence_highlights"))
    verdict = str(breakdown.get("verdict") or "missing")

    repaired_formula = formula if formula and not _is_weak_formula(formula) else str(breakdown.get("mathematical_formula") or "")
    repaired_evidence = evidence if evidence and not _looks_generic_evidence(evidence) else _build_evidence_summary(
        criterion_name,
        evidence_highlights,
        matched_signals,
        missing_requirements,
    )
    repaired_explanation = explanation if explanation and not _looks_generic_explanation(explanation) else _build_detail_explanation(
        criterion_name=criterion_name,
        verdict=verdict,
        matched_signals=matched_signals,
        missing_requirements=missing_requirements,
    )

    _set_detail_field(detail, "Cong thuc", repaired_formula)
    _set_detail_field(detail, "Dan chung", repaired_evidence)
    _set_detail_field(detail, "Giai thich", repaired_explanation)


def _refresh_candidate_summary(analysis: dict[str, Any]) -> None:
    raw_details = analysis.get("Chi tiet") or analysis.get("Chi tiết") or analysis.get("Chi tiáº¿t") or []
    details = [item for item in raw_details if isinstance(item, dict)] if isinstance(raw_details, list) else []
    strengths: list[str] = []
    weaknesses: list[str] = []

    for detail in details:
        criterion_name = _get_detail_value(detail, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­")
        breakdown = _as_advanced_dict(detail.get("advancedBreakdown") or detail.get("advanced_breakdown"))
        verdict = str(breakdown.get("verdict") or "missing")
        matched_signals = _as_string_list(breakdown.get("matched_signals"))
        missing_requirements = _as_string_list(breakdown.get("missing_requirements"))

        if verdict == "strong":
            message = criterion_name
            if matched_signals:
                message = f"{criterion_name}: {matched_signals[0]}"
            if message not in strengths:
                strengths.append(message)
        elif verdict in {"weak", "missing"}:
            message = criterion_name
            if missing_requirements:
                message = f"{criterion_name}: {missing_requirements[0]}"
            if message not in weaknesses:
                weaknesses.append(message)

    if not strengths and details:
        best_detail = max(
            details,
            key=lambda item: _score_ratio(
                *_parse_score_pair(
                    _get_detail_value(item, "Diem", "Điểm", "Äiá»ƒm"),
                    _get_detail_value(item, "Cong thuc", "Công thức", "CÃ´ng thá»©c"),
                )
            ),
        )
        best_name = _get_detail_value(best_detail, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­")
        if best_name:
            strengths.append(best_name)

    if not weaknesses and details:
        weakest_detail = min(
            details,
            key=lambda item: _score_ratio(
                *_parse_score_pair(
                    _get_detail_value(item, "Diem", "Điểm", "Äiá»ƒm"),
                    _get_detail_value(item, "Cong thuc", "Công thức", "CÃ´ng thá»©c"),
                )
            ),
        )
        weakest_name = _get_detail_value(weakest_detail, "Tieu chi", "Tiêu chí", "TiÃªu chÃ­")
        if weakest_name:
            weaknesses.append(weakest_name)

    analysis["Diem manh CV"] = strengths[:4]
    analysis["Diem yeu CV"] = weaknesses[:3]


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


def normalize_candidates_against_weights(
    candidates: List[Dict[str, Any]],
    weights: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return _post_process_candidates(candidates, weights)


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
            _repair_detail_content(detail, detail["advancedBreakdown"])
        analysis["Chi tiet"] = details
        analysis["Chi tiết"] = details
        analysis["Chi tiáº¿t"] = details
        _refresh_candidate_summary(analysis)
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


def _analysis_generation_config(*, include_schema: bool) -> dict[str, Any]:
    config: dict[str, Any] = {
        "responseMimeType": "application/json",
        "temperature": 0.1,
        "topP": 0.8,
        "topK": 40,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if include_schema:
        config["responseSchema"] = _analysis_response_schema()
    return config


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
    prompt_text = "\n\n".join(prompt_sections)

    try:
        response_text = generate_content(
            settings.gemini_cv_analysis_model,
            prompt_text,
            _analysis_generation_config(include_schema=True),
        )
    except Exception as error:
        print(f"[CV Analysis] Schema-guided generation failed, retrying JSON-only mode: {error}")
        response_text = generate_content(
            settings.gemini_cv_analysis_model,
            prompt_text,
            _analysis_generation_config(include_schema=False),
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
    prompt_text = "\n\n".join(prompt_sections)

    try:
        response_text = await asyncio.to_thread(
            generate_content,
            settings.gemini_cv_analysis_model,
            prompt_text,
            _analysis_generation_config(include_schema=True),
        )
    except Exception as error:
        print(f"[CV Analysis] Async schema-guided generation failed, retrying JSON-only mode: {error}")
        response_text = await asyncio.to_thread(
            generate_content,
            settings.gemini_cv_analysis_model,
            prompt_text,
            _analysis_generation_config(include_schema=False),
        )

    return _post_process_candidates(_extract_json_array(response_text), weights)
