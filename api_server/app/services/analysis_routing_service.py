from __future__ import annotations

import asyncio
import copy
import re
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import get_settings
from app.services.gemini_service import generate_content
from app.services.local_classifier_service import classify_cv_text


DEFAULT_ROUTING_METADATA: dict[str, Any] = {
    "routing_analysis": {
        "predicted_industry": "unknown",
        "confidence_score": 0.0,
    },
    "mathematical_match": {
        "vocab_similarity_score": 0.5,
        "core_keywords_found": [],
        "missing_critical_keywords": [],
    },
}

MAX_KEYWORDS = 12


def default_routing_metadata() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_ROUTING_METADATA)


def _normalize_technical_text(value: str) -> str:
    text = str(value or "").lower()
    replacements = {
        "c#": "csharp",
        "c++": "cpp",
        ".net": "dotnet",
        "node.js": "nodejs",
        "react.js": "reactjs",
        "vue.js": "vuejs",
        "next.js": "nextjs",
    }
    for source, target in replacements.items():
        text = text.replace(source, f" {target} ")
    text = re.sub(r"[^a-z0-9+#.\s-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_section(translated: str, marker: str) -> str:
    pattern = rf"\[{marker}\](.*?)\[/{marker}\]"
    match = re.search(pattern, translated or "", flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _translate_to_technical_english(jd_text: str, cv_text: str) -> tuple[str, str]:
    settings = get_settings()
    prompt = (
        "Translate the following Vietnamese recruiting documents into concise technical English.\n"
        "Do not analyze, summarize, score, infer, or add information.\n"
        "Preserve technical terms, product names, numbers, dates, degrees, roles, and bullet structure.\n"
        "Return only the translated text inside these exact markers:\n"
        "[JD_EN]\n<translated job description>\n[/JD_EN]\n"
        "[CV_EN]\n<translated curriculum vitae>\n[/CV_EN]\n\n"
        f"JOB DESCRIPTION:\n{jd_text}\n\n"
        f"CURRICULUM VITAE:\n{cv_text}"
    )
    translated = generate_content(
        settings.gemini_default_model,
        prompt,
        {
            "temperature": 0.1,
            "topP": 0.6,
            "topK": 10,
        },
    )
    jd_en = _extract_section(translated, "JD_EN")
    cv_en = _extract_section(translated, "CV_EN")
    return jd_en or jd_text, cv_en or cv_text


def _tfidf_match_metadata(jd_english: str, cv_english: str) -> dict[str, Any]:
    jd_clean = _normalize_technical_text(jd_english)
    cv_clean = _normalize_technical_text(cv_english)
    if not jd_clean or not cv_clean:
        return copy.deepcopy(DEFAULT_ROUTING_METADATA["mathematical_match"])

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=8000,
        min_df=1,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9+#.\-]{1,}\b",
    )
    matrix = vectorizer.fit_transform([jd_clean, cv_clean])
    similarity = float(cosine_similarity(matrix[0], matrix[1])[0][0])

    feature_names = vectorizer.get_feature_names_out()
    jd_scores = matrix[0].toarray()[0]
    cv_scores = matrix[1].toarray()[0]
    ranked_indexes = sorted(
        (index for index, score in enumerate(jd_scores) if score > 0),
        key=lambda index: jd_scores[index],
        reverse=True,
    )

    found: list[str] = []
    missing: list[str] = []
    for index in ranked_indexes:
        keyword = str(feature_names[index]).strip()
        if not keyword or len(keyword) < 2:
            continue
        target = found if cv_scores[index] > 0 else missing
        if keyword not in target:
            target.append(keyword)
        if len(found) >= MAX_KEYWORDS and len(missing) >= MAX_KEYWORDS:
            break

    return {
        "vocab_similarity_score": round(max(0.0, min(1.0, similarity)), 4),
        "core_keywords_found": found[:MAX_KEYWORDS],
        "missing_critical_keywords": missing[:MAX_KEYWORDS],
    }


def build_routing_metadata(
    jd_text: str,
    cv_text: str,
    *,
    classifier_result: dict[str, Any] | None = None,
    translate: bool = True,
) -> dict[str, Any]:
    if translate:
        try:
            jd_english, cv_english = _translate_to_technical_english(jd_text, cv_text)
        except Exception:
            jd_english, cv_english = jd_text, cv_text
    else:
        jd_english, cv_english = jd_text, cv_text

    if classifier_result is None:
        try:
            classifier_result = classify_cv_text(cv_english, top_k=5)
        except Exception:
            return default_routing_metadata()

    predicted_industry = str(classifier_result.get("predicted_label") or "unknown").strip() or "unknown"
    confidence = classifier_result.get("confidence")
    if not isinstance(confidence, (int, float)):
        top_predictions = classifier_result.get("top_predictions") or []
        if top_predictions and isinstance(top_predictions[0], dict):
            confidence = top_predictions[0].get("score")
    confidence_score = float(confidence) if isinstance(confidence, (int, float)) else 0.0

    try:
        mathematical_match = _tfidf_match_metadata(jd_english, cv_english)
    except Exception:
        mathematical_match = copy.deepcopy(DEFAULT_ROUTING_METADATA["mathematical_match"])

    return {
        "routing_analysis": {
            "predicted_industry": predicted_industry,
            "confidence_score": round(max(0.0, min(1.0, confidence_score)), 4),
        },
        "mathematical_match": mathematical_match,
    }


async def build_routing_metadata_async(
    jd_text: str,
    cv_text: str,
    *,
    classifier_result: dict[str, Any] | None = None,
    translate: bool = True,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        build_routing_metadata,
        jd_text,
        cv_text,
        classifier_result=classifier_result,
        translate=translate,
    )
