from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
from typing import Any

from app.core.ai_contract import EXEMPLAR_SCHEMA_VERSION, is_current_vector_contract
from app.repositories.firestore import account_repository as repo
from app.repositories.firestore import vector_repository as vector_repo
from app.schemas.account import AuthenticatedUser
from app.services.account.history_service import fetch_recent_history
from app.services.gemini_service import embed_text
from app.services.local_classifier_service import classify_cv_text
from app.services.vector_store_service import search_similar_records
from app.core.config import get_settings
from app.utils.text_normalization import normalize_display_text


SUPPORTED_COLLECTION_KEYS = ("it", "sales", "marketing", "design")
LABEL_TO_COLLECTION_KEYS: dict[str, list[str]] = {
    "INFORMATION-TECHNOLOGY": ["it"],
    "ENGINEERING": ["it"],
    "DESIGNER": ["design"],
    "APPAREL": ["design"],
    "ARTS": ["design"],
    "DIGITAL-MEDIA": ["marketing", "design"],
    "PUBLIC-RELATIONS": ["marketing"],
    "SALES": ["sales"],
    "BUSINESS-DEVELOPMENT": ["sales", "marketing"],
}
COLLECTION_KEYWORDS: dict[str, list[str]] = {
    "it": [
        "software",
        "developer",
        "engineer",
        "backend",
        "frontend",
        "fullstack",
        "devops",
        "data engineer",
        "data scientist",
        "python",
        "java",
        "react",
        "node",
        "sql",
        "machine learning",
        "ai",
    ],
    "sales": [
        "sales",
        "business development",
        "account manager",
        "account executive",
        "kinh doanh",
        "ban hang",
        "sale",
    ],
    "marketing": [
        "marketing",
        "seo",
        "social media",
        "content",
        "brand",
        "digital",
        "truyen thong",
        "pr",
    ],
    "design": [
        "design",
        "designer",
        "ui/ux",
        "ux/ui",
        "figma",
        "photoshop",
        "illustrator",
        "creative",
        "thiet ke",
    ],
}
MIN_EXEMPLAR_SIMILARITY = 0.72
MAX_HISTORY_LOOKBACK = 50
MAX_EXEMPLARS = 2
MAX_TOP_PREDICTIONS = 3


def _normalize_file_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_lookup_key(value: str) -> str:
    normalized = normalize_display_text(value)
    decomposed = unicodedata.normalize("NFD", normalized)
    ascii_text = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    ascii_text = ascii_text.replace("Đ", "D").replace("đ", "d")
    return re.sub(r"\s+", " ", ascii_text.strip().lower())


def _pick_value(record: dict[str, Any], *keys: str) -> Any:
    alias_set = {_normalize_lookup_key(key) for key in keys}
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
    for key, value in record.items():
        if value in (None, ""):
            continue
        if _normalize_lookup_key(str(key)) in alias_set:
            return value
    return None


def _as_float(value: Any) -> float | None:
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


def _extract_grade(candidate: dict[str, Any]) -> str:
    analysis = candidate.get("analysis") or {}
    return str(
        _pick_value(
            analysis,
            "Hạng",
            "Hang",
        )
        or "C"
    )


def _extract_total_score(candidate: dict[str, Any]) -> float:
    analysis = candidate.get("analysis") or {}
    return float(
        _as_float(
            _pick_value(
                analysis,
                "Tổng điểm",
                "Tong diem",
            )
        )
        or 0.0
    )


def _extract_details(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = candidate.get("analysis") or {}
    details = _pick_value(analysis, "Chi tiết", "Chi tiet")
    return [item for item in details if isinstance(item, dict)] if isinstance(details, list) else []


def _extract_strengths(candidate: dict[str, Any]) -> list[str]:
    analysis = candidate.get("analysis") or {}
    strengths = _pick_value(
        analysis,
        "Điểm mạnh CV",
        "Diem manh CV",
    )
    return [str(item).strip() for item in strengths if str(item).strip()] if isinstance(strengths, list) else []


def _extract_weaknesses(candidate: dict[str, Any]) -> list[str]:
    analysis = candidate.get("analysis") or {}
    weaknesses = _pick_value(
        analysis,
        "Điểm yếu CV",
        "Diem yeu CV",
    )
    return [str(item).strip() for item in weaknesses if str(item).strip()] if isinstance(weaknesses, list) else []


def _extract_jd_fit(details: list[dict[str, Any]]) -> float | None:
    for detail in details:
        criterion = str(
            _pick_value(detail, "Tiêu chí", "Tieu chi")
            or ""
        ).strip()
        if not criterion:
            continue
        if criterion.lower().startswith("phù hợp jd") or criterion.lower().startswith("phu hop jd"):
            return _as_float(_pick_value(detail, "Điểm", "Diem"))
    return None


def _summarize_details(details: list[dict[str, Any]], limit_count: int = 2) -> list[str]:
    summaries: list[tuple[float, str]] = []
    for detail in details:
        criterion = str(
            _pick_value(detail, "Tiêu chí", "Tieu chi")
            or ""
        ).strip()
        score_text = str(_pick_value(detail, "Điểm", "Diem") or "").strip()
        evidence = str(
            _pick_value(detail, "Dẫn chứng", "Dan chung")
            or ""
        ).strip()
        if not criterion:
            continue
        score_value = _as_float(score_text) or 0.0
        summary = f"{criterion}: {score_text or '0'}"
        if evidence:
            summary = f"{summary} | bằng chứng: {evidence[:180]}"
        summaries.append((score_value, summary))
    summaries.sort(key=lambda item: item[0], reverse=True)
    return [summary for _, summary in summaries[:limit_count]]


def _infer_collection_keys_from_text(cv_text: str) -> list[str]:
    lower = cv_text.lower()
    inferred: list[str] = []
    for collection_key, keywords in COLLECTION_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            inferred.append(collection_key)
    return inferred


def infer_collection_keys(cv_text: str, top_predictions: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for prediction in top_predictions[:MAX_TOP_PREDICTIONS]:
        label = str(prediction.get("label") or "").strip().upper()
        for collection_key in LABEL_TO_COLLECTION_KEYS.get(label, []):
            if collection_key in SUPPORTED_COLLECTION_KEYS and collection_key not in keys:
                keys.append(collection_key)
    for collection_key in _infer_collection_keys_from_text(cv_text):
        if collection_key not in keys:
            keys.append(collection_key)
    return keys[:3]


def _build_history_exemplar_index(user: AuthenticatedUser) -> dict[str, list[dict[str, Any]]]:
    history_items = fetch_recent_history(user, limit_count=MAX_HISTORY_LOOKBACK)
    index: dict[str, list[dict[str, Any]]] = {}

    for item in history_items:
        full_payload = item.get("fullPayload") or {}
        job_position = str(full_payload.get("jobPosition") or item.get("jobPosition") or "").strip()
        jd_text = str(full_payload.get("jdText") or "").strip()
        candidates = full_payload.get("candidates") or []
        if not isinstance(candidates, list):
            continue

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("status") or "").upper() == "FAILED":
                continue

            file_name = str(candidate.get("fileName") or "").strip()
            normalized_name = _normalize_file_name(file_name)
            if not normalized_name:
                continue

            details = _extract_details(candidate)
            exemplar = {
                "fileName": file_name,
                "jobPosition": job_position,
                "jdTextSnippet": jd_text[:240],
                "grade": _extract_grade(candidate),
                "score": _extract_total_score(candidate),
                "jdFit": _extract_jd_fit(details),
                "strengths": _extract_strengths(candidate)[:3],
                "weaknesses": _extract_weaknesses(candidate)[:2],
                "detailHighlights": _summarize_details(details, limit_count=2),
            }
            index.setdefault(normalized_name, []).append(exemplar)

    for normalized_name, exemplars in index.items():
        exemplars.sort(
            key=lambda item: (
                0 if item["grade"] == "A" else 1 if item["grade"] == "B" else 2,
                -float(item["score"] or 0.0),
            )
        )
        index[normalized_name] = exemplars

    return index


def _merge_vector_matches(
    collection_keys: list[str],
    cv_text: str,
    *,
    owner_uid: str,
    query_vector: list[float] | None,
    exclude_file_names: list[str] | None,
) -> list[dict[str, Any]]:
    if not query_vector:
        return []

    merged: dict[str, dict[str, Any]] = {}
    for collection_key in collection_keys:
        result = search_similar_records(
            collection_key,
            cv_text,
            top_k=5,
            min_similarity=MIN_EXEMPLAR_SIMILARITY,
            query_vector=query_vector,
            owner_uid=owner_uid,
            exclude_file_names=exclude_file_names,
        )
        if not result:
            continue

        for match in result.get("topMatches", []):
            metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
            file_name = str(metadata.get("fileName") or match.get("name") or "").strip()
            if not file_name:
                continue

            key = _normalize_file_name(file_name)
            current = merged.get(key)
            candidate_payload = {
                "fileName": file_name,
                "similarity": float(match.get("similarity") or 0.0),
                "collectionKey": collection_key,
                "relativePath": str(match.get("relativePath") or ""),
            }
            if current is None or candidate_payload["similarity"] > current["similarity"]:
                merged[key] = candidate_payload

    return sorted(merged.values(), key=lambda item: item["similarity"], reverse=True)


def _format_example_block(index: int, exemplar: dict[str, Any], vector_match: dict[str, Any]) -> str:
    lines = [
        f"Example {index}",
        f"- similarity: {vector_match['similarity']:.3f}",
        f"- collection: {vector_match['collectionKey']}",
        f"- prior job position: {exemplar['jobPosition'] or 'unknown'}",
        f"- prior score: {exemplar['score']:.1f}",
        f"- prior grade: {exemplar['grade']}",
    ]
    if exemplar.get("jdFit") is not None:
        lines.append(f"- prior jd fit: {float(exemplar['jdFit']):.1f}")
    if exemplar.get("strengths"):
        lines.append(f"- strengths: {', '.join(exemplar['strengths'])}")
    if exemplar.get("weaknesses"):
        lines.append(f"- weaknesses: {', '.join(exemplar['weaknesses'])}")
    if exemplar.get("detailHighlights"):
        lines.append("- detail highlights:")
        for highlight in exemplar["detailHighlights"]:
            lines.append(f"  * {highlight}")
    if exemplar.get("jdTextSnippet"):
        lines.append(f"- prior jd snippet: {exemplar['jdTextSnippet'][:180]}")
    return "\n".join(lines)


def build_grounding_context(
    *,
    user: AuthenticatedUser | None,
    cv_text: str,
    analysis_text: str,
    file_name: str,
    exclude_file_names: list[str] | None = None,
) -> dict[str, Any]:
    classifier_result: dict[str, Any] | None = None
    try:
        classifier_result = classify_cv_text(cv_text or analysis_text, top_k=MAX_TOP_PREDICTIONS)
    except Exception:
        classifier_result = None

    top_predictions = list((classifier_result or {}).get("top_predictions") or [])
    collection_keys = infer_collection_keys(analysis_text, top_predictions)

    exemplars: list[dict[str, Any]] = []
    vector_matches: list[dict[str, Any]] = []
    if user and collection_keys:
        query_vector: list[float] | None = None
        cleaned_analysis_text = _normalize_text(analysis_text)[:6000]
        if cleaned_analysis_text:
            try:
                query_vector = embed_text(cleaned_analysis_text, get_settings().gemini_embedding_model)
            except Exception:
                query_vector = None

        history_index = _build_history_exemplar_index(user)
        vector_matches = _merge_vector_matches(
            collection_keys,
            cleaned_analysis_text,
            owner_uid=user.uid,
            query_vector=query_vector,
            exclude_file_names=exclude_file_names,
        )

        for vector_match in vector_matches:
            matching_exemplars = history_index.get(_normalize_file_name(vector_match["fileName"])) or []
            if not matching_exemplars:
                continue

            best_exemplar = matching_exemplars[0]
            if float(best_exemplar.get("score") or 0.0) < 50:
                continue
            exemplars.append(
                {
                    **best_exemplar,
                    "similarity": vector_match["similarity"],
                    "collectionKey": vector_match["collectionKey"],
                }
            )
            if len(exemplars) >= MAX_EXEMPLARS:
                break

    prediction_summary = [
        f"{str(item.get('label') or '')}:{float(item.get('score') or 0.0):.3f}"
        for item in top_predictions
        if item.get("label")
    ]
    entry_notes = [
        "Dùng local classifier như gợi ý mềm, không xem là kết luận tuyệt đối.",
    ]
    if prediction_summary:
        entry_notes.append(f"Classifier hints: {', '.join(prediction_summary)}")
    if collection_keys:
        entry_notes.append(f"Grounding collections ưu tiên: {', '.join(collection_keys)}")
    if exemplars:
        entry_notes.append(
            "Có exemplar lịch sử đã được phân tích. Chỉ dùng để canh chỉnh cách lập luận, "
            "không sao chép máy móc."
        )

    few_shot_examples = "\n\n".join(
        _format_example_block(index + 1, exemplar, exemplar)
        for index, exemplar in enumerate(exemplars)
    )
    return {
        "classifier": classifier_result,
        "collection_keys": collection_keys,
        "entry_note": "\n".join(entry_notes).strip(),
        "few_shot_examples": few_shot_examples.strip(),
        "exemplars": exemplars,
    }


def _normalize_lookup(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _as_vector(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    vector: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            return None
        vector.append(float(item))
    return vector


def _cosine_similarity(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return None
    return dot / (norm_a * norm_b)


def _nested_value(record: dict[str, Any], *keys: str) -> Any:
    current: Any = record
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_record_value(record: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        parts = path.split(".")
        value = _nested_value(record, *parts) if len(parts) > 1 else record.get(path)
        if value not in (None, "", []):
            return value
    return None


def _redact_pii(text: str) -> str:
    redacted = str(text or "")
    redacted = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[EMAIL]", redacted, flags=re.I)
    redacted = re.sub(r"(?:\+?\d[\d\s().-]{7,}\d)", "[PHONE]", redacted)
    redacted = re.sub(r"https?://\S+|www\.\S+", "[URL]", redacted, flags=re.I)
    redacted = re.sub(
        r"\b(name|full name|candidate|ho ten|họ tên)\s*[:\-]\s*[^\n\r]{1,80}",
        r"\1: [REDACTED]",
        redacted,
        flags=re.I,
    )
    return _normalize_text(redacted)


def _compact_json(value: Any, max_chars: int = 2800) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        rendered = json.dumps(str(value), ensure_ascii=False)
    return rendered[:max_chars]


def _approved_collection_ref():
    settings = get_settings()
    collection_name = settings.approved_exemplars_collection or "approvedExemplars"
    return repo.db().collection(collection_name)


def _fetch_approved_records(rubric_version: str) -> list[dict[str, Any]]:
    settings = get_settings()
    collection_ref = _approved_collection_ref()
    try:
        docs = list(
            collection_ref
            .where("status", "==", "approved")
            .where("approved", "==", True)
            .where("rubricVersion", "==", rubric_version)
            .where("vectorIndexVersion", "==", settings.vector_index_version)
            .limit(settings.rag_candidate_limit)
            .stream()
        )
    except Exception:
        # Bounded compatibility path; records still pass strict local contract checks.
        docs = list(collection_ref.limit(settings.rag_candidate_limit).stream())

    records: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        data["_id"] = doc.id
        records.append(data)
    return records


def _is_approved(record: dict[str, Any]) -> bool:
    explicit = record.get("approved")
    status = _normalize_lookup(str(record.get("status") or record.get("state") or ""))
    return explicit is True and status == "approved"


def _record_vector(record: dict[str, Any]) -> list[float] | None:
    return (
        _as_vector(record.get("embedding"))
        or _as_vector(record.get("embeddingVector"))
        or _as_vector(record.get("vector"))
        or _as_vector(record.get("cvEmbedding"))
        or _as_vector(_first_record_value(record, "metadata.embedding", "metadata.vector"))
    )


def _record_industry_values(record: dict[str, Any]) -> list[str]:
    values = [
        _first_record_value(record, "industry", "industryKey", "collectionKey", "label", "metadata.industry"),
        _first_record_value(record, "category", "roleFamily", "metadata.collectionKey"),
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _build_industry_hints(
    analysis_text: str,
    top_predictions: list[dict[str, Any]],
    *,
    threshold: float,
) -> tuple[list[str], list[str]]:
    raw_labels: list[str] = []
    accepted_predictions: list[dict[str, Any]] = []
    for prediction in top_predictions[:MAX_TOP_PREDICTIONS]:
        label = str(prediction.get("label") or "").strip()
        score = float(prediction.get("score") or 0.0)
        if label and score >= threshold:
            raw_labels.append(label)
            accepted_predictions.append(prediction)

    collection_keys = infer_collection_keys(analysis_text, accepted_predictions)
    if not collection_keys:
        collection_keys = _infer_collection_keys_from_text(analysis_text)[:3]
    hints: list[str] = []
    for value in [*raw_labels, *collection_keys]:
        normalized = _normalize_lookup(value)
        if normalized and normalized not in {_normalize_lookup(item) for item in hints}:
            hints.append(value)
    return hints, collection_keys


def _industry_matches(record: dict[str, Any], hints: list[str]) -> bool:
    if not hints:
        return True
    normalized_hints = [_normalize_lookup(item) for item in hints if item]
    for value in _record_industry_values(record):
        normalized_value = _normalize_lookup(value)
        if any(hint in normalized_value or normalized_value in hint for hint in normalized_hints):
            return True
    return False


def _seniority_bucket(value: str) -> str:
    normalized = _normalize_lookup(value)
    if any(token in normalized for token in ("intern", "fresher", "thuc tap")):
        return "intern"
    if "junior" in normalized:
        return "junior"
    if any(token in normalized for token in ("senior", "sr", "cao cap")):
        return "senior"
    if any(token in normalized for token in ("lead", "leader", "truong nhom")):
        return "lead"
    if any(token in normalized for token in ("manager", "head", "director", "truong phong")):
        return "manager"
    if any(token in normalized for token in ("mid", "middle")):
        return "mid"
    return normalized


def _seniority_matches(record: dict[str, Any], target_seniority: str) -> bool:
    if not target_seniority:
        return True
    record_seniority = str(
        _first_record_value(record, "seniority", "experienceLevel", "level", "metadata.seniority")
        or ""
    )
    if not record_seniority:
        return True
    return _seniority_bucket(record_seniority) == _seniority_bucket(target_seniority)


def _job_title_matches(record: dict[str, Any], target_title: str) -> bool:
    if not target_title:
        return True
    record_title = str(_first_record_value(record, "jobTitle", "role", "position", "metadata.jobTitle") or "")
    if not record_title:
        return True
    target_tokens = {token for token in _normalize_lookup(target_title).split() if len(token) > 2}
    record_tokens = {token for token in _normalize_lookup(record_title).split() if len(token) > 2}
    if not target_tokens or not record_tokens:
        return True
    return bool(target_tokens & record_tokens)


def _rubric_matches(record: dict[str, Any], rubric_version: str) -> bool:
    record_version = str(_first_record_value(record, "rubricVersion", "rubric.version", "metadata.rubricVersion") or "")
    return record_version == rubric_version


def _schema_matches(record: dict[str, Any]) -> bool:
    schema_version = str(
        _first_record_value(record, "schemaVersion", "schema_version", "metadata.schemaVersion") or ""
    )
    return schema_version == EXEMPLAR_SCHEMA_VERSION


def _format_approved_example(index: int, exemplar: dict[str, Any]) -> str:
    analysis_json = (
        _first_record_value(exemplar, "analysisJson", "analysis_json", "analysis", "analysisData", "historicalAnalysis")
        or {}
    )
    redacted_text = (
        _first_record_value(exemplar, "redactedCvText", "redacted_cv_text", "cvTextRedacted", "redacted_text", "textSnippet")
        or ""
    )
    lines = [
        f"Approved exemplar {index}",
        f"- similarity: {float(exemplar.get('similarity') or 0.0):.3f}",
        f"- industry: {', '.join(_record_industry_values(exemplar)) or 'unknown'}",
        f"- seniority: {str(_first_record_value(exemplar, 'seniority', 'experienceLevel', 'level') or 'unknown')}",
        f"- job title: {str(_first_record_value(exemplar, 'jobTitle', 'role', 'position') or 'unknown')}",
        "- redacted CV snippet:",
        _redact_pii(str(redacted_text))[:1800] or "No redacted CV text stored.",
        "- approved analysis JSON:",
        _compact_json(analysis_json),
    ]
    return "\n".join(lines)


def _find_approved_exemplars(
    *,
    query_vector: list[float],
    industry_hints: list[str],
    target_seniority: str,
    target_job_title: str,
    rubric_version: str,
    max_items: int,
    similarity_threshold: float,
) -> list[dict[str, Any]]:
    settings = get_settings()
    try:
        retrieval_limit = min(
            int(settings.rag_candidate_limit),
            max(max_items * 10, max_items),
        )
        native_records = vector_repo.find_nearest_approved_exemplars(
            collection_name=settings.approved_exemplars_collection,
            query_vector=query_vector,
            rubric_version=rubric_version,
            vector_index_version=settings.vector_index_version,
            limit=retrieval_limit,
            similarity_threshold=similarity_threshold,
        )
        return [
            record for record in native_records
            if _is_approved(record)
            and _schema_matches(record)
            and _rubric_matches(record, rubric_version)
            and is_current_vector_contract(
                model=_first_record_value(record, "embeddingModel", "embedding_model"),
                dimension=_first_record_value(record, "embeddingDimension", "embedding_dimension"),
                index_version=_first_record_value(record, "vectorIndexVersion", "vector_index_version"),
                expected_model=settings.gemini_embedding_model,
                expected_dimension=settings.gemini_embedding_dimension,
                expected_index_version=settings.vector_index_version,
            )
            and _industry_matches(record, industry_hints)
            and _seniority_matches(record, target_seniority)
            and _job_title_matches(record, target_job_title)
        ][:max_items]
    except Exception:
        # Keep a bounded fallback for local tests and the index creation window.
        pass

    scored: list[dict[str, Any]] = []
    for record in _fetch_approved_records(rubric_version):
        if not _is_approved(record):
            continue
        if not _schema_matches(record):
            continue
        if not _rubric_matches(record, rubric_version):
            continue
        if not is_current_vector_contract(
            model=_first_record_value(record, "embeddingModel", "embedding_model"),
            dimension=_first_record_value(record, "embeddingDimension", "embedding_dimension"),
            index_version=_first_record_value(record, "vectorIndexVersion", "vector_index_version"),
            expected_model=settings.gemini_embedding_model,
            expected_dimension=settings.gemini_embedding_dimension,
            expected_index_version=settings.vector_index_version,
        ):
            continue
        if not _industry_matches(record, industry_hints):
            continue
        if not _seniority_matches(record, target_seniority):
            continue
        if not _job_title_matches(record, target_job_title):
            continue

        record_vector = _record_vector(record)
        similarity = _cosine_similarity(query_vector, record_vector or [])
        if similarity is None or similarity < similarity_threshold:
            continue
        scored.append({**record, "similarity": similarity})

    scored.sort(key=lambda item: float(item.get("similarity") or 0.0), reverse=True)
    return scored[:max_items]


async def build_approved_grounding_context(
    *,
    cv_text: str,
    analysis_text: str,
    file_name: str,
    hard_filters: dict[str, Any],
    jd_text: str,
    rubric_version: str | None = None,
    classifier_result: dict[str, Any] | None = None,
    query_vector: list[float] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if classifier_result is None:
        try:
            classifier_result = await asyncio.to_thread(classify_cv_text, cv_text or analysis_text, MAX_TOP_PREDICTIONS)
        except Exception as error:
            classifier_result = {
                "predicted_label": "",
                "confidence": None,
                "top_predictions": [],
                "model_source": "",
                "error": str(error),
            }

    top_predictions = list((classifier_result or {}).get("top_predictions") or [])
    industry_hints, collection_keys = _build_industry_hints(
        analysis_text,
        top_predictions,
        threshold=float(settings.local_classifier_confidence_threshold),
    )

    cleaned_analysis_text = _normalize_text(analysis_text or cv_text)[:6000]
    embedding_error = ""
    if query_vector is None and cleaned_analysis_text:
        try:
            query_vector = await asyncio.to_thread(
                embed_text,
                cleaned_analysis_text,
                settings.gemini_embedding_model,
                task="semantic_similarity",
            )
        except Exception as error:
            embedding_error = str(error)

    target_seniority = str(hard_filters.get("seniority") or hard_filters.get("level") or "").strip()
    target_job_title = str(
        hard_filters.get("jobTitle")
        or hard_filters.get("position")
        or hard_filters.get("role")
        or hard_filters.get("job_position")
        or ""
    ).strip()
    if not target_job_title:
        match = re.search(r"(?:position|role|title|vi tri|chuc danh)\s*[:\-]\s*([^\n\r]{3,120})", jd_text, re.I)
        if match:
            target_job_title = match.group(1).strip()

    exemplars: list[dict[str, Any]] = []
    retrieval_error = ""
    if query_vector:
        try:
            exemplars = await asyncio.to_thread(
                _find_approved_exemplars,
                query_vector=query_vector,
                industry_hints=industry_hints,
                target_seniority=target_seniority,
                target_job_title=target_job_title,
                rubric_version=rubric_version or settings.rubric_version,
                max_items=int(settings.rag_max_exemplars),
                similarity_threshold=float(settings.rag_similarity_threshold),
            )
        except Exception as error:
            retrieval_error = str(error)

    few_shot_examples = "\n\n".join(
        _format_approved_example(index + 1, exemplar)
        for index, exemplar in enumerate(exemplars)
    )
    prediction_summary = [
        f"{str(item.get('label') or '')}:{float(item.get('score') or 0.0):.3f}"
        for item in top_predictions
        if item.get("label")
    ]
    entry_notes = [
        "Use local classifier only as a routing hint, not as final evidence.",
        "Use approved RAG exemplars only when similarity passes the gate; never copy their scores blindly.",
    ]
    if prediction_summary:
        entry_notes.append(f"Local classifier top-k: {', '.join(prediction_summary)}")
    if industry_hints:
        entry_notes.append(f"Industry hints for RAG: {', '.join(industry_hints)}")
    if exemplars:
        top_similarity = max(float(item.get("similarity") or 0.0) for item in exemplars)
        entry_notes.append(f"Approved exemplar gate passed. Top similarity: {top_similarity:.3f}.")
    else:
        entry_notes.append("No approved exemplar passed the similarity gate; use zero-shot evaluation.")
    if embedding_error:
        entry_notes.append(f"Embedding fallback note: {embedding_error[:160]}")
    if retrieval_error:
        entry_notes.append(f"RAG retrieval fallback note: {retrieval_error[:160]}")

    return {
        "classifier": classifier_result,
        "collection_keys": collection_keys,
        "industry_hints": industry_hints,
        "entry_note": "\n".join(entry_notes).strip(),
        "few_shot_examples": few_shot_examples.strip(),
        "exemplars": exemplars,
        "rag_status": "few_shot" if exemplars else "zero_shot",
        "similarity_gate": float(settings.rag_similarity_threshold),
        "embedding_model": settings.gemini_embedding_model,
        "embedding_dimension": settings.gemini_embedding_dimension,
        "vector_index_version": settings.vector_index_version,
        "query_vector": query_vector,
        "embedding_error": embedding_error,
        "retrieval_error": retrieval_error,
    }
