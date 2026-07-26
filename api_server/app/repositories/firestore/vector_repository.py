from __future__ import annotations

from app.integrations.firebase_admin import get_firestore_client


def db():
    return get_firestore_client()


def vector_library(collection_name: str):
    return db().collection(collection_name)


def find_nearest_approved_exemplars(
    *,
    collection_name: str,
    query_vector: list[float],
    rubric_version: str,
    vector_index_version: str,
    limit: int,
    similarity_threshold: float,
) -> list[dict]:
    from google.cloud.firestore_v1.base_query import FieldFilter
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
    from google.cloud.firestore_v1.vector import Vector

    query = (
        vector_library(collection_name)
        .where(filter=FieldFilter("status", "==", "approved"))
        .where(filter=FieldFilter("approved", "==", True))
        .where(filter=FieldFilter("rubricVersion", "==", rubric_version))
        .where(filter=FieldFilter("vectorIndexVersion", "==", vector_index_version))
    )
    vector_query = query.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_vector),
        limit=limit,
        distance_measure=DistanceMeasure.COSINE,
        distance_result_field="_vectorDistance",
        distance_threshold=max(0.0, 1.0 - similarity_threshold),
    )
    records: list[dict] = []
    for snapshot in vector_query.stream():
        data = snapshot.to_dict() or {}
        data["_id"] = snapshot.id
        distance = float(data.pop("_vectorDistance", 1.0) or 0.0)
        data["similarity"] = max(-1.0, min(1.0, 1.0 - distance))
        records.append(data)
    return records
