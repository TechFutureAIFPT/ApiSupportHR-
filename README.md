## Backend

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Environment:

- Copy `.env.example` to `.env`
- Set `GEMINI_API_KEY_1` and `GEMINI_API_KEY_2`

Render deploy:

- Python version is pinned in `.python-version`
- Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- You can deploy from `render.yaml` or configure the same values in the Render UI
