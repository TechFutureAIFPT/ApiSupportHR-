# Vector Library

Thu muc nay la noi backend uu tien tim cac file vector library theo tung collection.

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

Neu `VECTOR_STORE_PROVIDER=firestore` thi backend se uu tien doc Firestore truoc.
Neu Firestore khong co record hop le, backend se fallback ve JSON library trong thu muc nay.

Firestore mode hien tai hoat dong theo 2 nguon:

- `vectorLibraryRecords`: collection index chinh cho semantic search
- `uploadedFiles`: du lieu goc, duoc backend tu dong embed va dong bo sang `vectorLibraryRecords`

Luot sync hien tai:

- Khi luu `uploadedFiles` co `fileType=cv`, backend thu embed va tao record Firestore
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
