## Backend

FastAPI backend for CV analysis, recruiter workflow automation, Google Drive import, Firestore persistence, and feedback/evaluation loops.

### Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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

### Deploy

- Python version is pinned in `.python-version`
- Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- You can deploy directly from `render.yaml` or mirror the same settings in Render UI.
