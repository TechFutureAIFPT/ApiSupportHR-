from __future__ import annotations

import io
import json
import os
import sys
import types
import unittest
from urllib.error import HTTPError

if "dotenv" not in sys.modules:
    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

if "joblib" not in sys.modules:
    joblib_module = types.ModuleType("joblib")
    joblib_module.load = lambda *args, **kwargs: None
    sys.modules["joblib"] = joblib_module

from app.core.config import get_settings
from app.services import local_classifier_service


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class LocalClassifierServiceRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            "LOCAL_CLASSIFIER_MODE": os.getenv("LOCAL_CLASSIFIER_MODE"),
            "LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL": os.getenv("LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL"),
            "LOCAL_CLASSIFIER_REMOTE_STATUS_URL": os.getenv("LOCAL_CLASSIFIER_REMOTE_STATUS_URL"),
            "LOCAL_CLASSIFIER_REMOTE_TIMEOUT_SECONDS": os.getenv("LOCAL_CLASSIFIER_REMOTE_TIMEOUT_SECONDS"),
        }
        self.original_urlopen = local_classifier_service.urlopen
        self.original_model_cache = local_classifier_service._model_cache
        self.original_model_error = local_classifier_service._model_error
        get_settings.cache_clear()
        local_classifier_service._model_cache = None
        local_classifier_service._model_error = None

    def tearDown(self) -> None:
        local_classifier_service.urlopen = self.original_urlopen
        local_classifier_service._model_cache = self.original_model_cache
        local_classifier_service._model_error = self.original_model_error
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    def test_remote_classify_uses_configured_api(self) -> None:
        captured: dict[str, object] = {}
        os.environ["LOCAL_CLASSIFIER_MODE"] = "remote"
        os.environ["LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL"] = "https://classifier.example.com/api/cv/classify-industry"
        get_settings.cache_clear()

        def fake_urlopen(request, timeout: float = 0.0):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(
                {
                    "predicted_label": "INFORMATION-TECHNOLOGY",
                    "confidence": 0.93456,
                    "top_predictions": [
                        {"label": "INFORMATION-TECHNOLOGY", "score": 0.93456},
                        {"label": "ENGINEERING", "score": 0.03123},
                    ],
                    "model_source": "remote://classifier-v1",
                }
            )

        local_classifier_service.urlopen = fake_urlopen

        result = local_classifier_service.classify_cv_text("Senior backend engineer with Python FastAPI.")

        self.assertEqual(captured["url"], "https://classifier.example.com/api/cv/classify-industry")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["payload"], {"cv_text": "senior backend engineer with python fastapi", "top_k": 3})
        self.assertEqual(result["predicted_label"], "INFORMATION-TECHNOLOGY")
        self.assertEqual(result["confidence"], 0.9346)
        self.assertEqual(result["top_predictions"][0]["score"], 0.9346)
        self.assertEqual(result["model_source"], "remote://classifier-v1")

    def test_remote_status_uses_derived_status_url(self) -> None:
        captured: dict[str, object] = {}
        os.environ["LOCAL_CLASSIFIER_MODE"] = "auto"
        os.environ["LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL"] = "https://classifier.example.com/api/cv/classify-industry"
        get_settings.cache_clear()

        def fake_urlopen(request, timeout: float = 0.0):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["timeout"] = timeout
            return FakeHttpResponse(
                {
                    "ready": True,
                    "model_source": "remote://classifier-v1",
                    "label_count": 2,
                    "labels": ["INFORMATION-TECHNOLOGY", "ENGINEERING"],
                    "error": None,
                }
            )

        local_classifier_service.urlopen = fake_urlopen

        result = local_classifier_service.get_classifier_status()

        self.assertEqual(captured["url"], "https://classifier.example.com/api/cv/classifier-status")
        self.assertEqual(captured["method"], "GET")
        self.assertTrue(result["ready"])
        self.assertEqual(result["label_count"], 2)
        self.assertEqual(result["labels"], ["INFORMATION-TECHNOLOGY", "ENGINEERING"])

    def test_remote_classifier_http_503_maps_to_not_found(self) -> None:
        os.environ["LOCAL_CLASSIFIER_MODE"] = "remote"
        os.environ["LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL"] = "https://classifier.example.com/api/cv/classify-industry"
        get_settings.cache_clear()

        def fake_urlopen(request, timeout: float = 0.0):
            raise HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"detail":"Model is warming up."}'),
            )

        local_classifier_service.urlopen = fake_urlopen

        with self.assertRaises(FileNotFoundError) as context:
            local_classifier_service.classify_cv_text("Backend engineer")

        self.assertIn("Model is warming up", str(context.exception))


if __name__ == "__main__":
    unittest.main()
