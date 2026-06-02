from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import api_app


class MobileJDApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self._old_env = {
            "MOBILE_JD_GEMINI_MODEL": os.environ.get("MOBILE_JD_GEMINI_MODEL"),
            "MOBILE_JD_GEMINI_API_KEY": os.environ.get("MOBILE_JD_GEMINI_API_KEY"),
        }

    def tearDown(self) -> None:
        self.client.close()
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    def test_standardize_jd_text_returns_ai_payload(self) -> None:
        ai_payload = {
            "score": 82,
            "missingSections": [
                {
                    "key": "salary",
                    "label": "Mức lương",
                    "reason": "JD chưa nêu khoảng lương.",
                    "priority": "high",
                }
            ],
            "weakPoints": [{"label": "Quyền lợi mỏng", "detail": "Cần bổ sung phúc lợi cụ thể."}],
            "suggestions": [{"label": "Thêm KPI", "detail": "Nêu rõ chỉ tiêu và cách đo hiệu quả."}],
            "normalizedJD": {
                "title": "Marketing Executive",
                "overview": "Phụ trách triển khai chiến dịch marketing.",
                "responsibilities": ["Lập kế hoạch nội dung", "Theo dõi hiệu quả chiến dịch"],
                "requirements": ["Tối thiểu 1 năm kinh nghiệm marketing"],
                "benefits": ["Môi trường làm việc chuyên nghiệp"],
                "workingTime": "Thứ 2 - Thứ 6",
                "location": "Hà Nội",
                "salary": "",
                "applicationInfo": "Gửi CV qua email tuyển dụng.",
                "keywords": ["marketing", "content", "campaign"],
            },
        }

        os.environ["MOBILE_JD_GEMINI_MODEL"] = "gemini-test-jd"
        os.environ["MOBILE_JD_GEMINI_API_KEY"] = "jd-key"
        get_settings.cache_clear()

        with patch("app.services.mobile_jd.standardizer_service.generate_content", return_value=json.dumps(ai_payload)) as generate:
            response = self.client.post(
                "/api/mobile/jd/standardize",
                json={
                    "jdText": "Marketing Executive\nMô tả công việc: lập kế hoạch nội dung.",
                    "targetPlatform": "topcv",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score"], 82)
        self.assertEqual(payload["platform"]["name"], "TopCV")
        self.assertEqual(payload["normalizedJD"]["title"], "Marketing Executive")
        self.assertEqual(payload["source"], "ai")
        self.assertEqual(generate.call_args.args[0], "gemini-test-jd")
        self.assertEqual(generate.call_args.kwargs["api_keys"][0], "jd-key")

    def test_standardize_jd_text_falls_back_when_ai_fails(self) -> None:
        with patch("app.services.mobile_jd.standardizer_service.generate_content", side_effect=RuntimeError("quota")):
            response = self.client.post(
                "/api/mobile/jd/standardize",
                json={
                    "jdText": "Backend Developer\nMô tả công việc: xây dựng API FastAPI.",
                    "targetPlatform": "linkedin",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "fallback")
        self.assertEqual(payload["platform"]["name"], "LinkedIn Jobs")
        self.assertGreaterEqual(payload["score"], 45)
        self.assertIn("normalizedJD", payload)

    def test_standardize_jd_file_accepts_text_upload(self) -> None:
        with patch("app.services.mobile_jd.standardizer_service.generate_content", side_effect=RuntimeError("quota")):
            response = self.client.post(
                "/api/mobile/jd/standardize-file",
                data={"target_platform": "parse_jd"},
                files={"file": ("jd.txt", b"Sales Executive\nMo ta: tu van khach hang.", "text/plain")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["platform"]["name"], "Parse JD")
        self.assertEqual(payload["source"], "fallback")


if __name__ == "__main__":
    unittest.main()
