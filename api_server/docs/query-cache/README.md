# Analysis query cache

## Storage and ownership

Completed candidate results are stored in PostgreSQL collection `syncedAnalysisCache`. Document IDs remain
`{uid}_{cacheKey}`, so entries are isolated by authenticated user. Entries expire after 30 days and each user
keeps at most 50.

## Cache identity

The analysis pipeline, not the frontend, builds the authoritative key. The SHA-256 payload includes:

- CV identity and CV text hash;
- JD hash;
- scoring weights and hard filters;
- rubric version;
- prompt version;
- classifier artifact version;
- analysis pipeline version.

Changing any scoring/model/content input therefore produces a cache miss. `jdHash`, `weightsHash`,
`filtersHash`, `rubricVersion`, and `pipelineVersion` are also stored as audit metadata.

## Read and write flow

The pipeline checks cache before language normalization, classifier, embedding, RAG, or Gemini scoring.
Valid hits skip all expensive AI work. On a miss, successful candidates are written concurrently with
`maintain_views=false`; cleanup and user-view refresh run once after the batch instead of once per candidate.

Expired entries are removed on read. Failed candidate results are not cached. Cache errors become pipeline
warnings and do not fail the analysis request.

## Account cache endpoints

- `POST /api/account/sync/cache`
- `GET /api/account/sync/cache/{cache_key}`
- `GET /api/account/sync/cache`
- `DELETE /api/account/sync/cache`

These endpoints remain available for account synchronization, while `run_smart_cv_analysis` owns the key
contract used for AI-result reuse.
