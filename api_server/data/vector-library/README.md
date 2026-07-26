# Legacy Vector Seed Library

Thu muc nay chi luu seed JSON cu de doi soat va tai tao du lieu. Backend production khong doc JSON luc runtime.

Ten file mac dinh:

```text
{collectionKey}-embeddings.json
```

Vi du:

```text
it-embeddings.json
sales-embeddings.json
marketing-embeddings.json
design-embeddings.json
```

Cau truc file:

```json
{
  "records": [
    {
      "id": "sample-1",
      "name": "Senior Backend Engineer",
      "role": "Backend Developer",
      "relativePath": "samples/backend-01.md",
      "metadata": {
        "level": "senior",
        "source": "seed"
      },
      "vector": [0.12, -0.04, 0.98]
    }
  ]
}
```

Firebase runtime hien tai hoat dong theo 2 bang:

- `vector_library_records`: bang Firestore vector search chinh cho semantic search
- `uploaded_files`: du lieu goc, duoc backend tu dong embed va dong bo sang `vector_library_records`

Luot sync hien tai:

- Khi luu `uploaded_files` co `file_type=cv`, backend thu embed va tao record Cloud Firestore
- Record duoc gan `metadata.ownerUid` de `/api/cv/enrich` chi tim trong thu vien vector cua dung user dang goi API
- Neu can backfill du lieu cu, goi:

```text
POST /api/account/uploaded-files/vector-index/rebuild
```

Hoac re-index 1 file cu the:

```text
POST /api/account/uploaded-files/{file_id}/vectorize
```

Seed data hien tai:

- `it-embeddings.json`
- `sales-embeddings.json`
- `marketing-embeddings.json`
- `design-embeddings.json`

Thu muc `samples/` chua cac profile mau duoc dung de sinh embedding seed.

De tao lai toan bo seed vectors:

```bash
py -3.10 scripts/generate_vector_library.py
```

Lenh tren can backend `.env` hop le va Gemini embedding API key con hoat dong.
