from __future__ import annotations

from typing import Any


PIPELINE_VERSION = "cv-analysis-v2"
MODEL_ARTIFACT_SCHEMA_VERSION = "supporthr-classifier-manifest-v1"
EXEMPLAR_SCHEMA_VERSION = "supporthr-exemplar-v2"
DEFAULT_RUBRIC_VERSION = "v2"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
DEFAULT_EMBEDDING_DIMENSION = 768
DEFAULT_VECTOR_INDEX_VERSION = "gemini-embedding-2-768-v1"

RANK_A_MIN_SCORE = 75.0
RANK_B_MIN_SCORE = 50.0


def rank_from_score(score: Any) -> str:
    try:
        normalized = max(0.0, min(100.0, float(score)))
    except (TypeError, ValueError):
        normalized = 0.0
    if normalized >= RANK_A_MIN_SCORE:
        return "A"
    if normalized >= RANK_B_MIN_SCORE:
        return "B"
    return "C"


def embedding_prompt(text: str, *, task: str = "semantic_similarity", title: str = "none") -> str:
    """Apply Gemini Embedding 2 text instructions in one canonical place."""
    content = " ".join(str(text or "").split()).strip()
    normalized_task = str(task or "semantic_similarity").strip().lower()
    if normalized_task == "retrieval_query":
        return f"task: search result | query: {content}"
    if normalized_task == "retrieval_document":
        return f"title: {title or 'none'} | text: {content}"
    if normalized_task == "classification":
        return f"task: classification | input: {content}"
    return f"task: sentence similarity | query: {content}"


def is_current_vector_contract(
    *,
    model: Any,
    dimension: Any,
    index_version: Any,
    expected_model: str = DEFAULT_EMBEDDING_MODEL,
    expected_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
    expected_index_version: str = DEFAULT_VECTOR_INDEX_VERSION,
) -> bool:
    try:
        parsed_dimension = int(dimension)
    except (TypeError, ValueError):
        return False
    return (
        str(model or "").strip() == expected_model
        and parsed_dimension == expected_dimension
        and str(index_version or "").strip() == expected_index_version
    )
