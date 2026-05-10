from __future__ import annotations

from typing import Any

from firebase_admin import firestore

from app.integrations.firebase_admin import get_firestore_client


USERS_COLLECTION = "users"
CV_HISTORY_COLLECTION = "cvHistory"
SYNCED_CACHE_COLLECTION = "syncedAnalysisCache"
SYNCED_HISTORY_COLLECTION = "syncedAnalysisHistory"
UPLOADED_FILES_COLLECTION = "uploadedFiles"
JD_TEMPLATES_COLLECTION = "userJDTemplates"
CHATBOT_SESSIONS_COLLECTION = "chatbotSessions"
MANUAL_COLLECTION_ID = "CLdl7JGuaOGIuijiDZeG"


def db():
    return get_firestore_client()


def server_timestamp():
    return firestore.SERVER_TIMESTAMP


def users():
    return db().collection(USERS_COLLECTION)


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


def create_document(collection_ref):
    return collection_ref.document()


def get_document(collection_ref, document_id: str):
    return collection_ref.document(document_id).get()


def set_document(collection_ref, document_id: str, payload: dict[str, Any], merge: bool = False):
    collection_ref.document(document_id).set(payload, merge=merge)

