from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import sha256_file, stable_id
from .dedupe import assign_near_duplicate_groups, content_hash
from .privacy import redact_pii
from .registry import ensure_use_allowed
from .text import canonical_text_for_hash, normalize_document_text


SKILL_BENCHMARK_SCHEMA_VERSION = "supporthr-skill-benchmark-v1"


def prepare_skill_benchmark(
    *,
    source: dict[str, Any],
    input_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    ensure_use_allowed(source, "skill_linker_evaluation")
    csv_paths = sorted(input_root.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No CSV files found under {input_root}")

    records: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], str] = {}
    split_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    cross_split_duplicates = 0
    same_split_duplicates = 0
    source_files: list[dict[str, Any]] = []
    for csv_path in csv_paths:
        split = csv_path.stem
        source_files.append({
            "path": csv_path.name,
            "sha256": sha256_file(csv_path),
            "size": csv_path.stat().st_size,
        })
        with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            if not {"sentence", "label"}.issubset(headers):
                raise ValueError(f"{csv_path} is missing sentence/label columns.")
            for row_number, row in enumerate(reader, start=2):
                sentence = normalize_document_text(row.get("sentence"))
                label = normalize_document_text(row.get("label"))
                redaction = redact_pii(sentence)
                reason_codes: list[str] = []
                if not sentence:
                    reason_codes.append("empty_sentence")
                if not label:
                    reason_codes.append("empty_skill_label")
                if not redaction.safe_for_release:
                    reason_codes.append("pii_remaining_after_redaction")
                key = (canonical_text_for_hash(redaction.text), label)
                previous_split = seen.get(key)
                if previous_split == split:
                    same_split_duplicates += 1
                    reason_codes.append("same_split_duplicate")
                elif previous_split:
                    cross_split_duplicates += 1
                    reason_codes.append("cross_split_duplicate")
                if reason_codes:
                    quarantine.append({
                        "sourceFile": csv_path.name,
                        "sourceRow": row_number,
                        "reasonCodes": sorted(set(reason_codes)),
                        "recordHash": stable_id(*key),
                    })
                    continue
                seen[key] = split
                record = {
                    "schemaVersion": SKILL_BENCHMARK_SCHEMA_VERSION,
                    "recordId": stable_id(source["id"], split, *key),
                    "sourceId": source["id"],
                    "sourceRevision": source["revision"],
                    "sourceFile": csv_path.name,
                    "split": split,
                    "sentence": redaction.text,
                    "mention": normalize_document_text(row.get("span")),
                    "subMention": normalize_document_text(row.get("sub_span")),
                    "canonicalSkillId": label,
                    "redaction": {
                        "version": redaction.version,
                        "counts": redaction.counts,
                        "safeForRelease": redaction.safe_for_release,
                    },
                    "intendedUse": "skill_linker_evaluation",
                }
                records.append(record)
                split_counts[split] += 1
                label_counts[label] += 1

    unique_sentences: dict[str, str] = {}
    for record in records:
        sentence_hash = content_hash(str(record["sentence"]))
        unique_sentences.setdefault(sentence_hash, str(record["sentence"]))
    sentence_groups, near_duplicate_sentence_pairs = assign_near_duplicate_groups(
        [
            {"documentId": sentence_hash, "cleanText": sentence}
            for sentence_hash, sentence in unique_sentences.items()
        ],
        max_hamming_distance=3,
    )
    sentence_annotation_counts: Counter[str] = Counter()
    for record in records:
        sentence_hash = content_hash(str(record["sentence"]))
        sentence_annotation_counts[sentence_hash] += 1
        record["sentenceEntityGroupId"] = sentence_groups[sentence_hash]

    output_dir.mkdir(parents=True, exist_ok=True)
    curated_path = output_dir / "curated" / f"{source['id']}.jsonl"
    quarantine_path = output_dir / "quarantine" / f"{source['id']}.jsonl"
    report_path = output_dir / "reports" / f"{source['id']}.audit.json"
    curated_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    for path, values in ((curated_path, records), (quarantine_path, quarantine)):
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for value in values:
                handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schemaVersion": SKILL_BENCHMARK_SCHEMA_VERSION,
        "sourceId": source["id"],
        "sourceRevision": source["revision"],
        "license": source["license"],
        "intendedUse": "skill_linker_evaluation",
        "sourceFiles": source_files,
        "acceptedRows": len(records),
        "quarantinedRows": len(quarantine),
        "sameSplitDuplicates": same_split_duplicates,
        "crossSplitDuplicates": cross_split_duplicates,
        "splitDistribution": dict(sorted(split_counts.items())),
        "labelCount": len(label_counts),
        "uniqueSentenceCount": len(unique_sentences),
        "repeatedSentenceAnnotations": sum(
            count - 1 for count in sentence_annotation_counts.values() if count > 1
        ),
        "nearDuplicateSentencePairs": near_duplicate_sentence_pairs,
        "sentenceEntityGroupCount": len(set(sentence_groups.values())),
        "qualityGatePassed": all(
            "pii_remaining_after_redaction" not in item["reasonCodes"]
            for item in quarantine
        ),
        "trainingAllowed": False,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "report": report,
        "paths": {
            "curated": str(curated_path),
            "quarantine": str(quarantine_path),
            "report": str(report_path),
        },
    }
