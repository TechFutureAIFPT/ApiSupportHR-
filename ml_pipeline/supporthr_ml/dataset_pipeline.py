from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    DEDUPLICATION_VERSION,
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    PII_REDACTION_VERSION,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    TEXT_NORMALIZATION_VERSION,
    sha256_file,
    stable_id,
)
from .dedupe import assign_near_duplicate_groups, content_hash
from .privacy import redact_pii
from .registry import ensure_use_allowed
from .text import normalize_document_text


LABEL_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{1,63}$")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def prepare_csv_dataset(
    *,
    csv_path: Path,
    source: dict[str, Any],
    output_dir: Path,
    intended_use: str,
    text_column: str | None = None,
    label_column: str | None = None,
    id_column: str | None = None,
    min_chars: int = 80,
    max_chars: int = 120_000,
    max_near_duplicate_hamming: int = 3,
) -> dict[str, Any]:
    ensure_use_allowed(source, intended_use)
    csv_path = csv_path.expanduser().resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)

    schema = source.get("schema") or {}
    resolved_text_column = text_column or str(schema.get("textColumn") or "")
    resolved_label_column = label_column or str(schema.get("labelColumn") or "")
    resolved_id_column = id_column or str(schema.get("idColumn") or "")
    if not resolved_text_column:
        raise ValueError("A text column is required.")

    raw_candidates: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    total_rows = 0
    empty_header_count = 0
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        empty_header_count = sum(1 for header in headers if not str(header or "").strip())
        required = [resolved_text_column]
        if resolved_label_column:
            required.append(resolved_label_column)
        missing = [column for column in required if column not in headers]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}; available={headers[:30]}")

        for row_number, row in enumerate(reader, start=2):
            total_rows += 1
            raw_text = str(row.get(resolved_text_column) or "")
            normalized = normalize_document_text(raw_text)
            source_record_id = str(row.get(resolved_id_column) or row_number).strip()
            label = str(row.get(resolved_label_column) or "").strip().upper() if resolved_label_column else ""
            reason_codes: list[str] = []
            if len(normalized) < min_chars:
                reason_codes.append("text_too_short")
            if len(normalized) > max_chars:
                reason_codes.append("text_too_long")
            if resolved_label_column and not LABEL_PATTERN.fullmatch(label):
                reason_codes.append("invalid_label")

            redaction = redact_pii(normalized)
            if redaction.remaining_types:
                reason_codes.append("pii_remaining_after_redaction")
            if reason_codes:
                quarantine.append({
                    "sourceRecordId": source_record_id,
                    "sourceRow": row_number,
                    "reasonCodes": sorted(set(reason_codes)),
                    "rawHash": content_hash(raw_text),
                })
                continue

            normalized_hash = content_hash(redaction.text)
            raw_candidates.append({
                "schemaVersion": NORMALIZED_DOCUMENT_SCHEMA_VERSION,
                "documentId": stable_id(source["id"], normalized_hash),
                "sourceId": source["id"],
                "sourceRevision": source.get("revision") or sha256_file(csv_path),
                "sourceRecordId": source_record_id,
                "documentType": source.get("documentType") or "resume",
                "language": source.get("language") or "unknown",
                "label": label,
                "cleanText": redaction.text,
                "rawHash": content_hash(raw_text),
                "normalizedHash": normalized_hash,
                "redaction": {
                    "version": redaction.version,
                    "counts": redaction.counts,
                    "safeForRelease": redaction.safe_for_release,
                },
                "lineage": {
                    "textNormalizationVersion": TEXT_NORMALIZATION_VERSION,
                    "piiRedactionVersion": PII_REDACTION_VERSION,
                    "deduplicationVersion": DEDUPLICATION_VERSION,
                },
            })

    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in raw_candidates:
        by_hash[str(record["normalizedHash"])].append(record)

    records: list[dict[str, Any]] = []
    exact_duplicates_removed = 0
    conflicting_rows_removed = 0
    for normalized_hash, group in sorted(by_hash.items()):
        labels = {str(record.get("label") or "") for record in group}
        if len(labels) > 1:
            conflicting_rows_removed += len(group)
            quarantine.extend({
                "sourceRecordId": record["sourceRecordId"],
                "reasonCodes": ["conflicting_label_for_identical_text"],
                "normalizedHash": normalized_hash,
            } for record in group)
            continue
        canonical = sorted(group, key=lambda item: str(item["sourceRecordId"]))[0]
        records.append(canonical)
        exact_duplicates_removed += len(group) - 1

    groups, near_pairs = assign_near_duplicate_groups(
        records,
        max_hamming_distance=max_near_duplicate_hamming,
    )
    for record in records:
        record["entityGroupId"] = groups[str(record["documentId"])]

    label_distribution = Counter(str(record.get("label") or "") for record in records)
    source_sha = sha256_file(csv_path)
    manifest = {
        "schemaVersion": SOURCE_MANIFEST_SCHEMA_VERSION,
        "sourceId": source["id"],
        "provider": source.get("provider"),
        "repository": source.get("repository"),
        "revision": source.get("revision") or source_sha,
        "sourceSha256": source_sha,
        "license": source.get("license"),
        "commercialAllowed": bool(source.get("commercialAllowed")),
        "attributionRequired": bool(source.get("attributionRequired")),
        "intendedUse": intended_use,
        "documentCount": len(records),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    report = {
        "sourceId": source["id"],
        "sourcePath": str(csv_path),
        "sourceSha256": source_sha,
        "totalRows": total_rows,
        "acceptedRows": len(records),
        "quarantinedRows": len(quarantine),
        "exactDuplicatesRemoved": exact_duplicates_removed,
        "conflictingRowsRemoved": conflicting_rows_removed,
        "nearDuplicatePairs": near_pairs,
        "entityGroupCount": len(set(groups.values())),
        "emptyHeaderCount": empty_header_count,
        "labelCount": len([label for label in label_distribution if label]),
        "labelDistribution": dict(sorted(label_distribution.items())),
        "piiSafeReleaseRows": sum(
            1 for record in records if bool((record.get("redaction") or {}).get("safeForRelease"))
        ),
        "qualityGatePassed": not any(
            "pii_remaining_after_redaction" in item.get("reasonCodes", [])
            for item in quarantine
        ),
    }

    curated_path = output_dir / "curated" / f"{source['id']}.jsonl"
    quarantine_path = output_dir / "quarantine" / f"{source['id']}.jsonl"
    manifest_path = output_dir / "manifests" / f"{source['id']}.manifest.json"
    report_path = output_dir / "reports" / f"{source['id']}.audit.json"
    _write_jsonl(curated_path, records)
    _write_jsonl(quarantine_path, quarantine)
    _write_json(manifest_path, manifest)
    _write_json(report_path, report)
    return {
        "manifest": manifest,
        "report": report,
        "paths": {
            "curated": str(curated_path),
            "quarantine": str(quarantine_path),
            "manifest": str(manifest_path),
            "report": str(report_path),
        },
    }
