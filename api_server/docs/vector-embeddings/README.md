# Vector embeddings and approved RAG

## Production contract

The production backend uses Cloud Firestore native vector search for approved RAG exemplars. The active contract is:

```text
model: gemini-embedding-2
dimension: 768
vectorIndexVersion: gemini-embedding-2-768-v1
rubricVersion: v2
```

Embedding spaces are not interchangeable. Records from `gemini-embedding-001`, records with a different
dimension, and records missing `vectorIndexVersion` are ignored and must be re-embedded.

## Canonical approved exemplar

An exemplar in `approvedExemplars` contains:

- `schemaVersion=supporthr-exemplar-v2`;
- `approved=true` and `status=approved` (missing values are not trusted);
- rubric, embedding model, dimension, and vector-index versions;
- role, industry, seniority, job title;
- redacted CV text and approved analysis JSON;
- a Cloud Firestore `Vector` in `embedding`.

`BE/ml_pipeline/seed_exemplars.py` creates this schema. It defaults to `pending`; direct approval requires
both `--status approved` and `--allow-approved` after recruiter review.

## Retrieval path

`analysis_grounding_service.py` creates one semantic-similarity vector per cache-miss CV. The same CV vector
is reused by RAG and candidate enrichment. `vector_repository.find_nearest_approved_exemplars` applies status,
rubric, and vector-version prefilters and calls Cloud Firestore `find_nearest` with cosine distance.

If the composite vector index is still building, a compatibility path reads no more than
`RAG_CANDIDATE_LIMIT` records and applies the same approval/version checks locally. It never streams the
whole collection and never treats missing approval as approved.

## User vector library

Uploaded CV vector records are tagged with the same model, dimension, and index version. Production sets
`VECTOR_STORE_COLLECTION=vectorLibraryRecords`; Cloud Firestore vector search is the only runtime vector store.
Legacy JSON files are not loaded by the application runtime.

## Similarity bonus policy

```text
>= 0.88 -> +5.0
>= 0.83 -> +3.5
>= 0.78 -> +2.0
>= 0.72 -> +1.0
<  0.72 -> +0.0
```

Classifier labels and vector similarity are supporting signals only. Final scores still require evidence
from the current CV and JD.
