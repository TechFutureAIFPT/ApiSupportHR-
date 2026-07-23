## Backend

FastAPI backend for CV analysis, recruiter workflow automation, Google Drive import, and feedback/evaluation loops. The data/auth layer supports Supabase/PostgreSQL before cutover and Supabase Auth/PostgreSQL afterward.

### Project documentation

- [Project and code map](../../../../Document/01-Tai-Lieu-Du-An/00-BAN-DO-DU-AN.md)
- [Backend from A-Z](../../../../Document/01-Tai-Lieu-Du-An/03-backend-be-tu-a-z.md)
- [API reference](../../../../Document/01-Tai-Lieu-Du-An/04-api-reference.md)
- [Documentation-code traceability](../../../../Document/01-Tai-Lieu-Du-An/11-MA-TRAN-TRUY-VET.md)

### Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run with Docker

Docker Compose runs the API, Redis and a separate analysis worker. The production path uses
`ANALYSIS_JOB_MODE=redis`; `in_process` is retained only for local development compatibility.

From the backend repo root (`Software/Web/BE`):

```bash
docker compose build
docker compose up
docker compose up --scale worker=3
```

Check the API:

```bash
curl http://localhost:8000/health
```

Expected response includes classifier and queue readiness. Liveness and readiness are also available at:

```text
GET /health/live
GET /health/ready
```

Docker reads local secrets from `api_server/.env` through `docker-compose.yml`; `.env` is excluded from the image by `.dockerignore`.
Do not share output from `docker compose config` or `docker inspect` because those commands can display environment variables from `.env`.

When testing the mobile app against this Docker backend:

- Expo web: `EXPO_PUBLIC_API_URL=http://localhost:8000`
- Android emulator: `EXPO_PUBLIC_API_URL=http://10.0.2.2:8000`
- Physical phone: use the computer LAN IP, for example `EXPO_PUBLIC_API_URL=http://192.168.x.x:8000`

### Environment

- Keep your local `.env` for testing.
- Use `.env.example` as the public-safe template when pushing code to Git.
- Required minimum for backend startup:
  - `SUPABASE_URL` and pooled `DATABASE_URL`
  - base64 32-byte `DATA_ENCRYPTION_KEY`
  - `GEMINI_API_KEY_1`
  - packaged `app/models/text_classifier_model.pkl` and matching `.manifest.json`
- Required for Google Drive import:
  - `GOOGLE_OAUTH_CLIENT_ID`
  - `GOOGLE_OAUTH_CLIENT_SECRET`
  - `GOOGLE_OAUTH_REDIRECT_URI`
  - `GOOGLE_DRIVE_ALLOWED_ORIGINS`
- Optional for remote CV classifier deployment:
  - `LOCAL_CLASSIFIER_MODE=remote` or `auto`
  - `LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL`
  - `LOCAL_CLASSIFIER_REMOTE_STATUS_URL` (optional if the remote service also exposes `/api/cv/classifier-status`)

AI/RAG production contract:

- `GEMINI_EMBEDDING_MODEL=gemini-embedding-2`
- `GEMINI_EMBEDDING_DIMENSION=768`
- `VECTOR_INDEX_VERSION=gemini-embedding-2-768-v1`
- `RUBRIC_VERSION=v2`
- `VECTOR_STORE_COLLECTION=vectorLibraryRecords`; PostgreSQL/pgvector is the only runtime vector store.

Migration commands and safety gates are documented in `scripts/README-supabase-migration.md`.

### Project structure

```text
backend/
├─ app/
│  ├─ api/
│  │  ├─ deps.py
│  │  └─ routes/
│  │     ├─ ai.py
│  │     ├─ files.py
│  │     └─ account/
│  │        ├─ profile.py
│  │        ├─ sync.py
│  │        ├─ history.py
│  │        ├─ uploaded_files.py
│  │        ├─ templates.py
│  │        ├─ chatbot.py
│  │        └─ google_drive.py
│  ├─ core/
│  ├─ integrations/
│  ├─ prompts/
│  ├─ repositories/
│  ├─ schemas/
│  ├─ services/
│  │  ├─ account/
│  │  ├─ candidate_enrichment_service.py
│  │  ├─ cv_analysis_service.py
│  │  ├─ file_extraction_service.py
│  │  ├─ gemini_service.py
│  │  └─ workflow_service.py
│  └─ main.py
├─ data/
├─ docs/
├─ tests/
├─ .env.example
├─ Dockerfile
└─ requirements.txt
```

### Public Git checklist

- Do not commit `.env`, service-account JSON files, or private API keys.
- Keep docs in `docs/` and runtime data samples in `data/`.
- Put new HTTP endpoints under `app/api/routes/` instead of growing a single route file.
- Keep PostgreSQL collection access inside `app/repositories/`.
- Keep business logic inside `app/services/`.

### Key API flows

Google Drive:
- `POST /api/account/google-drive/oauth-url`
- `POST /api/account/google-drive/exchange-code`
- `GET /api/account/google-drive/files`
- `POST /api/account/google-drive/import`

Feedback loop:
- `POST /api/account/history/feedback`
- `GET /api/account/history/feedback`
- `GET /api/account/history/feedback/stats`

Async CV analysis:
- `POST /api/cv/analyze-core-async` returns `202 Accepted` with `job_id`.
- `POST /api/analysis/jobs` is the queue-oriented alias for creating the same analysis job.
- `GET /api/analysis/status/{job_id}` returns `queued`, `processing`, `completed`, or `failed` for frontend polling.
- Completed jobs include the normal `{ candidates, pipeline }` payload and are persisted to PostgreSQL history when the request has a valid Supabase user.

### Deploy

The repository-level `../render.yaml` is the temporary free demo deployment: one Render web service,
`ANALYSIS_JOB_MODE=in_process`, and no paid worker or Redis service. Render secrets must be configured
in the dashboard before `/health/ready` can pass.

The primary production target remains `../compose.production.yaml` with operating scripts under
`../deploy/vps`. Kubernetes/K3s manifests and operating notes are under `../deploy/kubernetes`;
`overlays/oci-free` is the single-node ARM64 target, while `overlays/production` remains the multi-node path.

- Python version is pinned in `.python-version`
- Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- GitHub Actions publishes AMD64/ARM64 images to GHCR; pin production to an immutable `sha-*` tag.
- The gated VPS workflow deploys successful `main` images over verified-host SSH and runs the public health/rollback gate.
- Keep only the repository-level Render blueprint; do not add a second copy under `api_server`.
- Render free mode is for demo/acceptance traffic and may spin down. It is not the production queue topology.
- The self-trained CV classifier can stay local inside this API, or be deployed as a separate HTTP service and wired back through `LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL`.
- Canonical offline training and exemplar ingestion live in `../ml_pipeline`; raw data and generated artifacts are not copied into the server image.
