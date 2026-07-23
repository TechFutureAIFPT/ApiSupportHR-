from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.ai_contract import GRAPH_FACT_SCHEMA_VERSION
from app.services.graph_rag_service import build_graph_rag_context


def _fact(*, status: str = "approved", approved: bool = True, reviewer: str = "reviewer-1"):
    return {
        "schemaVersion": GRAPH_FACT_SCHEMA_VERSION,
        "id": f"fact-{status}-{approved}-{reviewer}",
        "status": status,
        "approved": approved,
        "decisionImpact": "none",
        "subject": {
            "namespace": "supporthr-occupation-label",
            "id": "information-technology",
            "label": "Information Technology",
        },
        "predicate": "ASSOCIATED_WITH_SKILL",
        "object": {
            "namespace": "supporthr-skill",
            "id": "python",
            "label": "Python",
            "aliases": ["python"],
        },
        "observation": {"documentCount": 20, "labelDocumentCount": 100, "rate": 0.2},
        "provenance": {
            "sourceArtifact": "curated.jsonl",
            "sourceChecksum": "a" * 64,
            "reviewer": reviewer,
            "reviewedAt": "2026-07-23T00:00:00Z",
        },
    }


class GraphRagServiceTests(unittest.TestCase):
    def test_disabled_context_is_non_decisional(self) -> None:
        result = build_graph_rag_context(
            jd_text="Python backend engineer",
            cv_text="Python developer",
            enabled=False,
        )
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["decisionImpact"], "none")
        self.assertEqual(result["facts"], [])

    def test_only_reviewed_approved_facts_are_retrieved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "facts.jsonl"
            records = [
                _fact(),
                _fact(status="pending", approved=False),
                _fact(reviewer=""),
            ]
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            result = build_graph_rag_context(
                jd_text="Information Technology role requiring Python",
                cv_text="Backend engineer using Python and APIs",
                industry_hints=["INFORMATION-TECHNOLOGY"],
                artifact_path=path,
                enabled=True,
                shadow_mode=True,
            )
        self.assertEqual(result["status"], "shadow")
        self.assertEqual(result["loadedApprovedFactCount"], 1)
        self.assertEqual(result["factCount"], 1)
        self.assertEqual(result["decisionImpact"], "none")
        self.assertNotIn("evidenceDocumentIds", result["facts"][0]["provenance"])


if __name__ == "__main__":
    unittest.main()
