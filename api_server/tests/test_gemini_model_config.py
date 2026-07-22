from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.services.gemini_service import _config_for_model, _normalize_config


class GeminiModelConfigTests(unittest.TestCase):
    def test_default_generation_models_use_gemini_36_flash(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        self.assertEqual(settings.gemini_default_model, "gemini-3.6-flash")
        self.assertEqual(settings.gemini_cv_analysis_model, "gemini-3.6-flash")
        self.assertEqual(settings.quick_cv_gemini_model, "gemini-3.6-flash")
        self.assertEqual(settings.mobile_jd_gemini_model, "gemini-3.6-flash")

    def test_gemini_36_removes_deprecated_sampling_parameters(self) -> None:
        normalized = _normalize_config(
            {
                "temperature": 0.1,
                "topP": 0.8,
                "topK": 40,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
            }
        )

        result = _config_for_model(normalized, "gemini-3.6-flash")

        self.assertEqual(
            result,
            {
                "max_output_tokens": 8192,
                "response_mime_type": "application/json",
            },
        )

    def test_older_fallback_keeps_supported_sampling_parameters(self) -> None:
        config = {"temperature": 0.1, "top_p": 0.8, "top_k": 40}

        self.assertEqual(_config_for_model(config, "gemini-3.5-flash"), config)


if __name__ == "__main__":
    unittest.main()
