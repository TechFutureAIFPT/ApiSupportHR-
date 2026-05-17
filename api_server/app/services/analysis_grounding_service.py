from __future__ import annotations

import re
from typing import Any

from app.schemas.account import AuthenticatedUser
from app.services.account.history_service import fetch_recent_history
from app.services.gemini_service import embed_text
from app.services.local_classifier_service import classify_cv_text
from app.services.vector_store_service import search_similar_records
from app.core.config import get_settings


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


def _pick_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, ""):
            return record.get(key)
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
            "Háº¡ng",
            "HÃ¡ÂºÂ¡ng",
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
                "Tá»•ng Ä‘iá»ƒm",
                "TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m",
            )
        )
        or 0.0
    )


def _extract_details(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = candidate.get("analysis") or {}
    details = _pick_value(analysis, "Chi tiết", "Chi tiet", "Chi tiáº¿t", "Chi tiÃ¡ÂºÂ¿t")
    return [item for item in details if isinstance(item, dict)] if isinstance(details, list) else []


def _extract_strengths(candidate: dict[str, Any]) -> list[str]:
    analysis = candidate.get("analysis") or {}
    strengths = _pick_value(
        analysis,
        "Điểm mạnh CV",
        "Diem manh CV",
        "Äiá»ƒm máº¡nh CV",
        "Ã„ÂiÃ¡Â»Æ’m mÃ¡ÂºÂ¡nh CV",
    )
    return [str(item).strip() for item in strengths if str(item).strip()] if isinstance(strengths, list) else []


def _extract_weaknesses(candidate: dict[str, Any]) -> list[str]:
    analysis = candidate.get("analysis") or {}
    weaknesses = _pick_value(
        analysis,
        "Điểm yếu CV",
        "Diem yeu CV",
        "Äiá»ƒm yáº¿u CV",
        "Ã„ÂiÃ¡Â»Æ’m yÃ¡ÂºÂ¿u CV",
    )
    return [str(item).strip() for item in weaknesses if str(item).strip()] if isinstance(weaknesses, list) else []


def _extract_jd_fit(details: list[dict[str, Any]]) -> float | None:
    for detail in details:
        criterion = str(
            _pick_value(detail, "Tiêu chí", "Tieu chi", "TiÃªu chÃ­", "TiÃƒÂªu chÃƒÂ­")
            or ""
        ).strip()
        if not criterion:
            continue
        if criterion.lower().startswith("phù hợp jd") or criterion.lower().startswith("phu hop jd"):
            return _as_float(_pick_value(detail, "Điểm", "Diem", "Äiá»ƒm", "Ã„ÂiÃ¡Â»Æ’m"))
    return None


def _summarize_details(details: list[dict[str, Any]], limit_count: int = 2) -> list[str]:
    summaries: list[tuple[float, str]] = []
    for detail in details:
        criterion = str(
            _pick_value(detail, "Tiêu chí", "Tieu chi", "TiÃªu chÃ­", "TiÃƒÂªu chÃƒÂ­")
            or ""
        ).strip()
        score_text = str(_pick_value(detail, "Điểm", "Diem", "Äiá»ƒm", "Ã„ÂiÃ¡Â»Æ’m") or "").strip()
        evidence = str(
            _pick_value(detail, "Dẫn chứng", "Dan chung", "Dáº«n chá»©ng", "DÃ¡ÂºÂ«n chÃ¡Â»Â©ng")
            or ""
        ).strip()
        if not criterion:
            continue
        score_value = _as_float(score_text) or 0.0
        summary = f"{criterion}: {score_text or '0'}"
        if evidence:
            summary = f"{summary} | bang chung: {evidence[:180]}"
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
        "Dung local classifier nhu goi y mem, khong xem la ket luan tuyet doi.",
    ]
    if prediction_summary:
        entry_notes.append(f"Classifier hints: {', '.join(prediction_summary)}")
    if collection_keys:
        entry_notes.append(f"Grounding collections uu tien: {', '.join(collection_keys)}")
    if exemplars:
        entry_notes.append(
            "Co exemplar lich su da duoc phan tich. Chi dung de canh chinh cach lap luan, "
            "khong sao chep may moc."
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
