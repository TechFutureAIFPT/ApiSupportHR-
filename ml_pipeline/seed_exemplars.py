from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from supporthr_ml.contracts import stable_id
from supporthr_ml.privacy import redact_pii as redact_pii_report


SCHEMA_VERSION = "supporthr-exemplar-v2"
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSION = 768
VECTOR_INDEX_VERSION = "gemini-embedding-2-768-v1"
RUBRIC_VERSION = "v2"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def redact_pii(value: str) -> str:
    return redact_pii_report(value).text


def value(row: dict[str, Any], *aliases: str) -> str:
    normalized = {re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_"): item for key, item in row.items()}
    for alias in aliases:
        item = normalized.get(alias)
        if item not in (None, ""):
            return str(item)
    return ""


def records(
    csv_path: Path,
    *,
    status: str,
    limit: int | None,
    source_license: str,
    reviewer: str,
    review_reference: str,
) -> Iterable[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        emitted = 0
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            cv = value(row, "resume_text", "resume", "cv_text", "cv")
            jd = value(row, "job_text", "jd_text", "job_description", "jd", "description")
            if not cv or not jd:
                continue
            cv_redaction = redact_pii_report(cv)
            jd_redaction = redact_pii_report(jd)
            if not cv_redaction.safe_for_release or not jd_redaction.safe_for_release:
                raise ValueError(f"PII remained after redaction at source row {row_number}.")
            redacted = cv_redaction.text
            redacted_jd = jd_redaction.text
            doc_id = stable_id(redacted, redacted_jd, RUBRIC_VERSION)
            yield {
                "id": doc_id,
                "schemaVersion": SCHEMA_VERSION,
                "status": status,
                "approved": status == "approved",
                "rubricVersion": RUBRIC_VERSION,
                "roleKey": clean(value(row, "role_key")),
                "industry": clean(value(row, "category", "industry", "label")) or "unknown",
                "seniority": clean(value(row, "seniority", "level", "experience_level")) or "unknown",
                "jobTitle": clean(value(row, "job_title", "position", "role")),
                "redactedCvText": redacted,
                "jdSnapshot": redacted_jd,
                "analysisJson": {
                    "source": csv_path.name,
                    "sourceRow": row_number,
                    "sourceLicense": source_license,
                    "review": {
                        "reviewer": reviewer,
                        "reference": review_reference,
                        "required": status == "approved",
                    },
                },
                "redactionReport": {
                    "version": cv_redaction.version,
                    "cvCounts": cv_redaction.counts,
                    "jdCounts": jd_redaction.counts,
                    "safeForRelease": True,
                },
                "embeddingModel": EMBEDDING_MODEL,
                "embeddingDimension": EMBEDDING_DIMENSION,
                "vectorIndexVersion": VECTOR_INDEX_VERSION,
            }
            emitted += 1
            if limit and emitted >= limit:
                return


def attach_embedding(record: dict[str, Any], client: Any) -> dict[str, Any]:
    prompt = f"task: sentence similarity | query: {record['redactedCvText'][:12000]}"
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=prompt,
        config={"output_dimensionality": EMBEDDING_DIMENSION},
    )
    vector = [float(item) for item in response.embeddings[0].values]
    if len(vector) != EMBEDDING_DIMENSION:
        raise RuntimeError(f"Expected {EMBEDDING_DIMENSION} values; received {len(vector)}")
    record["embedding"] = vector
    return record


def payload_checksum(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or seed canonical SupportHR RAG exemplars.")
    parser.add_argument("--data-csv", required=True)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--status", choices=("pending", "approved"), default="pending")
    parser.add_argument("--allow-approved", action="store_true")
    parser.add_argument("--confirm-reviewed", action="store_true")
    parser.add_argument("--source-license", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--review-reference", default="")
    parser.add_argument("--with-embeddings", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not args.dry_run and not args.source_license.strip():
        raise SystemExit("--source-license is required before records can be seeded.")
    if args.status == "approved":
        missing = [
            flag for flag, present in (
                ("--allow-approved", args.allow_approved),
                ("--confirm-reviewed", args.confirm_reviewed),
                ("--reviewer", bool(args.reviewer.strip())),
                ("--review-reference", bool(args.review_reference.strip())),
                ("--source-license", bool(args.source_license.strip())),
            )
            if not present
        ]
        if missing:
            raise SystemExit(
                "Direct approval requires recruiter review evidence; missing: " + ", ".join(missing)
            )

    iterable: Iterable[dict[str, Any]] = records(
        Path(args.data_csv).resolve(),
        status=args.status,
        limit=args.limit,
        source_license=args.source_license.strip() or "UNREVIEWED-DRY-RUN",
        reviewer=args.reviewer.strip(),
        review_reference=args.review_reference.strip(),
    )
    if args.with_embeddings:
        from google import genai
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1")
        if not key:
            raise SystemExit("Set GEMINI_API_KEY before --with-embeddings.")
        client = genai.Client(api_key=key)
        iterable = (attach_embedding(record, client) for record in iterable)

    if args.dry_run:
        count = 0
        for record in iterable:
            count += 1
            print(json.dumps({key: val for key, val in record.items() if key != "embedding"}, ensure_ascii=False))
        print(f"Prepared {count} records.")
        return 0

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url before seeding Supabase.")

    import psycopg
    from psycopg.types.json import Jsonb

    total = 0
    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            for record in iterable:
                clean = dict(record)
                doc_id = str(clean.pop("id"))
                embedding = clean.pop("embedding", None)
                vector_text = None
                if isinstance(embedding, list):
                    vector_text = "[" + ",".join(str(float(item)) for item in embedding) + "]"
                clean["updatedAt"] = clean.get("updatedAt") or "seeded-by-ml-pipeline"
                cursor.execute(
                    """
                    insert into public.approved_exemplars
                      (id, payload, source_payload, source_collection, source_document_id,
                       source_checksum, migrated_at, updated_at, status, approved,
                       rubric_version, embedding_model, vector_index_version, embedding)
                    values (%s, %s, %s, 'approvedExemplars', %s, %s, now(), now(),
                            %s, %s, %s, %s, %s, %s::vector)
                    on conflict (id) do update set
                      payload = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.payload else excluded.payload end,
                      source_payload = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.source_payload else excluded.source_payload end,
                      source_checksum = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.source_checksum else excluded.source_checksum end,
                      updated_at = now(),
                      status = case
                        when public.approved_exemplars.approved then public.approved_exemplars.status
                        else excluded.status end,
                      approved = public.approved_exemplars.approved or excluded.approved,
                      rubric_version = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.rubric_version else excluded.rubric_version end,
                      embedding_model = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.embedding_model else excluded.embedding_model end,
                      vector_index_version = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.vector_index_version else excluded.vector_index_version end,
                      embedding = case
                        when public.approved_exemplars.approved and not excluded.approved
                        then public.approved_exemplars.embedding
                        else coalesce(excluded.embedding, public.approved_exemplars.embedding) end
                    """,
                    (
                        doc_id,
                        Jsonb(clean),
                        Jsonb(clean),
                        doc_id,
                        payload_checksum(clean),
                        clean["status"],
                        bool(clean["approved"]),
                        clean["rubricVersion"],
                        clean["embeddingModel"],
                        clean["vectorIndexVersion"],
                        vector_text,
                    ),
                )
                total += 1
        connection.commit()
    print(f"Seeded {total} {args.status} records into Supabase approved_exemplars.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
