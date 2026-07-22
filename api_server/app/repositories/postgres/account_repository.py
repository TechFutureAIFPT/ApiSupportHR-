from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.postgres.document_store import PostgresDocumentDatabase


USERS_COLLECTION = "users"
USER_SETTINGS_COLLECTION = "userSettings"
CV_HISTORY_COLLECTION = "cvHistory"
SYNCED_CACHE_COLLECTION = "syncedAnalysisCache"
SYNCED_HISTORY_COLLECTION = "syncedAnalysisHistory"
UPLOADED_FILES_COLLECTION = "uploadedFiles"
JD_TEMPLATES_COLLECTION = "userJDTemplates"
CHATBOT_SESSIONS_COLLECTION = "chatbotSessions"
MANUAL_COLLECTION_ID = "CLdl7JGuaOGIuijiDZeG"
GOOGLE_DRIVE_CONNECTIONS_COLLECTION = "googleDriveConnections"
GOOGLE_DRIVE_OAUTH_STATES_COLLECTION = "googleDriveOAuthStates"
ANALYSIS_FEEDBACK_COLLECTION = "analysisFeedback"
APPROVED_EXEMPLARS_COLLECTION = "approvedExemplars"
ANALYSIS_JOBS_COLLECTION = "analysisJobs"
AI_REQUEST_HISTORY_COLLECTION = "aiRequestHistory"
QUICK_CV_SCORES_COLLECTION = "mobileQuickCvAnalyses"
FILE_EXTRACTIONS_COLLECTION = "fileExtractions"
MOBILE_JD_HISTORY_COLLECTION = "mobileJDStandardizations"
MOBILE_INBOX_VIEW_COLLECTION = "mobileInboxViews"
USER_SYNC_STATE_COLLECTION = "userSyncState"


def db() -> PostgresDocumentDatabase:
    return PostgresDocumentDatabase()


def server_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def users():
    return db().collection(USERS_COLLECTION)


def user_settings():
    return db().collection(USER_SETTINGS_COLLECTION)


def cv_history():
    return db().collection(CV_HISTORY_COLLECTION)


def synced_cache():
    return db().collection(SYNCED_CACHE_COLLECTION)


def synced_history():
    return db().collection(SYNCED_HISTORY_COLLECTION)


def uploaded_files():
    return db().collection(UPLOADED_FILES_COLLECTION)


def jd_templates():
    return db().collection(JD_TEMPLATES_COLLECTION)


def chatbot_sessions():
    return db().collection(CHATBOT_SESSIONS_COLLECTION)


def manual_history():
    return db().collection(MANUAL_COLLECTION_ID)


def google_drive_connections():
    return db().collection(GOOGLE_DRIVE_CONNECTIONS_COLLECTION)


def google_drive_oauth_states():
    return db().collection(GOOGLE_DRIVE_OAUTH_STATES_COLLECTION)


def analysis_feedback():
    return db().collection(ANALYSIS_FEEDBACK_COLLECTION)


def approved_exemplars():
    return db().collection(APPROVED_EXEMPLARS_COLLECTION)


def analysis_jobs():
    return db().collection(ANALYSIS_JOBS_COLLECTION)


def ai_request_history():
    return db().collection(AI_REQUEST_HISTORY_COLLECTION)


def quick_cv_scores():
    return db().collection(QUICK_CV_SCORES_COLLECTION)


def file_extractions():
    return db().collection(FILE_EXTRACTIONS_COLLECTION)


def mobile_jd_history():
    return db().collection(MOBILE_JD_HISTORY_COLLECTION)


def mobile_inbox_views():
    return db().collection(MOBILE_INBOX_VIEW_COLLECTION)


def user_sync_state():
    return db().collection(USER_SYNC_STATE_COLLECTION)


def create_document(collection_ref):
    return collection_ref.document()


def get_document(collection_ref, document_id: str):
    return collection_ref.document(document_id).get()


def set_document(collection_ref, document_id: str, payload: dict[str, Any], merge: bool = False):
    collection_ref.document(document_id).set(payload, merge=merge)
