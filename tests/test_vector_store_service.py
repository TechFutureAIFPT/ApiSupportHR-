from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.repositories.firestore import vector_repository as repo
from app.services import candidate_enrichment_service, vector_store_service


class FakeDocumentSnapshot:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    @property
    def exists(self) -> bool:
        return self.id in self._collection.store

    def to_dict(self) -> dict[str, Any]:
        return dict(self._collection.store.get(self.id, {}))


class FakeQuery:
    def __init__(self, collection: "FakeCollection", field_name: str, expected_value: Any):
        self._collection = collection
        self._field_name = field_name
        self._expected_value = expected_value

    def stream(self) -> list[FakeDocumentSnapshot]:
        return [
            FakeDocumentSnapshot(self._collection, doc_id)
            for doc_id, payload in self._collection.store.items()
            if payload.get(self._field_name) == self._expected_value
        ]


class FakeCollection:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def where(self, field_name: str, op: str, expected_value: Any) -> FakeQuery:
        if op != "==":
            raise NotImplementedError("Only equality filters are supported in FakeCollection.")
        return FakeQuery(self, field_name, expected_value)


class VectorStoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            "VECTOR_STORE_PROVIDER": os.getenv("VECTOR_STORE_PROVIDER"),
            "VECTOR_STORE_JSON_DIR": os.getenv("VECTOR_STORE_JSON_DIR"),
            "VECTOR_STORE_FIRESTORE_COLLECTION": os.getenv("VECTOR_STORE_FIRESTORE_COLLECTION"),
        }
        self.original_embed_text = vector_store_service.embed_text
        self.original_search = candidate_enrichment_service.search_similar_records
        self.original_vector_library = repo.vector_library
        vector_store_service.clear_vector_store_cache()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        vector_store_service.embed_text = self.original_embed_text
        candidate_enrichment_service.search_similar_records = self.original_search
        repo.vector_library = self.original_vector_library  # type: ignore[assignment]
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        vector_store_service.clear_vector_store_cache()
        get_settings.cache_clear()

    def test_search_similar_records_from_json_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_path = Path(tmp_dir) / "it-embeddings.json"
            data_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "backend-1",
                                "name": "Backend Reactivity",
                                "role": "Backend Engineer",
                                "relativePath": "samples/backend-1.md",
                                "metadata": {"level": "senior"},
                                "vector": [1.0, 0.0],
                            },
                            {
                                "id": "frontend-1",
                                "name": "Frontend React",
                                "role": "Frontend Engineer",
                                "relativePath": "samples/frontend-1.md",
                                "metadata": {"level": "mid"},
                                "vector": [0.7, 0.3],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            os.environ["VECTOR_STORE_PROVIDER"] = "json"
            os.environ["VECTOR_STORE_JSON_DIR"] = tmp_dir
            get_settings.cache_clear()
            vector_store_service.clear_vector_store_cache()
            vector_store_service.embed_text = lambda text, model: [1.0, 0.0]

            result = vector_store_service.search_similar_records("it", "Python FastAPI backend", top_k=2)

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["provider"], "json")
            self.assertEqual(result["collectionKey"], "it")
            self.assertEqual(result["queryModel"], get_settings().gemini_embedding_model)
            self.assertEqual(result["recordCount"], 2)
            self.assertEqual(len(result["topMatches"]), 2)
            self.assertEqual(result["topMatches"][0]["id"], "backend-1")
            self.assertGreater(result["averageSimilarity"], 0.9)
            self.assertGreaterEqual(result["bonusPoints"], 3.5)

    def test_candidate_enrichment_similarity_uses_vector_store_result(self) -> None:
        candidate_enrichment_service.search_similar_records = lambda industry, cv_text, top_k=3, min_similarity=0.0, owner_uid=None, exclude_file_names=None: {
            "provider": "json",
            "collectionKey": "it",
            "queryModel": "gemini-embedding-001",
            "recordCount": 4,
            "averageSimilarity": 0.86,
            "topMatches": [{"id": "backend-1", "name": "Backend", "role": "Engineer", "relativePath": "", "metadata": {}, "similarity": 0.86}],
            "bonusPoints": 3.5,
        }

        result = candidate_enrichment_service._compute_industry_similarity("it", "backend cv text")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["industry"], "it")
        self.assertEqual(result["provider"], "json")
        self.assertEqual(result["collectionKey"], "it")
        self.assertEqual(result["queryModel"], "gemini-embedding-001")
        self.assertEqual(result["recordCount"], 4)
        self.assertEqual(result["bonusPoints"], 3.5)

    def test_search_similar_records_from_firestore_honors_owner_uid(self) -> None:
        fake_vectors = FakeCollection()
        fake_vectors.store["uploaded-file-1"] = {
            "id": "uploaded-file-1",
            "collectionKey": "it",
            "name": "Candidate One",
            "role": "Backend Engineer",
            "metadata": {"ownerUid": "user-123", "fileType": "cv"},
            "vector": [1.0, 0.0],
        }
        fake_vectors.store["uploaded-file-2"] = {
            "id": "uploaded-file-2",
            "collectionKey": "it",
            "name": "Candidate Two",
            "role": "Frontend Engineer",
            "metadata": {"ownerUid": "user-999", "fileType": "cv"},
            "vector": [1.0, 0.0],
        }

        repo.vector_library = lambda collection_name: fake_vectors  # type: ignore[assignment]
        os.environ["VECTOR_STORE_PROVIDER"] = "firestore"
        get_settings.cache_clear()
        vector_store_service.embed_text = lambda text, model: [1.0, 0.0]

        result = vector_store_service.search_similar_records(
            "it",
            "Python FastAPI backend",
            top_k=3,
            provider="firestore",
            owner_uid="user-123",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["provider"], "firestore")
        self.assertEqual(result["recordCount"], 1)
        self.assertEqual(result["topMatches"][0]["id"], "uploaded-file-1")

    def test_search_similar_records_from_firestore_excludes_same_file_name(self) -> None:
        fake_vectors = FakeCollection()
        fake_vectors.store["uploaded-file-1"] = {
            "id": "uploaded-file-1",
            "collectionKey": "it",
            "name": "Current Candidate",
            "role": "Backend Engineer",
            "metadata": {"ownerUid": "user-123", "fileType": "cv", "fileName": "same-file.pdf"},
            "vector": [1.0, 0.0],
        }
        fake_vectors.store["uploaded-file-2"] = {
            "id": "uploaded-file-2",
            "collectionKey": "it",
            "name": "Reference Candidate",
            "role": "Platform Engineer",
            "metadata": {"ownerUid": "user-123", "fileType": "cv", "fileName": "other-file.pdf"},
            "vector": [0.95, 0.05],
        }

        repo.vector_library = lambda collection_name: fake_vectors  # type: ignore[assignment]
        os.environ["VECTOR_STORE_PROVIDER"] = "firestore"
        get_settings.cache_clear()
        vector_store_service.embed_text = lambda text, model: [1.0, 0.0]

        result = vector_store_service.search_similar_records(
            "it",
            "Python FastAPI backend",
            provider="firestore",
            owner_uid="user-123",
            exclude_file_names=["same-file.pdf"],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["recordCount"], 1)
        self.assertEqual(result["topMatches"][0]["id"], "uploaded-file-2")


if __name__ == "__main__":
    unittest.main()
