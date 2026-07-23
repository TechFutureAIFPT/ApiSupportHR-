from __future__ import annotations

import ast
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import (
    COMPATIBILITY_BENCHMARK_SCHEMA_VERSION,
    JOB_SKILL_DATASET_SCHEMA_VERSION,
    PII_REDACTION_VERSION,
    TEXT_NORMALIZATION_VERSION,
    sha256_file,
    stable_id,
)
from .dedupe import assign_near_duplicate_groups, content_hash
from .privacy import redact_pii
from .registry import ensure_use_allowed
from .text import normalize_document_text, normalized_lookup


LABEL_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{1,63}$")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _parse_skills(value: Any) -> list[str]:
    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
    if not isinstance(parsed, (list, tuple, set)):
        return []
    unique: dict[str, str] = {}
    for item in parsed:
        skill = normalize_document_text(item)
        key = normalized_lookup(skill)
        if skill and key and key not in unique:
            unique[key] = skill
    return list(unique.values())


def audit_resume_source_equivalence(
    *,
    source: dict[str, Any],
    csv_path: Path,
    canonical_source: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    ensure_use_allowed(source, "classifier_source_equivalence")
    csv_path = csv_path.expanduser().resolve()
    schema = source.get("schema") or {}
    text_column = str(schema.get("textColumn") or "")
    label_column = str(schema.get("labelColumn") or "")
    id_column = str(schema.get("idColumn") or "")
    source_hash = sha256_file(csv_path)
    canonical_hash = str(canonical_source.get("revision") or "").strip().lower()

    rows = 0
    empty_texts = 0
    ids: set[str] = set()
    labels: set[str] = set()
    seen_texts: set[str] = set()
    duplicates = 0
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {text_column, label_column, id_column}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"Resume mirror is missing required columns: {missing}")
        for row in reader:
            rows += 1
            text = normalize_document_text(row.get(text_column))
            empty_texts += int(not text)
            ids.add(str(row.get(id_column) or "").strip())
            labels.add(str(row.get(label_column) or "").strip())
            text_hash = content_hash(text)
            if text_hash in seen_texts:
                duplicates += 1
            seen_texts.add(text_hash)

    byte_equivalent = len(canonical_hash) == 64 and source_hash == canonical_hash
    report = {
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "sourceSha256": source_hash,
        "canonicalSourceId": canonical_source["id"],
        "canonicalSha256": canonical_hash,
        "byteEquivalent": byte_equivalent,
        "rows": rows,
        "uniqueIds": len(ids),
        "labelCount": len(labels),
        "emptyTexts": empty_texts,
        "exactDuplicateTexts": duplicates,
        "routingDecision": "duplicate_alias_excluded_from_training" if byte_equivalent else "manual_review_required",
        "classifierTrainingRowsAdded": 0,
        "trainingAllowed": False,
    }
    report_path = output_dir / "reports" / f"{source['id']}.equivalence.json"
    _write_json(report_path, report)
    return {"report": report, "paths": {"report": str(report_path)}}


def prepare_job_skill_audit(
    *,
    source: dict[str, Any],
    parquet_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if source.get("status") != "quarantine" or "audit_only" not in set(source.get("intendedUses") or []):
        raise ValueError("Job-skill audit accepts only a registered audit_only quarantine source.")

    import pandas as pd

    parquet_path = parquet_path.expanduser().resolve()
    schema = source.get("schema") or {}
    required = [
        str(schema.get("idColumn") or ""),
        str(schema.get("categoryColumn") or ""),
        str(schema.get("titleColumn") or ""),
        str(schema.get("textColumn") or ""),
        str(schema.get("skillsColumn") or ""),
    ]
    frame = pd.read_parquet(parquet_path)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Job-skill parquet is missing required columns: {missing}")

    id_column, category_column, title_column, text_column, skills_column = required
    accepted: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    skill_frequency: Counter[str] = Counter()
    skill_display: dict[str, str] = {}
    seen_descriptions: set[str] = set()
    rows_with_pii = 0

    for row_number, row in enumerate(frame.to_dict(orient="records"), start=1):
        job_id = str(row.get(id_column) or "").strip()
        category = normalize_document_text(row.get(category_column)).upper()
        title_redaction = redact_pii(row.get(title_column))
        description_redaction = redact_pii(row.get(text_column))
        skills = _parse_skills(row.get(skills_column))
        rows_with_pii += int(bool(title_redaction.counts or description_redaction.counts))
        description_hash = content_hash(description_redaction.text)
        reason_codes: list[str] = []
        if not job_id:
            reason_codes.append("missing_job_id")
        if not LABEL_PATTERN.fullmatch(category):
            reason_codes.append("invalid_category")
        if not title_redaction.text:
            reason_codes.append("empty_job_title")
        if not description_redaction.text:
            reason_codes.append("empty_job_description")
        if not skills:
            reason_codes.append("invalid_or_empty_skill_list")
        if not title_redaction.safe_for_release or not description_redaction.safe_for_release:
            reason_codes.append("pii_remaining_after_redaction")
        if description_hash in seen_descriptions:
            reason_codes.append("duplicate_job_description")
        seen_descriptions.add(description_hash)

        if reason_codes:
            quarantine.append({
                "sourceRow": row_number,
                "sourceRecordHash": stable_id(source["id"], job_id, description_hash),
                "reasonCodes": sorted(set(reason_codes)),
            })
            continue

        normalized_skills: list[str] = []
        for skill in skills:
            skill_key = normalized_lookup(skill)
            skill_frequency[skill_key] += 1
            skill_display.setdefault(skill_key, skill)
            normalized_skills.append(stable_id("skill-candidate", skill_key))
        accepted.append({
            "schemaVersion": JOB_SKILL_DATASET_SCHEMA_VERSION,
            "recordId": stable_id(source["id"], source["revision"], job_id),
            "sourceId": source["id"],
            "sourceRevision": source["revision"],
            "jobId": job_id,
            "category": category,
            "jobTitle": title_redaction.text,
            "jobDescription": description_redaction.text,
            "skillIds": normalized_skills,
            "redaction": {
                "version": PII_REDACTION_VERSION,
                "safeForRelease": True,
                "counts": {
                    **title_redaction.counts,
                    **description_redaction.counts,
                },
            },
            "releaseEligible": False,
            "intendedUse": "audit_only",
        })

    candidates = [
        {
            "skillId": stable_id("skill-candidate", key),
            "label": skill_display[key],
            "normalizedLabel": key,
            "frequency": count,
            "status": "pending",
        }
        for key, count in skill_frequency.most_common()
    ]
    entity_groups, near_duplicate_pairs = assign_near_duplicate_groups(
        [
            {"documentId": record["recordId"], "cleanText": record["jobDescription"]}
            for record in accepted
        ],
        max_hamming_distance=3,
    )
    for record in accepted:
        record["entityGroupId"] = entity_groups[record["recordId"]]
    curated_path = output_dir / "quarantine" / f"{source['id']}.jsonl"
    rejected_path = output_dir / "rejected" / f"{source['id']}.jsonl"
    candidates_path = output_dir / "candidates" / f"{source['id']}.skills.json"
    report_path = output_dir / "reports" / f"{source['id']}.audit.json"
    _write_jsonl(curated_path, accepted)
    if quarantine:
        _write_jsonl(rejected_path, quarantine)
    elif rejected_path.exists():
        rejected_path.unlink()
    _write_json(candidates_path, {
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "status": "pending",
        "releaseEligible": False,
        "skills": candidates,
    })
    report = {
        "schemaVersion": JOB_SKILL_DATASET_SCHEMA_VERSION,
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "sourceSha256": sha256_file(parquet_path),
        "license": source["license"],
        "totalRows": int(len(frame)),
        "auditAcceptedRows": len(accepted),
        "rejectedRows": len(quarantine),
        "uniqueSkillCandidates": len(candidates),
        "rowsWithPiiDetected": rows_with_pii,
        "nearDuplicatePairs": near_duplicate_pairs,
        "entityGroupCount": len(set(entity_groups.values())),
        "trainingAllowed": False,
        "releaseEligible": False,
        "routingDecision": "quarantine_until_derivative_label_license_is_verified",
    }
    _write_json(report_path, report)
    return {
        "report": report,
        "paths": {
            "quarantineCurated": str(curated_path),
            "rejected": str(rejected_path) if quarantine else None,
            "skillCandidates": str(candidates_path),
            "report": str(report_path),
        },
    }


def prepare_compatibility_benchmark(
    *,
    source: dict[str, Any],
    json_path: Path,
    resume_source: dict[str, Any],
    resume_csv_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    ensure_use_allowed(source, "compatibility_evaluation")
    json_path = json_path.expanduser().resolve()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Compatibility dataset must be a JSON list.")
    schema = source.get("schema") or {}
    resume_column = str(schema.get("resumeColumn") or "")
    jd_column = str(schema.get("jobDescriptionColumn") or "")
    review_column = str(schema.get("reviewColumn") or "")
    instruction_column = str(schema.get("instructionColumn") or "")
    resume_schema = resume_source.get("schema") or {}
    resume_id_column = str(resume_schema.get("idColumn") or "")
    resume_text_column = str(resume_schema.get("textColumn") or "")
    resume_references: dict[str, str] = {}
    with resume_csv_path.expanduser().resolve().open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        required = {resume_id_column, resume_text_column}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"Resume reference CSV is missing required columns: {missing}")
        for row in reader:
            raw_hash = content_hash(str(row.get(resume_text_column) or ""))
            resume_references.setdefault(raw_hash, str(row.get(resume_id_column) or "").strip())

    accepted: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    job_descriptions: dict[str, dict[str, Any]] = {}
    seen_pairs: set[str] = set()
    rows_with_pii = 0
    percent_review_count = 0
    resolved_resume_references = 0
    for row_number, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            quarantine.append({"sourceRow": row_number, "reasonCodes": ["invalid_record"]})
            continue
        raw_resume_text = str(row.get(resume_column) or "")
        raw_resume_hash = content_hash(raw_resume_text)
        resume_record_id = resume_references.get(raw_resume_hash, "")
        if resume_record_id:
            resolved_resume_references += 1
        resume = redact_pii(raw_resume_text)
        jd = redact_pii(row.get(jd_column))
        review = redact_pii(row.get(review_column))
        instruction = normalize_document_text(row.get(instruction_column))
        rows_with_pii += int(bool(resume.counts or jd.counts or review.counts))
        pair_hash = content_hash(f"{resume.text}\x1f{jd.text}")
        reason_codes: list[str] = []
        if not resume.text:
            reason_codes.append("empty_resume")
        if not jd.text:
            reason_codes.append("empty_job_description")
        if not review.text:
            reason_codes.append("empty_reference_review")
        if not resume_record_id:
            reason_codes.append("resume_reference_not_found")
        if not resume.safe_for_release or not jd.safe_for_release or not review.safe_for_release:
            reason_codes.append("pii_remaining_after_redaction")
        if pair_hash in seen_pairs:
            reason_codes.append("duplicate_resume_jd_pair")
        seen_pairs.add(pair_hash)
        if reason_codes:
            quarantine.append({
                "sourceRow": row_number,
                "pairHash": pair_hash,
                "reasonCodes": sorted(set(reason_codes)),
            })
            continue
        percent_review_count += int(bool(re.search(r"\b\d{1,3}\s*%", review.text)))
        job_description_id = stable_id(source["id"], "job-description", content_hash(jd.text))
        job_descriptions.setdefault(job_description_id, {
            "jobDescriptionId": job_description_id,
            "text": jd.text,
        })
        accepted.append({
            "schemaVersion": COMPATIBILITY_BENCHMARK_SCHEMA_VERSION,
            "recordId": stable_id(source["id"], source["revision"], pair_hash),
            "sourceId": source["id"],
            "sourceRevision": source["revision"],
            "instruction": instruction,
            "resumeReference": {
                "sourceId": resume_source["id"],
                "sourceRevision": resume_source["revision"],
                "sourceRecordId": resume_record_id,
                "contentHash": raw_resume_hash,
            },
            "jobDescriptionId": job_description_id,
            "referenceReview": review.text,
            "numericCompatibilityLabel": None,
            "intendedUse": "compatibility_evaluation",
            "scoringGroundTruth": False,
            "trainingAllowed": False,
            "redaction": {
                "version": PII_REDACTION_VERSION,
                "safeForRelease": True,
            },
        })

    benchmark_path = output_dir / "evaluation" / f"{source['id']}.jsonl"
    job_descriptions_path = output_dir / "evaluation" / f"{source['id']}.job-descriptions.jsonl"
    quarantine_path = output_dir / "quarantine" / f"{source['id']}.jsonl"
    report_path = output_dir / "reports" / f"{source['id']}.audit.json"
    _write_jsonl(benchmark_path, accepted)
    _write_jsonl(job_descriptions_path, list(job_descriptions.values()))
    _write_jsonl(quarantine_path, quarantine)
    report = {
        "schemaVersion": COMPATIBILITY_BENCHMARK_SCHEMA_VERSION,
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "sourceSha256": sha256_file(json_path),
        "license": source["license"],
        "totalRows": len(payload),
        "acceptedRows": len(accepted),
        "quarantinedRows": len(quarantine),
        "rowsWithPiiDetected": rows_with_pii,
        "reviewsWithExplicitPercent": percent_review_count,
        "resumeReferencesResolved": resolved_resume_references,
        "crossSourceResumeOverlapCount": resolved_resume_references,
        "uniqueJobDescriptions": len(job_descriptions),
        "duplicateJobDescriptionReferencesRemoved": max(0, len(accepted) - len(job_descriptions)),
        "numericCompatibilityLabels": 0,
        "trainingAllowed": False,
        "scoringGroundTruth": False,
        "routingDecision": "prompt_regression_evaluation_only",
        "textNormalizationVersion": TEXT_NORMALIZATION_VERSION,
    }
    _write_json(report_path, report)
    return {
        "report": report,
        "paths": {
            "evaluation": str(benchmark_path),
            "jobDescriptions": str(job_descriptions_path),
            "quarantine": str(quarantine_path),
            "report": str(report_path),
        },
    }
