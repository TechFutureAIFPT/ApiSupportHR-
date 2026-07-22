from __future__ import annotations

import os
import unittest

from app.core.ai_contract import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_VECTOR_INDEX_VERSION,
    embedding_prompt,
    is_current_vector_contract,
    rank_from_score,
)
from app.core.config import get_settings
from app.repositories.firestore import vector_repository
from app.services.account.cache_service import build_cv_jd_cache_key
from app.services.analysis_grounding_service import _is_approved, _rubric_matches, _schema_matches
from app.services.local_classifier_service import get_classifier_status
from app.services.rubric_service import list_rubrics, resolve_scoring_rubric, validate_weights


class AiContractV2Tests(unittest.TestCase):
    def test_rank_policy_is_shared(self) -> None:
        self.assertEqual(rank_from_score(75), "A")
        self.assertEqual(rank_from_score(74.99), "B")
        self.assertEqual(rank_from_score(50), "B")
        self.assertEqual(rank_from_score(49.99), "C")

    def test_embedding_contract_and_prompt(self) -> None:
        self.assertEqual(DEFAULT_EMBEDDING_MODEL, "gemini-embedding-2")
        self.assertEqual(DEFAULT_EMBEDDING_DIMENSION, 768)
        self.assertEqual(
            embedding_prompt(" senior backend ", task="retrieval_query"),
            "task: search result | query: senior backend",
        )
        self.assertTrue(is_current_vector_contract(
            model=DEFAULT_EMBEDDING_MODEL,
            dimension=768,
            index_version=DEFAULT_VECTOR_INDEX_VERSION,
        ))
        self.assertFalse(is_current_vector_contract(
            model="gemini-embedding-001",
            dimension=768,
            index_version=DEFAULT_VECTOR_INDEX_VERSION,
        ))

    def test_retired_embedding_env_is_migrated(self) -> None:
        previous = os.getenv("GEMINI_EMBEDDING_MODEL")
        try:
            os.environ["GEMINI_EMBEDDING_MODEL"] = "gemini-embedding-001"
            get_settings.cache_clear()
            self.assertEqual(get_settings().gemini_embedding_model, DEFAULT_EMBEDDING_MODEL)
        finally:
            if previous is None:
                os.environ.pop("GEMINI_EMBEDDING_MODEL", None)
            else:
                os.environ["GEMINI_EMBEDDING_MODEL"] = previous
            get_settings.cache_clear()

    def test_all_eight_role_rubrics_total_100(self) -> None:
        rubrics = list_rubrics(version="v2")
        self.assertEqual(len(rubrics), 8)
        for rubric in rubrics:
            self.assertEqual(validate_weights(rubric["weights"]), 100.0)

    def test_invalid_recruiter_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "total 100"):
            resolve_scoring_rubric(
                jd_text="Backend developer using Python and FastAPI",
                hard_filters={"jobTitle": "Backend Developer"},
                requested_weights={"skills": {"name": "Skills", "weight": 80}},
                rubric_version="v2",
            )

    def test_cache_key_changes_for_every_scoring_input(self) -> None:
        base = dict(
            cv_id="cv-1",
            jd_text="Python backend",
            cv_text="FastAPI engineer",
            weights={"fit": {"name": "Fit", "weight": 100}},
            hard_filters={"location": "Ha Noi"},
            rubric_version="v2",
            classifier_version="model-v1",
        )
        first = build_cv_jd_cache_key(**base)
        self.assertNotEqual(first, build_cv_jd_cache_key(**{**base, "cv_text": "Java engineer"}))
        self.assertNotEqual(first, build_cv_jd_cache_key(**{**base, "hard_filters": {"location": "Da Nang"}}))
        self.assertNotEqual(first, build_cv_jd_cache_key(**{**base, "classifier_version": "model-v2"}))

    def test_exemplars_are_pending_by_default(self) -> None:
        self.assertFalse(_is_approved({}))
        self.assertFalse(_is_approved({"status": "approved"}))
        self.assertFalse(_is_approved({"approved": True, "status": "pending"}))
        self.assertTrue(_is_approved({"approved": True, "status": "approved"}))
        self.assertFalse(_rubric_matches({}, "v2"))
        self.assertTrue(_rubric_matches({"rubricVersion": "v2"}, "v2"))
        self.assertFalse(_schema_matches({}))
        self.assertFalse(_schema_matches({"schemaVersion": "supporthr-exemplar-v1"}))
        self.assertTrue(_schema_matches({"schemaVersion": "supporthr-exemplar-v2"}))

    def test_packaged_classifier_passes_manifest_readiness(self) -> None:
        status = get_classifier_status()
        self.assertTrue(status["ready"], status.get("error"))
        self.assertEqual(status["model_version"], "cv-industry-24-v1")
        self.assertEqual(status["label_count"], 24)

    def test_native_vector_search_applies_contract_prefilters(self) -> None:
        captured: dict[str, object] = {"filters": []}

        class FakeDoc:
            id = "approved-1"

            def to_dict(self):
                return {"_vectorDistance": 0.1, "approved": True, "status": "approved"}

        class FakeQuery:
            def where(self, *, filter):
                captured["filters"].append((filter.field_path, filter.op_string, filter.value))
                return self

            def find_nearest(self, **kwargs):
                captured["nearest"] = kwargs
                return self

            def stream(self):
                return [FakeDoc()]

        original = vector_repository.vector_library
        try:
            vector_repository.vector_library = lambda _: FakeQuery()  # type: ignore[assignment]
            result = vector_repository.find_nearest_approved_exemplars(
                collection_name="approvedExemplars",
                query_vector=[0.1, 0.2],
                rubric_version="v2",
                vector_index_version="gemini-embedding-2-768-v1",
                limit=2,
                similarity_threshold=0.75,
            )
        finally:
            vector_repository.vector_library = original  # type: ignore[assignment]

        self.assertEqual(
            captured["filters"],
            [
                ("status", "==", "approved"),
                ("approved", "==", True),
                ("rubricVersion", "==", "v2"),
                ("vectorIndexVersion", "==", "gemini-embedding-2-768-v1"),
            ],
        )
        self.assertEqual(captured["nearest"]["distance_threshold"], 0.25)
        self.assertAlmostEqual(result[0]["similarity"], 0.9)


if __name__ == "__main__":
    unittest.main()
