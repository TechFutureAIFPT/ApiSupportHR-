from __future__ import annotations

import os
import unittest
from typing import Any

from app.core.config import get_settings
from app.repositories.postgres import vector_repository as repo
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
            "VECTOR_STORE_COLLECTION": os.getenv("VECTOR_STORE_COLLECTION"),
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

    def test_candidate_enrichment_similarity_uses_vector_store_result(self) -> None:
        candidate_enrichment_service.search_similar_records = lambda industry, cv_text, top_k=3, min_similarity=0.0, owner_uid=None, exclude_file_names=None, query_vector=None: {
            "provider": "supabase",
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
        self.assertEqual(result["provider"], "supabase")
        self.assertEqual(result["collectionKey"], "it")
        self.assertEqual(result["queryModel"], "gemini-embedding-001")
        self.assertEqual(result["recordCount"], 4)
        self.assertEqual(result["bonusPoints"], 3.5)

    def test_enrich_candidates_restores_job_fit_from_jd_cv_embedding(self) -> None:
        candidate_enrichment_service.embed_text = lambda text, model=None: [1.0, 0.0]
        candidate_enrichment_service.search_similar_records = (
            lambda industry, cv_text, top_k=3, min_similarity=0.0, owner_uid=None, exclude_file_names=None, query_vector=None: None
        )

        enriched = candidate_enrichment_service.enrich_candidates(
            candidates=[
                {
                    "id": "candidate-1",
                    "fileName": "candidate-1.pdf",
                    "jobTitle": "Backend Developer",
                    "industry": "IT",
                    "department": "Engineering",
                    "analysis": {
                        "Tong diem": 42,
                        "Chi tiet": [
                            {
                                "Tieu chi": "Phu hop JD (Job Fit)",
                                "Diem": "0/20",
                                "Dan chung": "Chua co",
                                "Giai thich": "Chua tinh semantic match",
                            },
                            {
                                "Tieu chi": "Kinh nghiem",
                                "Diem": "10/20",
                                "Dan chung": "Python FastAPI GraphQL Docker",
                                "Giai thich": "Co kinh nghiem backend",
                            },
                        ],
                    },
                }
            ],
            cv_text_map={
                "candidate-1.pdf": "Python FastAPI GraphQL Docker backend engineer with REST API experience.",
            },
            jd_text="Backend developer can Python FastAPI GraphQL Docker va xay dung REST API.",
            hard_filters={},
            owner_uid="user-123",
        )

        self.assertEqual(len(enriched), 1)
        candidate = enriched[0]
        details = (
            candidate["analysis"].get("Chi tiÃ¡ÂºÂ¿t")
            or candidate["analysis"].get("Chi tiÃƒÂ¡Ã‚ÂºÃ‚Â¿t")
            or candidate["analysis"].get("Chi tiet")
            or []
        )
        job_fit_detail = next(
            item for item in details
            if "Job Fit" in str(item.get("TiÃƒÂªu chÃƒÂ­") or item.get("TiÃƒÆ’Ã‚Âªu chÃƒÆ’Ã‚Â­") or item.get("Tieu chi") or "")
        )
        self.assertIn("20/20", str(job_fit_detail.get("Ã„ÂiÃ¡Â»Æ’m") or job_fit_detail.get("Diem") or ""))
        self.assertEqual(candidate["analysis"]["Tong diem"], 62.0)
        self.assertAlmostEqual(candidate["jdCvMatchInsights"]["similarity"], 1.0)
        self.assertEqual(candidate["jdCvMatchInsights"]["weightedScore"], 20.0)

    def test_search_similar_records_from_supabase_honors_owner_uid(self) -> None:
        fake_vectors = FakeCollection()
        fake_vectors.store["uploaded-file-1"] = {
            "id": "uploaded-file-1",
            "collectionKey": "it",
            "name": "Candidate One",
            "role": "Backend Engineer",
            "metadata": {"ownerUid": "user-123", "fileType": "cv"},
            "embeddingModel": "gemini-embedding-2",
            "embeddingDimension": 768,
            "vectorIndexVersion": "gemini-embedding-2-768-v1",
            "vector": [1.0, 0.0],
        }
        fake_vectors.store["uploaded-file-2"] = {
            "id": "uploaded-file-2",
            "collectionKey": "it",
            "name": "Candidate Two",
            "role": "Frontend Engineer",
            "metadata": {"ownerUid": "user-999", "fileType": "cv"},
            "embeddingModel": "gemini-embedding-2",
            "embeddingDimension": 768,
            "vectorIndexVersion": "gemini-embedding-2-768-v1",
            "vector": [1.0, 0.0],
        }

        repo.vector_library = lambda collection_name: fake_vectors  # type: ignore[assignment]
        os.environ["VECTOR_STORE_COLLECTION"] = "vectorLibraryRecords"
        get_settings.cache_clear()
        vector_store_service.embed_text = lambda text, model: [1.0, 0.0]

        result = vector_store_service.search_similar_records(
            "it",
            "Python FastAPI backend",
            top_k=3,
            provider="supabase",
            owner_uid="user-123",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["provider"], "supabase")
        self.assertEqual(result["recordCount"], 1)
        self.assertEqual(result["topMatches"][0]["id"], "uploaded-file-1")

    def test_search_similar_records_from_supabase_excludes_same_file_name(self) -> None:
        fake_vectors = FakeCollection()
        fake_vectors.store["uploaded-file-1"] = {
            "id": "uploaded-file-1",
            "collectionKey": "it",
            "name": "Current Candidate",
            "role": "Backend Engineer",
            "metadata": {"ownerUid": "user-123", "fileType": "cv", "fileName": "same-file.pdf"},
            "embeddingModel": "gemini-embedding-2",
            "embeddingDimension": 768,
            "vectorIndexVersion": "gemini-embedding-2-768-v1",
            "vector": [1.0, 0.0],
        }
        fake_vectors.store["uploaded-file-2"] = {
            "id": "uploaded-file-2",
            "collectionKey": "it",
            "name": "Reference Candidate",
            "role": "Platform Engineer",
            "metadata": {"ownerUid": "user-123", "fileType": "cv", "fileName": "other-file.pdf"},
            "embeddingModel": "gemini-embedding-2",
            "embeddingDimension": 768,
            "vectorIndexVersion": "gemini-embedding-2-768-v1",
            "vector": [0.95, 0.05],
        }

        repo.vector_library = lambda collection_name: fake_vectors  # type: ignore[assignment]
        os.environ["VECTOR_STORE_COLLECTION"] = "vectorLibraryRecords"
        get_settings.cache_clear()
        vector_store_service.embed_text = lambda text, model: [1.0, 0.0]

        result = vector_store_service.search_similar_records(
            "it",
            "Python FastAPI backend",
            provider="supabase",
            owner_uid="user-123",
            exclude_file_names=["same-file.pdf"],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["recordCount"], 1)
        self.assertEqual(result["topMatches"][0]["id"], "uploaded-file-2")


if __name__ == "__main__":
    unittest.main()
