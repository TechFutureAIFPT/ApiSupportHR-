from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.account import template_service


class _DocumentReference:
    id = "template-1"

    def __init__(self) -> None:
        self.payload = None

    def set(self, payload):
        self.payload = payload


class TemplateServiceTests(unittest.TestCase):
    def test_create_template_returns_json_safe_timestamps(self) -> None:
        document = _DocumentReference()
        sentinel = object()
        user = SimpleNamespace(uid="user-1")
        payload = {
            "name": "Frontend Developer",
            "category": "Engineering",
            "jobPosition": "Frontend Developer",
            "jdText": "Build accessible web interfaces.",
            "hardFilters": {"minExp": 2},
        }

        with (
            patch.object(template_service.repo, "jd_templates", return_value=object()),
            patch.object(template_service.repo, "create_document", return_value=document),
            patch.object(template_service.repo, "server_timestamp", return_value=sentinel),
            patch.object(template_service.view_sync_service, "refresh_user_views"),
        ):
            result = template_service.create_template(user, payload)

        self.assertIs(document.payload["createdAt"], sentinel)
        self.assertIs(document.payload["updatedAt"], sentinel)
        self.assertIsInstance(result["createdAt"], int)
        self.assertIsInstance(result["updatedAt"], int)
        self.assertEqual(result["id"], "template-1")
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
