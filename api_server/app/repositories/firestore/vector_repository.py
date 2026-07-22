from __future__ import annotations

from app.core.config import get_settings
from app.integrations.firebase_admin import get_firestore_client


def db():
    if get_settings().data_provider == "supabase":
        from app.repositories.postgres.document_store import PostgresDocumentDatabase

        return PostgresDocumentDatabase()
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
    """Run server-side ANN search. Firestore requires a matching composite vector index."""
    if get_settings().data_provider == "supabase":
        from app.integrations.postgres import get_postgres_pool

        vector_text = "[" + ",".join(str(float(value)) for value in query_vector) + "]"
        with get_postgres_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select id, payload, 1 - (embedding <=> %s::vector) as similarity
                    from public.approved_exemplars
                    where embedding is not null
                      and approved = true
                      and status = 'approved'
                      and rubric_version = %s
                      and vector_index_version = %s
                      and 1 - (embedding <=> %s::vector) >= %s
                    order by embedding <=> %s::vector
                    limit %s
                    """,
                    (
                        vector_text,
                        rubric_version,
                        vector_index_version,
                        vector_text,
                        similarity_threshold,
                        vector_text,
                        limit,
                    ),
                )
                rows = cursor.fetchall()
        records: list[dict] = []
        for document_id, payload, similarity in rows:
            record = dict(payload or {})
            record["_id"] = document_id
            record["similarity"] = float(similarity or 0.0)
            records.append(record)
        return records

    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
    from google.cloud.firestore_v1.base_query import FieldFilter
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
    for doc in vector_query.stream():
        data = doc.to_dict() or {}
        data["_id"] = doc.id
        distance = float(data.pop("_vectorDistance", 1.0) or 0.0)
        data["similarity"] = max(-1.0, min(1.0, 1.0 - distance))
        records.append(data)
    return records
