## Backend

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Environment:

- Copy `.env.example` to `.env`
- Set `GEMINI_API_KEY_1` and `GEMINI_API_KEY_2`
- For Google Drive import, also set:
  - `GOOGLE_OAUTH_CLIENT_ID`
  - `GOOGLE_OAUTH_CLIENT_SECRET`
  - `GOOGLE_OAUTH_REDIRECT_URI`
  - `GOOGLE_DRIVE_ALLOWED_ORIGINS`

Google Drive API flow:

- `POST /api/account/google-drive/oauth-url` to get the Google consent URL
- `POST /api/account/google-drive/exchange-code` to exchange the returned `code`
- `GET /api/account/google-drive/files` to browse Drive files
- `POST /api/account/google-drive/import` to download a Drive file and extract text for CV/JD flow

Render deploy:

- Python version is pinned in `.python-version`
- Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- You can deploy from `render.yaml` or configure the same values in the Render UI
