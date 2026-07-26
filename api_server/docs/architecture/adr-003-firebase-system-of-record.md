# ADR-003: Firebase is the SupportHR system of record

## Status

Accepted, 2026-07-26.

## Decision

- Firebase Authentication is the only supported user identity provider.
- Cloud Firestore is the only application database and vector-store provider.
- The backend verifies Firebase ID tokens with Firebase Admin and uses Admin SDK access for trusted operations.
- Web and Android use Firebase client sessions; Android uses owner-scoped Firestore realtime listeners.
- Firestore Security Rules protect direct client reads and writes. Backend-only collections remain denied to clients.
- Redis remains limited to queues, rate limits, short-lived job state, and caches.

## Operational requirements

- Production needs `FIREBASE_PROJECT_ID` and a valid Admin credential (`FIREBASE_SERVICE_ACCOUNT_JSON`, credential path, or Application Default Credentials).
- `/health/ready` must report `provider=firebase` and `firestoreReady=true`.
- Firebase authorized domains must contain every production web host used for Google sign-in.
- Firestore rules and indexes are versioned under `Software/Project-Rules/firebase`.

## Provider removal

The previous alternate-provider runtime, SQL schema, migration scripts, dependencies, and provider switches were removed. Any external provider project is retained only until its data and user counts have been reconciled against Firebase; deletion is a separate irreversible administrative action.
