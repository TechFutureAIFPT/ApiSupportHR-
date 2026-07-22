# ADR-002: Redis Stream workers and Kubernetes runtime

## Status

Accepted - 2026-07-22

## Context

The first async CV endpoint used `asyncio.create_task` inside the API process. PostgreSQL snapshots made job
status visible, but did not keep execution alive across a restart and per-user concurrency limits were local
to one process. That design cannot safely support multiple API replicas.

## Decision

- Keep FastAPI pods stateless for HTTP traffic.
- Put analysis jobs in a Redis Stream and process them through a consumer group.
- Store short-lived internal payload/state in Redis and authenticated audit snapshots in PostgreSQL.
- Acknowledge a stream message only after the worker finishes handling it.
- Reclaim pending messages after the configured idle lease so another worker can recover abandoned work.
- Enforce per-user concurrent-job slots in Redis with expiring leases.
- Use the same immutable image for API and worker processes, with different commands.
- Deploy API and worker as separate Kubernetes Deployments with probes, resources, HPA and PDB.
- Use managed Redis in production; the in-cluster Redis manifest is local-development only.

## Compatibility

`ANALYSIS_JOB_MODE=in_process` preserves the previous local/Render behavior. Docker Compose and Kubernetes
set `ANALYSIS_JOB_MODE=redis`. The public polling contract adds a `queued` state but keeps existing endpoints
and response fields.

## Trade-offs

- Redis is now required for the horizontally scaled job path.
- Redis Streams provide at-least-once delivery, so downstream writes must remain idempotent.
- CPU/memory HPA is a baseline. Queue-depth autoscaling requires KEDA or an external metrics adapter.
- PostgreSQL remains the record system; this change does not introduce a relational transaction boundary.
