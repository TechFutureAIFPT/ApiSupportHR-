# Cloud Firestore database

Firebase Authentication and Cloud Firestore are the SupportHR source of truth.

## Ownership model

- User-owned documents contain a `uid` field matching the Firebase Auth UID.
- Profile and realtime state documents use the UID as their document ID where practical.
- Backend routes always derive ownership from the verified Firebase ID token.
- Direct mobile access is limited by `Project-Rules/firebase/firestore.rules`.
- Firebase Admin access is trusted and therefore must enforce ownership in repositories and services.

## Main collections

`users`, `userSettings`, `cvHistory`, `syncedAnalysisCache`, `syncedAnalysisHistory`, `uploadedFiles`, `userJDTemplates`, `chatbotSessions`, `analysisFeedback`, `approvedExemplars`, `analysisJobs`, `aiRequestHistory`, `mobileQuickCvAnalyses`, `fileExtractions`, `mobileJDStandardizations`, `mobileInboxViews`, `desktopSessions`, `sessionCommands`, and `userSyncState`.

The legacy-compatible manual history collection ID remains `CLdl7JGuaOGIuijiDZeG` so existing Firebase records stay readable.

## Runtime

Repositories live in `app/repositories/firestore`. The backend uses Firebase Admin credentials and Firestore native vector queries. Client credentials must never contain the Admin service account.

## Deployment check

Deploy rules and indexes from `Software/firebase.json`, then verify the backend readiness endpoint reports:

```json
{
  "provider": "firebase",
  "firestoreReady": true
}
```
