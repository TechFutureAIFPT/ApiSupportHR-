from __future__ import annotations

from app.integrations.postgres import get_postgres_pool
from app.repositories.postgres.document_store import PostgresDocumentDatabase


def vector_library(collection_name: str):
    return PostgresDocumentDatabase().collection(collection_name)


def find_nearest_approved_exemplars(
    *,
    collection_name: str,
    query_vector: list[float],
    rubric_version: str,
    vector_index_version: str,
    limit: int,
    similarity_threshold: float,
) -> list[dict]:
    """Run server-side pgvector cosine search against approved Supabase exemplars."""
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
