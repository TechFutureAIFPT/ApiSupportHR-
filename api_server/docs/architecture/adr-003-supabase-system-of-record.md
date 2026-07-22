# ADR-003: Supabase as the SupportHR system of record

## Status

Accepted and implemented for runtime; production activation is gated on hosted-project access, restored Web FE source, and migration reconciliation.

## Context

SupportHR historically used Firebase services. That system is now treated only as a read-only legacy migration source; production application code uses Supabase Auth, PostgreSQL, pgvector, and Supabase Realtime.

## Decision

- Use Supabase Auth and PostgreSQL as the single source of truth after cutover.
- Preserve HTTP routes and response shapes.
- Do not keep runtime provider switches or fallback paths; Supabase is the only supported runtime provider.
- Use one relational table per existing collection with typed ownership/index columns plus operational and original JSONB payloads.
- Preserve legacy document IDs and maintain an explicit legacy UID to Supabase UUID mapping.
- Use PostgreSQL RLS for client access and direct pooled SQL for trusted backend access.
- Preserve legacy 3072-dimensional vectors separately and generate new 768-dimensional runtime embeddings.

## Trade-offs

- PostgreSQL repositories expose the minimal collection-style contract required by existing services while keeping storage implementation Supabase-only.
- JSONB preserves irregular historical payloads; frequently queried ownership/time/status fields remain typed and indexed.
- The legacy source remains unchanged until reconciliation and then read-only for 30 days. There is no dual-write path, avoiding split-brain.

## Consequences

- Web and Android must use Supabase sessions and Supabase Realtime.
- App Check is removed; Supabase JWT verification, RLS, CORS, and existing Redis rate limits remain mandatory.
- Unknown owners are imported with `owner_id = null` and are inaccessible to normal users until manually resolved.
- Production cutover cannot proceed without a Supabase project, Auth import, restored Web FE, canary sign-ins, and exact migration reconciliation.
