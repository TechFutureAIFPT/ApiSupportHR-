from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from supporthr_ml.dataset_pipeline import prepare_csv_dataset
from supporthr_ml.graph import build_pending_graph_facts, validate_release_facts
from supporthr_ml.hf_dataset_adapters import (
    audit_resume_source_equivalence,
    prepare_compatibility_benchmark,
    prepare_job_skill_audit,
)
from supporthr_ml.privacy import redact_pii
from supporthr_ml.skill_benchmark import prepare_skill_benchmark


class DataPipelineTests(unittest.TestCase):
    def test_redaction_removes_common_cv_identifiers(self) -> None:
        result = redact_pii(
            "Full name: Nguyen Van A\n"
            "Email: person@example.com\n"
            "Phone: +84 912 345 678\n"
            "Address: 12 Example Street, Ha Noi\n"
            "DOB: 01/02/1999\n"
            "LinkedIn: https://linkedin.com/in/example"
        )
        self.assertTrue(result.safe_for_release)
        self.assertNotIn("person@example.com", result.text)
        self.assertNotIn("912 345 678", result.text)
        self.assertIn("[NAME]", result.text)
        self.assertIn("[ADDRESS]", result.text)

    def test_prepare_dataset_deduplicates_and_quarantines_invalid_rows(self) -> None:
        source = {
            "id": "fixture",
            "provider": "test",
            "repository": "fixture",
            "revision": "fixture-revision",
            "license": "CC0-1.0",
            "commercialAllowed": True,
            "attributionRequired": False,
            "status": "approved",
            "documentType": "resume",
            "language": "en",
            "intendedUses": ["classifier_training"],
            "schema": {"idColumn": "ID", "textColumn": "Resume_str", "labelColumn": "Category"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = root / "fixture.csv"
            text = (
                "Full name: Candidate Example\nEmail: candidate@example.com\n"
                "Backend engineer with Python, PostgreSQL, Docker and API delivery experience. "
                "Built reliable services and documented production systems."
            )
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ID", "Resume_str", "Category"])
                writer.writeheader()
                writer.writerow({"ID": "1", "Resume_str": text, "Category": "ENGINEERING"})
                writer.writerow({"ID": "2", "Resume_str": text, "Category": "ENGINEERING"})
                writer.writerow({"ID": "3", "Resume_str": "too short", "Category": "?"})
            result = prepare_csv_dataset(
                csv_path=csv_path,
                source=source,
                output_dir=root / "output",
                intended_use="classifier_training",
            )
            report = result["report"]
            self.assertEqual(report["acceptedRows"], 1)
            self.assertEqual(report["exactDuplicatesRemoved"], 1)
            self.assertEqual(report["quarantinedRows"], 1)
            curated = Path(result["paths"]["curated"]).read_text(encoding="utf-8")
            self.assertNotIn("candidate@example.com", curated)

    def test_pending_graph_facts_cannot_pass_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            curated = root / "curated.jsonl"
            aliases = root / "aliases.json"
            aliases.write_text(json.dumps({
                "skills": [{"id": "python", "label": "Python", "namespace": "supporthr-skill", "aliases": ["python"]}]
            }), encoding="utf-8")
            records = [
                {
                    "documentId": f"doc-{index}",
                    "label": "ENGINEERING",
                    "cleanText": "Python backend engineering and reliable API delivery.",
                }
                for index in range(3)
            ]
            curated.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            facts, report = build_pending_graph_facts(
                curated_jsonl=curated,
                skill_aliases_path=aliases,
                min_document_count=3,
            )
            self.assertEqual(report["factCount"], 1)
            self.assertEqual(facts[0]["decisionImpact"], "none")
            self.assertIn("fact[0]:not_approved", validate_release_facts(facts))

    def test_skill_benchmark_quarantines_cross_split_duplicates(self) -> None:
        source = {
            "id": "skill-eval",
            "revision": "a" * 40,
            "license": "MIT",
            "status": "evaluation_only",
            "intendedUses": ["skill_linker_evaluation"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root = root / "raw"
            input_root.mkdir()
            for split in ("validation", "test"):
                with (input_root / f"{split}.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["sentence", "label"])
                    writer.writeheader()
                    writer.writerow({"sentence": "Build APIs with Python.", "label": "skill/python"})
            result = prepare_skill_benchmark(
                source=source,
                input_root=input_root,
                output_dir=root / "output",
            )
            self.assertEqual(result["report"]["acceptedRows"], 1)
            self.assertEqual(result["report"]["crossSplitDuplicates"], 1)
            self.assertEqual(result["report"]["uniqueSentenceCount"], 1)
            self.assertFalse(result["report"]["trainingAllowed"])

    def test_resume_mirror_is_excluded_when_bytes_match_canonical_source(self) -> None:
        source = {
            "id": "resume-mirror",
            "status": "evaluation_only",
            "revision": "a" * 40,
            "intendedUses": ["classifier_source_equivalence"],
            "schema": {"idColumn": "ID", "textColumn": "Resume_str", "labelColumn": "Category"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            csv_path = root / "Resume.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ID", "Resume_str", "Category"])
                writer.writeheader()
                writer.writerow({"ID": 1, "Resume_str": "Python backend engineer", "Category": "IT"})
            from supporthr_ml.contracts import sha256_file

            result = audit_resume_source_equivalence(
                source=source,
                csv_path=csv_path,
                canonical_source={"id": "canonical", "revision": sha256_file(csv_path)},
                output_dir=root / "output",
            )
            self.assertTrue(result["report"]["byteEquivalent"])
            self.assertEqual(result["report"]["classifierTrainingRowsAdded"], 0)

    def test_job_skill_source_stays_quarantined_and_emits_pending_candidates(self) -> None:
        import pandas as pd

        source = {
            "id": "job-skill",
            "status": "quarantine",
            "revision": "b" * 40,
            "license": "OTHER-UNVERIFIED",
            "intendedUses": ["audit_only"],
            "schema": {
                "idColumn": "job_id",
                "categoryColumn": "category",
                "titleColumn": "job_title",
                "textColumn": "job_description",
                "skillsColumn": "job_skill_set",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parquet = root / "jobs.parquet"
            pd.DataFrame([{
                "job_id": 1,
                "category": "INFORMATION-TECHNOLOGY",
                "job_title": "Backend Engineer",
                "job_description": "Build APIs with Python and PostgreSQL.",
                "job_skill_set": "['Python', 'PostgreSQL', 'Python']",
            }]).to_parquet(parquet)
            result = prepare_job_skill_audit(
                source=source,
                parquet_path=parquet,
                output_dir=root / "output",
            )
            self.assertEqual(result["report"]["uniqueSkillCandidates"], 2)
            self.assertEqual(result["report"]["nearDuplicatePairs"], 0)
            self.assertFalse(result["report"]["trainingAllowed"])
            curated = json.loads(
                Path(result["paths"]["quarantineCurated"]).read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(len(curated["skillIds"]), 2)
            self.assertNotIn("skills", curated)

    def test_compatibility_dataset_is_evaluation_only_without_numeric_ground_truth(self) -> None:
        source = {
            "id": "compat",
            "status": "evaluation_only",
            "revision": "c" * 40,
            "license": "Apache-2.0",
            "intendedUses": ["compatibility_evaluation"],
            "schema": {
                "resumeColumn": "resume",
                "jobDescriptionColumn": "jd",
                "reviewColumn": "review",
                "instructionColumn": "instruction",
            },
        }
        resume_source = {
            "id": "resume-source",
            "revision": "d" * 40,
            "schema": {"idColumn": "ID", "textColumn": "Resume_str"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            json_path = root / "compat.json"
            resume_csv = root / "Resume.csv"
            with resume_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ID", "Resume_str"])
                writer.writeheader()
                writer.writerow({
                    "ID": "1",
                    "Resume_str": "Email: person@example.com\nPython backend engineer.",
                })
                writer.writerow({"ID": "2", "Resume_str": "Java developer."})
            json_path.write_text(json.dumps([
                {
                    "resume": "Email: person@example.com\nPython backend engineer.",
                    "jd": "Need Python and SQL.",
                    "review": "Good overlap, but no numeric ground truth.",
                    "instruction": "Review compatibility.",
                },
                {
                    "resume": "Java developer.",
                    "jd": "Need Java.",
                    "review": "",
                    "instruction": "Review compatibility.",
                },
            ]), encoding="utf-8")
            result = prepare_compatibility_benchmark(
                source=source,
                json_path=json_path,
                resume_source=resume_source,
                resume_csv_path=resume_csv,
                output_dir=root / "output",
            )
            self.assertEqual(result["report"]["acceptedRows"], 1)
            self.assertEqual(result["report"]["quarantinedRows"], 1)
            self.assertFalse(result["report"]["scoringGroundTruth"])
            self.assertEqual(result["report"]["uniqueJobDescriptions"], 1)
            record = json.loads(
                Path(result["paths"]["evaluation"]).read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(record["resumeReference"]["sourceRecordId"], "1")
            self.assertNotIn("resumeText", record)
            self.assertNotIn("jobDescription", record)


if __name__ == "__main__":
    unittest.main()
