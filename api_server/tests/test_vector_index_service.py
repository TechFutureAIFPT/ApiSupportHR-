from __future__ import annotations

import os
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.repositories.firestore import account_repository as account_repo
from app.repositories.firestore import vector_repository
from app.schemas.account import AuthenticatedUser
from app.services import vector_index_service
from app.services.account import uploaded_file_service


class FakeDocumentSnapshot:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id
        self.reference = FakeDocumentReference(collection, doc_id)

    @property
    def exists(self) -> bool:
        return self.id in self._collection.store

    def to_dict(self) -> dict[str, Any]:
        data = self._collection.store.get(self.id)
        return deepcopy(data) if data is not None else {}


class FakeDocumentReference:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def get(self) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self._collection, self.id)

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        current = deepcopy(self._collection.store.get(self.id, {})) if merge else {}
        current.update(deepcopy(payload))
        self._collection.store[self.id] = current

    def delete(self) -> None:
        self._collection.store.pop(self.id, None)


class FakeQuery:
    def __init__(self, collection: "FakeCollection", field_name: str, expected_value: Any):
        self._collection = collection
        self._field_name = field_name
        self._expected_value = expected_value

    def stream(self) -> list[FakeDocumentSnapshot]:
        snapshots: list[FakeDocumentSnapshot] = []
        for doc_id, payload in self._collection.store.items():
            if payload.get(self._field_name) == self._expected_value:
                snapshots.append(FakeDocumentSnapshot(self._collection, doc_id))
        return snapshots


class FakeCollection:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def document(self, doc_id: str | None = None) -> FakeDocumentReference:
        if doc_id is None:
            self._counter += 1
            doc_id = f"doc-{self._counter}"
        return FakeDocumentReference(self, doc_id)

    def where(self, field_name: str, op: str, expected_value: Any) -> FakeQuery:
        if op != "==":
            raise NotImplementedError("FakeCollection only supports equality filters.")
        return FakeQuery(self, field_name, expected_value)


class VectorIndexServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = AuthenticatedUser(uid="user-123", email="hr@example.com")
        self.fake_uploaded_files = FakeCollection()
        self.fake_file_extractions = FakeCollection()
        self.fake_vectors = FakeCollection()
        self.fixed_time = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)

        self.original_uploaded_files = account_repo.uploaded_files
        self.original_file_extractions = account_repo.file_extractions
        self.original_server_timestamp = account_repo.server_timestamp
        self.original_vector_library = vector_repository.vector_library
        self.original_embed_text = vector_index_service.embed_text
        self.original_vector_store_collection = os.getenv("VECTOR_STORE_FIRESTORE_COLLECTION")

        account_repo.uploaded_files = lambda: self.fake_uploaded_files  # type: ignore[assignment]
        account_repo.file_extractions = lambda: self.fake_file_extractions  # type: ignore[assignment]
        account_repo.server_timestamp = lambda: self.fixed_time  # type: ignore[assignment]
        vector_repository.vector_library = lambda collection_name: self.fake_vectors  # type: ignore[assignment]
        vector_index_service.embed_text = lambda text, model: [0.9, 0.1]
        os.environ["VECTOR_STORE_FIRESTORE_COLLECTION"] = "vectorLibraryRecords"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        account_repo.uploaded_files = self.original_uploaded_files  # type: ignore[assignment]
        account_repo.file_extractions = self.original_file_extractions  # type: ignore[assignment]
        account_repo.server_timestamp = self.original_server_timestamp  # type: ignore[assignment]
        vector_repository.vector_library = self.original_vector_library  # type: ignore[assignment]
        vector_index_service.embed_text = self.original_embed_text
        if self.original_vector_store_collection is None:
            os.environ.pop("VECTOR_STORE_FIRESTORE_COLLECTION", None)
        else:
            os.environ["VECTOR_STORE_FIRESTORE_COLLECTION"] = self.original_vector_store_collection
        get_settings.cache_clear()

    def test_save_uploaded_file_auto_indexes_vector_record(self) -> None:
        file_id = uploaded_file_service.save_uploaded_file(
            self.user,
            {
                "fileName": "frontend-react-cv.pdf",
                "fileType": "cv",
                "fileSize": 2048,
                "mimeType": "application/pdf",
                "ocrMethod": "browser-local",
                "extractedText": "Frontend engineer with React, Next.js, TypeScript, API integration and product delivery experience." * 4,
                "processingTimeMs": 1200,
                "candidateName": "Nguyen Van A",
                "jobPosition": "Frontend Engineer",
            },
        )

        uploaded_file = self.fake_uploaded_files.store[file_id]
        self.assertEqual(uploaded_file["vectorStatus"], "ready")
        self.assertEqual(uploaded_file["vectorCollectionKey"], "it")
        self.assertEqual(uploaded_file["vectorRecordId"], f"uploaded-file-{file_id}")

        vector_record = self.fake_vectors.store[f"uploaded-file-{file_id}"]
        self.assertEqual(vector_record["collectionKey"], "it")
        self.assertEqual(vector_record["name"], "Nguyen Van A")
        self.assertEqual(vector_record["metadata"]["ownerUid"], "user-123")
        self.assertEqual(vector_record["metadata"]["fileType"], "cv")
        self.assertEqual(vector_record["vectorModel"], get_settings().gemini_embedding_model)
        self.assertEqual(len(self.fake_file_extractions.store), 1)
        extraction_record = next(iter(self.fake_file_extractions.store.values()))
        self.assertEqual(extraction_record["uid"], "user-123")
        self.assertEqual(extraction_record["fileName"], "frontend-react-cv.pdf")
        self.assertEqual(extraction_record["documentType"], "cv")
        self.assertGreater(extraction_record["extractedTextLength"], 0)

    def test_delete_uploaded_file_removes_vector_record(self) -> None:
        file_id = uploaded_file_service.save_uploaded_file(
            self.user,
            {
                "fileName": "backend-fastapi.pdf",
                "fileType": "cv",
                "fileSize": 1024,
                "mimeType": "application/pdf",
                "ocrMethod": "browser-local",
                "extractedText": "Backend engineer with Python, FastAPI, Docker, PostgreSQL and API design experience." * 4,
                "processingTimeMs": 800,
                "candidateName": "Tran Thi B",
                "jobPosition": "Backend Engineer",
            },
        )

        self.assertIn(f"uploaded-file-{file_id}", self.fake_vectors.store)
        self.assertTrue(uploaded_file_service.delete_file(self.user, file_id))
        self.assertNotIn(file_id, self.fake_uploaded_files.store)
        self.assertNotIn(f"uploaded-file-{file_id}", self.fake_vectors.store)

    def test_rebuild_uploaded_file_vector_index_reports_indexed_and_skipped(self) -> None:
        self.fake_uploaded_files.store["file-1"] = {
            "uid": "user-123",
            "email": "hr@example.com",
            "fileName": "designer.pdf",
            "fileType": "cv",
            "fileSize": 1000,
            "mimeType": "application/pdf",
            "ocrMethod": "browser-local",
            "extractedText": "Product designer with Figma, UI/UX research, prototyping and design system experience." * 4,
            "candidateName": "Le Thi C",
            "jobPosition": "Product Designer",
            "uploadedAt": self.fixed_time,
        }
        self.fake_uploaded_files.store["file-2"] = {
            "uid": "user-123",
            "email": "hr@example.com",
            "fileName": "job-description.pdf",
            "fileType": "jd",
            "fileSize": 900,
            "mimeType": "application/pdf",
            "ocrMethod": "browser-local",
            "extractedText": "Hiring product designer",
            "uploadedAt": self.fixed_time,
        }

        result = vector_index_service.rebuild_uploaded_file_vector_index(self.user, limit_count=10)

        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertIn("uploaded-file-file-1", self.fake_vectors.store)
        self.assertEqual(self.fake_uploaded_files.store["file-2"]["vectorStatus"], "skipped")


if __name__ == "__main__":
    unittest.main()
