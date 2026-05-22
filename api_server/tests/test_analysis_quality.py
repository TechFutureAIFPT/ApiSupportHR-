from __future__ import annotations

import importlib
import sys
import types
import unittest


def _install_dependency_stubs() -> None:
    if "dotenv" not in sys.modules:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: None
        sys.modules["dotenv"] = dotenv_module

    if "pydantic" not in sys.modules:
        pydantic_module = types.ModuleType("pydantic")

        class BaseModel:
            def __init__(self, *args, **kwargs) -> None:
                pass

            @classmethod
            def model_validate(cls, value):
                return value

            def model_dump(self, *args, **kwargs):
                return {}

        class RootModel:
            @classmethod
            def __class_getitem__(cls, item):
                return cls

        def Field(*args, default=None, default_factory=None, **kwargs):
            if default_factory is not None:
                return default_factory()
            return default

        pydantic_module.BaseModel = BaseModel
        pydantic_module.ConfigDict = dict
        pydantic_module.Field = Field
        pydantic_module.RootModel = RootModel
        sys.modules["pydantic"] = pydantic_module

    if "firebase_admin" not in sys.modules:
        firebase_admin_module = types.ModuleType("firebase_admin")
        firebase_admin_module._apps = []
        firebase_admin_module.App = object
        firebase_admin_module.get_app = lambda: object()
        firebase_admin_module.initialize_app = lambda *args, **kwargs: object()

        auth_module = types.ModuleType("firebase_admin.auth")
        auth_module.verify_id_token = lambda *args, **kwargs: {}

        credentials_module = types.ModuleType("firebase_admin.credentials")
        credentials_module.Certificate = lambda payload: payload

        firestore_module = types.ModuleType("firebase_admin.firestore")
        firestore_module.client = lambda *args, **kwargs: object()

        firebase_admin_module.auth = auth_module
        firebase_admin_module.credentials = credentials_module
        firebase_admin_module.firestore = firestore_module

        sys.modules["firebase_admin"] = firebase_admin_module
        sys.modules["firebase_admin.auth"] = auth_module
        sys.modules["firebase_admin.credentials"] = credentials_module
        sys.modules["firebase_admin.firestore"] = firestore_module

    if "fastapi" not in sys.modules:
        fastapi_module = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code: int, detail: str) -> None:
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        fastapi_module.HTTPException = HTTPException
        sys.modules["fastapi"] = fastapi_module

    if "google" not in sys.modules:
        sys.modules["google"] = types.ModuleType("google")

    if "google.genai" not in sys.modules:
        google_genai_module = types.ModuleType("google.genai")

        class _FakeResponse:
            text = ""

        class _FakeModels:
            def generate_content(self, *args, **kwargs):
                return _FakeResponse()

        class Client:
            def __init__(self, api_key: str | None = None) -> None:
                self.models = _FakeModels()

        google_genai_module.Client = Client
        sys.modules["google.genai"] = google_genai_module
        sys.modules["google"].genai = google_genai_module  # type: ignore[attr-defined]

    if "google.generativeai" not in sys.modules:
        google_generativeai_module = types.ModuleType("google.generativeai")
        google_generativeai_module.configure = lambda *args, **kwargs: None
        google_generativeai_module.embed_content = lambda *args, **kwargs: {"embedding": [1.0, 0.0]}
        sys.modules["google.generativeai"] = google_generativeai_module


_install_dependency_stubs()
cv_analysis_service = importlib.import_module("app.services.cv_analysis_service")
candidate_enrichment_service = importlib.import_module("app.services.candidate_enrichment_service")


class AnalysisQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_embed_text = candidate_enrichment_service.embed_text
        self.original_search = candidate_enrichment_service.search_similar_records

    def tearDown(self) -> None:
        candidate_enrichment_service.embed_text = self.original_embed_text
        candidate_enrichment_service.search_similar_records = self.original_search

    def test_attach_advanced_score_breakdown_repairs_generic_reasoning(self) -> None:
        candidate = {
            "fileName": "candidate-a.pdf",
            "analysis": {
                "Tong diem": 52,
                "Chi tiet": [
                    {
                        "Tieu chi": "Ky nang",
                        "Diem": "4/10",
                        "Cong thuc": "10d trong so",
                        "Dan chung": "Python, FastAPI; REST API",
                        "Giai thich": "CV kha phu hop.",
                    }
                ],
            },
        }

        updated = cv_analysis_service.attach_advanced_score_breakdowns(
            [candidate],
            {"candidate-a.pdf": "Backend engineer with Python, FastAPI and REST API experience."},
            "Can Python FastAPI Docker va REST API.",
        )[0]

        detail = updated["analysis"]["Chi tiet"][0]
        breakdown = detail["advancedBreakdown"]

        self.assertEqual(breakdown["verdict"], "weak")
        self.assertEqual(breakdown["evidence_quality"], "strong")
        self.assertIn("Docker", breakdown["missing_requirements"])
        self.assertIn("Python", breakdown["matched_signals"])
        self.assertIn("Bo sung bang chung cu the", breakdown["improvement_suggestion"])
        self.assertIn("Docker", detail["Giai thich"])
        self.assertIn("Python", detail["Dan chung"])
        self.assertIn("=", detail["Cong thuc"])
        self.assertTrue(updated["analysis"]["Diem yeu CV"])

    def test_candidate_name_from_collapsed_vietnamese_cv_text(self) -> None:
        text = (
            "CV - L\u00ea Chi\u1ebfn Th\u00f4ng tin c\u00e1 nh\u00e2n "
            "H\u1ecd t\u00ean: L\u00ea Chi\u1ebfn Gi\u1edbi t\u00ednh: Nam "
            "Email: lechien@example.com Kinh nghi\u1ec7m: Java Spring Boot"
        )

        self.assertEqual(
            cv_analysis_service._candidate_name_from_text("CV_CNTT1.docx", text),
            "L\u00ea Chi\u1ebfn",
        )

    def test_candidate_name_from_full_name_label_in_long_line(self) -> None:
        text = (
            "Th\u00f4ng tin c\u00e1 nh\u00e2n Full name: Ng\u00f4 Th\u1ecb H\u1ed3ng V\u00e2n "
            "Date of birth: 1998 Email: hongvan@example.com"
        )

        self.assertEqual(
            cv_analysis_service._candidate_name_from_text("CV_CNTT5.docx", text),
            "Ng\u00f4 Th\u1ecb H\u1ed3ng V\u00e2n",
        )

    def test_attach_breakdowns_replaces_file_stem_candidate_name(self) -> None:
        text = (
            "Th\u00f4ng tin c\u00e1 nh\u00e2n H\u1ecd t\u00ean: Ph\u1ea1m Th\u1ecb Mai Anh "
            "Email: maianh@example.com Kinh nghi\u1ec7m: Java Spring Boot"
        )
        candidate = {"fileName": "CV_CNTT3.docx", "candidateName": "CV_CNTT3", "analysis": {"Chi tiet": []}}

        updated = cv_analysis_service.attach_advanced_score_breakdowns(
            [candidate],
            {"CV_CNTT3.docx": text},
            "Java Developer",
        )[0]

        self.assertEqual(
            updated["candidateName"],
            "Ph\u1ea1m Th\u1ecb Mai Anh",
        )

    def test_enrich_candidates_adds_classifier_backed_industry_fit(self) -> None:
        candidate_enrichment_service.embed_text = lambda text, model=None: [1.0, 0.0]
        candidate_enrichment_service.search_similar_records = (
            lambda industry, cv_text, top_k=3, min_similarity=0.0, owner_uid=None, exclude_file_names=None, query_vector=None: {
                "provider": "json",
                "collectionKey": "it",
                "queryModel": "gemini-embedding-001",
                "recordCount": 4,
                "averageSimilarity": 0.86,
                "topMatches": [
                    {
                        "id": "backend-1",
                        "name": "Backend CV",
                        "role": "Backend Engineer",
                        "relativePath": "",
                        "metadata": {},
                        "similarity": 0.86,
                    }
                ],
                "bonusPoints": 3.5,
            }
        )

        enriched = candidate_enrichment_service.enrich_candidates(
            candidates=[
                {
                    "fileName": "candidate-b.pdf",
                    "jobTitle": "Backend Developer",
                    "industry": "IT",
                    "department": "Engineering",
                    "pipelineMetadata": {
                        "collectionKeys": ["it"],
                        "classifier": {
                            "confidence": 0.82,
                            "top_predictions": [
                                {"label": "INFORMATION-TECHNOLOGY", "score": 0.82},
                            ],
                            "model_source": "local://classifier",
                        },
                    },
                    "analysis": {
                        "Tong diem": 50.0,
                        "Tá»•ng Ä‘iá»ƒm": 50.0,
                        "Chi tiÃ¡ÂºÂ¿t": [],
                    },
                }
            ],
            cv_text_map={"candidate-b.pdf": "Python FastAPI Docker backend engineer with REST API experience."},
            jd_text="Backend developer can Python FastAPI Docker va xay dung REST API.",
            hard_filters={"industry": "IT"},
            owner_uid="user-123",
        )

        candidate = enriched[0]
        self.assertIn("industryFitInsights", candidate)
        self.assertGreater(candidate["industryFitInsights"]["classifierScore"], 0)
        self.assertGreater(candidate["industryFitInsights"]["finalScore"], 0)
        self.assertIn("embeddingInsights", candidate)
        self.assertGreater(candidate["analysis"]["Tá»•ng Ä‘iá»ƒm"], 50.0)

        detail = next(
            (
                item
                for item in candidate["analysis"]["Chi tiÃ¡ÂºÂ¿t"]
                if "Classifier" in candidate_enrichment_service._get_record_value(item, ["Dan chung", "Dáº«n chá»©ng"])
            ),
            None,
        )
        self.assertIsNotNone(detail)
        assert detail is not None
        score_text = candidate_enrichment_service._get_record_value(detail, ["Diem", "Äiá»ƒm"])
        evidence_text = candidate_enrichment_service._get_record_value(detail, ["Dan chung", "Dáº«n chá»©ng"])
        self.assertIn("/5", score_text)
        self.assertIn("Classifier", evidence_text)

    def test_enrich_candidates_preserves_existing_core_details(self) -> None:
        candidate_enrichment_service.embed_text = lambda text, model=None: [1.0, 0.0]
        candidate_enrichment_service.search_similar_records = (
            lambda industry, cv_text, top_k=3, min_similarity=0.0, owner_uid=None, exclude_file_names=None, query_vector=None: None
        )

        enriched = candidate_enrichment_service.enrich_candidates(
            candidates=[
                {
                    "fileName": "candidate-core-details.pdf",
                    "jobTitle": "Backend Developer",
                    "industry": "IT",
                    "department": "Engineering",
                    "analysis": {
                        "Tong diem": 42.0,
                        "Chi tiet": [
                            {
                                "Tieu chi": "Kinh nghiem",
                                "Diem": "10/20",
                                "Cong thuc": "10/20",
                                "Dan chung": "3 nam Python FastAPI Docker",
                                "Giai thich": "Co kinh nghiem backend phu hop",
                            }
                        ],
                    },
                }
            ],
            cv_text_map={
                "candidate-core-details.pdf": "Python FastAPI Docker backend engineer with REST API experience.",
            },
            jd_text="Backend developer can Python FastAPI Docker va xay dung REST API.",
            hard_filters={},
            owner_uid="user-123",
        )

        candidate = enriched[0]
        details = candidate["analysis"].get("Chi tiet") or []
        criterion_names = [
            candidate_enrichment_service._get_record_value(item, ["Tieu chi", "TiÃªu chÃ­"])
            for item in details
            if isinstance(item, dict)
        ]

        self.assertIn("Kinh nghiem", criterion_names)
        self.assertGreaterEqual(len(details), 2)

    def test_rule_based_fallback_candidates_are_successful(self) -> None:
        candidates = cv_analysis_service.build_rule_based_fallback_candidates(
            "Backend Developer can Python FastAPI PostgreSQL Docker REST API. Minimum 2 years experience.",
            {
                "positionRelevance": {"name": "Phu hop JD", "weight": 30},
                "experience": {"name": "Kinh nghiem", "weight": 25},
                "skills": {"name": "Ky nang", "weight": 25},
                "education": {"name": "Hoc van", "weight": 10},
                "achievements": {"name": "Thanh tich", "weight": 10},
            },
            {"minExp": "2", "industry": "IT"},
            [
                {
                    "file_name": "sample_backend_cv.txt",
                    "text": (
                        "Nguyen Van A\nBackend Developer with 4 years experience building REST API "
                        "using Python, FastAPI, PostgreSQL and Docker. Bachelor of Computer Science."
                    ),
                }
            ],
            failure_reason="provider unavailable",
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["status"], "SUCCESS")
        self.assertTrue(candidate["pipelineMetadata"]["aiFallback"])
        self.assertGreater(candidate["analysis"]["Tong diem"], 0)
        self.assertGreaterEqual(len(candidate["analysis"]["Chi tiet"]), 5)


if __name__ == "__main__":
    unittest.main()
