# SupportHR offline ML pipeline

This directory is the canonical training and exemplar-ingestion source for the backend repository.
It is intentionally **not** copied into the production image. The server only receives the reviewed
classifier artifact and manifest under `api_server/app/models/`.

## Safety contract

- Register every source in `configs/datasets.json` with a pinned revision, license decision, intended
  uses, and prohibited uses before acquisition or release.
- Put licensed source data under `ml_pipeline/data/raw/` or pass an external path.
- Raw CV/JD files, generated reports, and temporary artifacts are ignored by Git.
- The shared pipeline normalizes text once, redacts PII, quarantines invalid rows, removes exact
  duplicates, groups near-duplicates, and preserves lineage/checksums.
- Evaluation-only datasets cannot be used by training commands.
- Training rejects samples whose identical text has conflicting labels and keeps every near-duplicate
  entity group in one split.
- A model is deployable only with its generated manifest and SHA-256 checksum.
- Exemplar ingestion defaults to `pending`; `approved` requires reviewer identity, review reference,
  license confirmation, and two explicit approval confirmations.
- Graph candidates always start as `pending`, use `decisionImpact=none`, and cannot become runtime
  artifacts without `validate_graph_release.py`.
- RAG vectors use `gemini-embedding-2`, 768 dimensions, rubric `v2`, and vector index contract
  `gemini-embedding-2-768-v1`. Re-embed every record when any of these values changes.

## Train and install the classifier

```bash
python -m pip install -r ml_pipeline/requirements.txt
python ml_pipeline/prepare_dataset.py \
  --source-id kaggle-resume-dataset \
  --input-csv D:/datasets/Resume.csv \
  --intended-use classifier_training

python ml_pipeline/train_classifier.py \
  --source-id kaggle-resume-dataset \
  --dataset-csv D:/datasets/Resume.csv \
  --dataset-license CC0-1.0 \
  --classifier linear-svc \
  --output-model-dir ml_pipeline/artifacts/classifier/cv-industry-24-v2
```

Use a candidate output directory first. Omit `--output-model-dir` only after the evaluation gate
passes and the candidate has been reviewed, because that installs directly into runtime:

- `text_classifier_model.pkl`
- `text_classifier_model.manifest.json`
- generated evaluation files under `ml_pipeline/artifacts/` (not deployed)

Use `--audit-only` before a full run when onboarding a new dataset. Training also requires a registered
`--source-id`; the file SHA-256 and optional `--dataset-license` must match the reviewed registry entry.
The command fails when the source is evaluation-only/quarantined, labels are malformed, a class is too
small, duplicate labels conflict, or the holdout macro-F1 is below the configured gate.

The current 2,481-row cleaned Resume Dataset candidate does **not** pass the `0.70` macro-F1 release
gate (`0.665980` with grouped LinearSVC holdout), so the packaged runtime model is intentionally not
overwritten.

## Acquire pinned Hugging Face datasets

Dry-run shows exact files and size:

```bash
python ml_pipeline/acquire_hf_dataset.py \
  --source-id techwolf-skill-tech \
  --intended-use skill_linker_evaluation \
  --accept-license CC-BY-4.0 \
  --dry-run
```

Remove `--dry-run` to download into the ignored immutable raw-data directory. The three TechWolf
benchmarks are pinned and prepared as evaluation-only artifacts. Large ESCO/MELS sources remain
registry-pinned but are not downloaded until the skill-linker phase needs them.

```bash
python ml_pipeline/prepare_skill_benchmark.py \
  --source-id techwolf-skill-tech \
  --input-root ml_pipeline/data/raw/huggingface/techwolf-skill-tech/<revision>
```

The current four-source ingestion is physically separated under `data/raw/huggingface`:

| Source | Storage category | Model route |
|---|---|---|
| `TechWolf/skill-extraction-techwolf` | `skill_extraction/evaluation` | ESCO skill-linker benchmark only |
| `opensporks/resumes` | `resume_classification/source_equivalence` | Byte-identical mirror; zero extra training rows |
| `batuhanmtl/job-skill-set` | `job_skill/quarantine` | Redacted skill-catalog candidates; blocked from training until derivative-label terms are verified |
| `siddharth5151/job-compatibility` | `job_compatibility/evaluation` | CV/JD prompt regression only; never numeric scoring ground truth |

Run the adapters and create the routing report:

```bash
python ml_pipeline/integrate_hf_datasets.py
```

The report is written to
`ml_pipeline/artifacts/hf_integration/dataset-routing-report.json`. The acquisition command downloads
structured CSV/JSON/Parquet and README files by default. It deliberately excludes the resume mirror's
individual PDF copies because the CSV contains the same 2,484 records and has a smaller privacy surface.
Quarantined sources additionally require `--allow-quarantine-download --intended-use audit_only`.

Normalized artifacts do not repeat shared payloads: all compatibility CVs reference the canonical
Resume source, the 40 unique job descriptions are stored once and linked by ID, and job-skill rows
contain `skillIds` that resolve through one candidate catalog. Raw snapshots remain immutable for
provenance; deduplication happens only in generated artifacts. Near-duplicate JD rows receive the
same `entityGroupId` so a future train/evaluation split cannot leak them across folds.

Audit an unsafe source without emitting raw text:

```bash
python ml_pipeline/audit_quarantined_csv.py \
  --source-id job-resume-fit \
  --input-csv D:/datasets/job_resume_fit.csv \
  --primary-text-column resume_text \
  --paired-text-column job_text \
  --label-column category
```

## Build GraphRAG candidates

```bash
python ml_pipeline/build_graph_candidates.py \
  --curated-jsonl ml_pipeline/artifacts/data/curated/kaggle-resume-dataset.jsonl
```

This emits pending observations only. After human review, validate a separate approved artifact:

```bash
python ml_pipeline/validate_graph_release.py \
  --graph-jsonl D:/reviewed/approved_graph_facts.jsonl
```

Runtime reads only validated approved facts. Configure `GRAPH_RAG_ENABLED=true` and keep
`GRAPH_RAG_SHADOW_MODE=true` for the first rollout. Inspect readiness through
`GET /api/cv/graphrag-status`.

## Prepare RAG exemplars

Dry-run first:

```bash
python ml_pipeline/seed_exemplars.py --data-csv D:/datasets/job_resume_fit.csv --dry-run --limit 5
```

Upload pending records with embeddings:

```bash
python ml_pipeline/seed_exemplars.py \
  --data-csv D:/reviewed/pending_exemplars.csv \
  --source-license "<reviewed-license-id>" \
  --with-embeddings
```

Publishing directly is deliberately harder and should be used only after recruiter review:

```bash
python ml_pipeline/seed_exemplars.py \
  --data-csv D:/reviewed/exemplars.csv \
  --status approved \
  --source-license "<reviewed-license-id>" \
  --reviewer "<reviewer-id>" \
  --review-reference "<ticket-or-review-record>" \
  --allow-approved \
  --confirm-reviewed
```

Apply the Firestore vector index before enabling native nearest-neighbor retrieval.
The seed command writes directly to `public.approved_exemplars` through `FIREBASE_SERVICE_ACCOUNT_JSON`.
