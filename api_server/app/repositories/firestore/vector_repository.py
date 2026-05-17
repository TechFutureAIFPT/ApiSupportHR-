from __future__ import annotations

from app.integrations.firebase_admin import get_firestore_client


def db():
    return get_firestore_client()


def vector_library(collection_name: str):
    return db().collection(collection_name)
