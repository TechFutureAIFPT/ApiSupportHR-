# ADR-003: Supabase as the SupportHR system of record

## Status

Accepted for implementation; production cutover is gated on hosted-project access, restored Web FE source, and migration reconciliation.

## Context

SupportHR currently uses Firebase Auth, Firestore, App Check, and a small legacy Realtime Database chatbot tree. Backend services call Firestore-like collection references directly, while Android also reads/writes selected owner-scoped collections.

## Decision

- Use Supabase Auth and PostgreSQL as the single source of truth after cutover.
- Preserve HTTP routes and response shapes.
- Keep provider flags so the new build can be deployed with Firebase active and switched only after reconciliation.
- Use one relational table per existing collection with typed ownership/index columns plus operational and original JSONB payloads.
- Preserve Firebase document IDs and maintain an explicit Firebase UID to Supabase UUID mapping.
- Use PostgreSQL RLS for client access and direct pooled SQL for trusted backend access.
- Preserve legacy 3072-dimensional vectors separately and generate new 768-dimensional runtime embeddings.

## Trade-offs

- A Firestore-compatible PostgreSQL adapter is temporary compatibility code, but it avoids rewriting every service during a high-risk data migration.
- JSONB preserves irregular historical payloads; frequently queried ownership/time/status fields remain typed and indexed.
- Firebase remains unchanged until cutover and then read-only for 30 days. There is no long-lived dual-write path, avoiding split-brain.

## Consequences

- Web and Android must use Supabase sessions and Supabase Realtime.
- App Check is removed from Supabase mode; JWT verification, RLS, CORS, and existing Redis rate limits remain mandatory.
- Unknown owners are imported with `owner_id = null` and are inaccessible to normal users until manually resolved.
- Production cutover cannot proceed without a Supabase project, Auth import, restored Web FE, canary sign-ins, and exact migration reconciliation.
