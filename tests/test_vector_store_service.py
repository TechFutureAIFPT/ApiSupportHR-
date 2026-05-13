from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.core.config import get_settings
from app.services import candidate_enrichment_service, vector_store_service


class VectorStoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            "VECTOR_STORE_PROVIDER": os.getenv("VECTOR_STORE_PROVIDER"),
            "VECTOR_STORE_JSON_DIR": os.getenv("VECTOR_STORE_JSON_DIR"),
            "VECTOR_STORE_FIRESTORE_COLLECTION": os.getenv("VECTOR_STORE_FIRESTORE_COLLECTION"),
        }
        self.original_embed_text = vector_store_service.embed_text
        self.original_search = candidate_enrichment_service.search_similar_records
        vector_store_service.clear_vector_store_cache()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        vector_store_service.embed_text = self.original_embed_text
        candidate_enrichment_service.search_similar_records = self.original_search
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
        candidate_enrichment_service.search_similar_records = lambda industry, cv_text, top_k=3, min_similarity=0.0: {
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


if __name__ == "__main__":
    unittest.main()
