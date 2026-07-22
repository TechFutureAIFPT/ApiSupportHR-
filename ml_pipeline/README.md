# SupportHR offline ML pipeline

This directory is the canonical training and exemplar-ingestion source for the backend repository.
It is intentionally **not** copied into the production image. The server only receives the reviewed
classifier artifact and manifest under `api_server/app/models/`.

## Safety contract

- Put licensed source data under `ml_pipeline/data/raw/` or pass an external `--dataset-csv` path.
- Raw CV/JD files, generated reports, and temporary artifacts are ignored by Git.
- Training removes exact duplicates and rejects samples whose identical text has conflicting labels.
- A model is deployable only with its generated manifest and SHA-256 checksum.
- Exemplar ingestion defaults to `pending`; `approved` requires an explicit confirmation flag.
- RAG vectors use `gemini-embedding-2`, 768 dimensions, rubric `v2`, and vector index contract
  `gemini-embedding-2-768-v1`. Re-embed every record when any of these values changes.

## Train and install the classifier

```bash
python -m pip install -r ml_pipeline/requirements.txt
python ml_pipeline/train_classifier.py --dataset-csv D:/datasets/Resume.csv --dataset-license "<reviewed-license-id>"
```

The default outputs are installed directly into `api_server/app/models/`:

- `text_classifier_model.pkl`
- `text_classifier_model.manifest.json`
- generated evaluation files under `ml_pipeline/artifacts/` (not deployed)

Use `--audit-only` before a full run when onboarding a new dataset. A release run requires an explicit
`--dataset-license` value and fails when labels are malformed, a class is too small, duplicate labels
conflict, or the holdout macro-F1 is below the
configured gate.

## Prepare RAG exemplars

Dry-run first:

```bash
python ml_pipeline/seed_exemplars.py --data-csv D:/datasets/job_resume_fit.csv --dry-run --limit 5
```

Upload pending records with embeddings:

```bash
python ml_pipeline/seed_exemplars.py --data-csv D:/datasets/job_resume_fit.csv --with-embeddings
```

Publishing directly is deliberately harder and should be used only after recruiter review:

```bash
python ml_pipeline/seed_exemplars.py --data-csv D:/reviewed/exemplars.csv --status approved --allow-approved
```

Apply the Supabase pgvector migration and HNSW cosine index before enabling native nearest-neighbor retrieval.
The seed command writes directly to `public.approved_exemplars` through `DATABASE_URL`.
