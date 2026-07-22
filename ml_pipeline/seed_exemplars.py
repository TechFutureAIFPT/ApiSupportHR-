from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "supporthr-exemplar-v2"
EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSION = 768
VECTOR_INDEX_VERSION = "gemini-embedding-2-768-v1"
RUBRIC_VERSION = "v2"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def redact_pii(value: str) -> str:
    text = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "[EMAIL]", value)
    text = re.sub(r"(?:\+?\d[\d\s().-]{7,}\d)", "[PHONE]", text)
    text = re.sub(r"https?://\S+|www\.\S+", "[URL]", text, flags=re.I)
    return clean(text)


def value(row: dict[str, Any], *aliases: str) -> str:
    normalized = {re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_"): item for key, item in row.items()}
    for alias in aliases:
        item = normalized.get(alias)
        if item not in (None, ""):
            return str(item)
    return ""


def records(csv_path: Path, *, status: str, limit: int | None) -> Iterable[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        emitted = 0
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            cv = value(row, "resume_text", "resume", "cv_text", "cv")
            jd = value(row, "job_text", "jd_text", "job_description", "jd", "description")
            if not cv or not jd:
                continue
            redacted = redact_pii(cv)
            doc_id = hashlib.sha256(f"{csv_path.name}:{row_number}:{redacted[:500]}:{jd[:500]}".encode()).hexdigest()[:32]
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
                "jdSnapshot": clean(jd),
                "analysisJson": {"source": csv_path.name, "sourceRow": row_number},
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or seed canonical SupportHR RAG exemplars.")
    parser.add_argument("--data-csv", required=True)
    parser.add_argument("--collection", default="approvedExemplars")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--status", choices=("pending", "approved"), default="pending")
    parser.add_argument("--allow-approved", action="store_true")
    parser.add_argument("--with-embeddings", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.status == "approved" and not args.allow_approved:
        raise SystemExit("Direct approval requires --allow-approved after recruiter review.")

    iterable: Iterable[dict[str, Any]] = records(Path(args.data_csv).resolve(), status=args.status, limit=args.limit)
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

    from google.cloud import firestore
    from google.cloud.firestore_v1.vector import Vector
    db = firestore.Client(project=args.project) if args.project else firestore.Client()
    batch = db.batch()
    pending = total = 0
    for record in iterable:
        doc_id = str(record.pop("id"))
        if isinstance(record.get("embedding"), list):
            record["embedding"] = Vector(record["embedding"])
        record["updatedAt"] = firestore.SERVER_TIMESTAMP
        batch.set(db.collection(args.collection).document(doc_id), record, merge=True)
        pending += 1
        total += 1
        if pending >= 400:
            batch.commit()
            batch = db.batch()
            pending = 0
    if pending:
        batch.commit()
    print(f"Seeded {total} {args.status} records into {args.collection}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
