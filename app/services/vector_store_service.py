from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.repositories.firestore import vector_repository as repo
from app.services.gemini_service import embed_text


def _normalize_collection_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (value or "").strip().lower()).strip("-")


def _clean_query_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())[:6000]


def _as_float_vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    vector: list[float] = []
    for item in value:
        try:
            vector.append(float(item))
        except Exception:
            return []
    return vector


def _cosine_similarity(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def similarity_to_bonus(avg: float) -> float:
    if avg >= 0.88:
        return 5.0
    if avg >= 0.83:
        return 3.5
    if avg >= 0.78:
        return 2.0
    if avg >= 0.72:
        return 1.0
    return 0.0


def _normalize_record(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or fallback_id),
        "name": str(raw.get("name") or ""),
        "role": str(raw.get("role") or ""),
        "relativePath": str(raw.get("relativePath") or ""),
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        "vector": _as_float_vector(raw.get("vector")),
    }


def _legacy_json_dir() -> Path:
    return Path(__file__).resolve().parents[2].parent / "frontend" / "public" / "data"


def _candidate_json_paths(collection_key: str, configured_dir: str) -> list[Path]:
    filename = f"{collection_key}-embeddings.json"
    paths = [Path(configured_dir) / filename, _legacy_json_dir() / filename]
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


@lru_cache(maxsize=32)
def _load_json_records(collection_key: str, configured_dir: str) -> list[dict[str, Any]]:
    for path in _candidate_json_paths(collection_key, configured_dir):
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("records", []) if isinstance(data, dict) else []
        normalized = [
            _normalize_record(record, fallback_id=f"{collection_key}-{index}")
            for index, record in enumerate(records)
            if isinstance(record, dict)
        ]
        return [record for record in normalized if record["vector"]]
    return []


def clear_vector_store_cache() -> None:
    _load_json_records.cache_clear()


def _load_firestore_records(
    collection_key: str,
    collection_name: str,
    *,
    owner_uid: str | None = None,
    exclude_file_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        docs = list(repo.vector_library(collection_name).where("collectionKey", "==", collection_key).stream())
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    for snapshot in docs:
        data = snapshot.to_dict() or {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if owner_uid and str(metadata.get("ownerUid") or data.get("ownerUid") or "") != owner_uid:
            continue
        record_file_name = str(metadata.get("fileName") or data.get("fileName") or "").strip().lower()
        if exclude_file_names and record_file_name and record_file_name in exclude_file_names:
            continue
        source_file_type = str(metadata.get("fileType") or data.get("fileType") or "").strip().lower()
        if source_file_type and source_file_type != "cv":
            continue
        normalized = _normalize_record(data, fallback_id=snapshot.id)
        if normalized["vector"]:
            records.append(normalized)
    return records


def _load_collection_records(
    collection_key: str,
    provider: str | None = None,
    *,
    owner_uid: str | None = None,
    exclude_file_names: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    settings = get_settings()
    preferred_provider = (provider or settings.vector_store_provider or "auto").strip().lower()
    if preferred_provider in {"auto", "firestore", "hybrid"}:
        records = _load_firestore_records(
            collection_key,
            settings.vector_store_firestore_collection,
            owner_uid=owner_uid,
            exclude_file_names=exclude_file_names,
        )
        if records:
            return "firestore", records
    records = _load_json_records(collection_key, settings.vector_store_json_dir)
    return "json", records


def search_similar_records(
    collection_key: str,
    query_text: str,
    *,
    top_k: int = 3,
    min_similarity: float = 0.0,
    provider: str | None = None,
    query_vector: list[float] | None = None,
    owner_uid: str | None = None,
    exclude_file_names: list[str] | None = None,
) -> dict[str, Any] | None:
    normalized_key = _normalize_collection_key(collection_key)
    cleaned_query = _clean_query_text(query_text)
    if not normalized_key or not cleaned_query:
        return None

    excluded_file_name_set = {
        str(value).strip().lower()
        for value in (exclude_file_names or [])
        if str(value).strip()
    }
    active_provider, records = _load_collection_records(
        normalized_key,
        provider=provider,
        owner_uid=owner_uid,
        exclude_file_names=excluded_file_name_set or None,
    )
    if not records:
        return None

    settings = get_settings()
    vector = query_vector or embed_text(cleaned_query, settings.gemini_embedding_model)
    if not vector:
        return None

    matches: list[dict[str, Any]] = []
    for record in records:
        similarity = _cosine_similarity(vector, record["vector"])
        if similarity is None or similarity < min_similarity:
            continue
        matches.append(
            {
                "id": record["id"],
                "name": record["name"],
                "role": record["role"],
                "relativePath": record["relativePath"],
                "metadata": record["metadata"],
                "similarity": similarity,
            }
        )

    matches.sort(key=lambda item: item["similarity"], reverse=True)
    top_matches = matches[: max(1, top_k)]
    if not top_matches:
        return None

    average = sum(item["similarity"] for item in top_matches) / len(top_matches)
    return {
        "collectionKey": normalized_key,
        "provider": active_provider,
        "queryModel": settings.gemini_embedding_model,
        "recordCount": len(records),
        "averageSimilarity": average,
        "topMatches": top_matches,
        "bonusPoints": similarity_to_bonus(average),
    }
