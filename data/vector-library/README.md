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
