## Backend

FastAPI backend for CV analysis, recruiter workflow automation, Google Drive import, Firestore persistence, and feedback/evaluation loops.

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

Docker is an optional local runtime. It does not replace the current Render Python deployment unless `render.yaml` is changed later.

From the backend repo root (`Software/Web/BE`):

```bash
docker compose build
docker compose up
```

Check the API:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
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
  - `FIREBASE_SERVICE_ACCOUNT_JSON` or `FIREBASE_PROJECT_ID` + `FIREBASE_CLIENT_EMAIL` + `FIREBASE_PRIVATE_KEY`
  - `GEMINI_API_KEY_1`
- Required for Google Drive import:
  - `GOOGLE_OAUTH_CLIENT_ID`
  - `GOOGLE_OAUTH_CLIENT_SECRET`
  - `GOOGLE_OAUTH_REDIRECT_URI`
  - `GOOGLE_DRIVE_ALLOWED_ORIGINS`
- Optional for remote CV classifier deployment:
  - `LOCAL_CLASSIFIER_MODE=remote` or `auto`
  - `LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL`
  - `LOCAL_CLASSIFIER_REMOTE_STATUS_URL` (optional if the remote service also exposes `/api/cv/classifier-status`)

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
├─ render.yaml
└─ requirements.txt
```

### Public Git checklist

- Do not commit `.env`, service-account JSON files, or private API keys.
- Keep docs in `docs/` and runtime data samples in `data/`.
- Put new HTTP endpoints under `app/api/routes/` instead of growing a single route file.
- Keep Firestore collection access inside `app/repositories/`.
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
- `GET /api/analysis/status/{job_id}` returns `processing`, `completed`, or `failed` for frontend polling.
- Completed jobs include the normal `{ candidates, pipeline }` payload and are persisted to Firestore history when the request has a valid Firebase user.

### Deploy

- Python version is pinned in `.python-version`
- Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- You can deploy directly from `render.yaml` or mirror the same settings in Render UI.
- The self-trained CV classifier can stay local inside this API, or be deployed as a separate HTTP service and wired back through `LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL`.
