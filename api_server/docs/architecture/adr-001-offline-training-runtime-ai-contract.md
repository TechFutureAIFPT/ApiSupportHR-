# ADR-001: Offline training with a versioned in-process AI runtime

## Status

Accepted - 2026-07-18; async-job trade-off superseded by ADR-002 on 2026-07-22

## Context

SupportHR needs a self-trained CV classifier, recruiter scoring templates, and approved RAG exemplars.
Training data is large and may contain personal or licensed material. The Render service is a single
FastAPI deployment and should start quickly without retraining or depending on a second ML service.

## Options considered

| Option | Benefit | Cost |
| --- | --- | --- |
| Train inside the API process | One command | Slow and unsafe startup; raw data in production |
| Separate classifier service | Independent scaling | More deployment, networking, and failure modes |
| Offline train, versioned artifact inside the backend | Simple runtime, deterministic deploy | Artifact must be reviewed and replaced deliberately |

## Decision

Keep training and exemplar-ingestion source in `BE/ml_pipeline`, but run it only offline. Deploy only the
reviewed `.pkl` plus a manifest. The FastAPI process loads the model once and fails readiness when checksum,
labels, schema, or scikit-learn version do not match.

All scoring and retrieval data uses explicit contracts:

- pipeline `cv-analysis-v2`;
- rubric `v2`, with eight role templates and validated recruiter overrides totaling 100;
- exemplar schema `supporthr-exemplar-v2`, where missing approval means not approved;
- embedding `gemini-embedding-2`, dimension 768, vector index `gemini-embedding-2-768-v1`.

PostgreSQL native nearest-neighbor search is the production RAG path. A bounded local scan exists only for
the index creation/test window. Cache identity includes content and all scoring/model contract versions.

## Trade-offs

- A new embedding model or dimension requires complete re-embedding; incompatible vectors are ignored.
- The current classifier remains a routing signal for 24 broad categories, not a final scoring authority.
- The classifier still runs in-process, while async analysis execution is now separated into Redis-backed
  workers as described in ADR-002.

## Revisit triggers

- Classifier traffic requires independent autoscaling.
- Render memory is insufficient for the artifact.
- A new embedding/rubric contract is approved and migrated end-to-end.
