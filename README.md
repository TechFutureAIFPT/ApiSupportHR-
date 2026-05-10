## Backend

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Environment:

- Copy `.env.example` to `.env`
- Set `GEMINI_API_KEY_1` and `GEMINI_API_KEY_2`
