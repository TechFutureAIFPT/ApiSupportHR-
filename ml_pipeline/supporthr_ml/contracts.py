from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE_MANIFEST_SCHEMA_VERSION = "supporthr-source-manifest-v1"
NORMALIZED_DOCUMENT_SCHEMA_VERSION = "supporthr-normalized-document-v1"
GRAPH_FACT_SCHEMA_VERSION = "supporthr-graph-fact-v1"
TEXT_NORMALIZATION_VERSION = "supporthr-text-normalization-v1"
PII_REDACTION_VERSION = "supporthr-pii-redaction-v1"
DEDUPLICATION_VERSION = "supporthr-deduplication-v1"
JOB_SKILL_DATASET_SCHEMA_VERSION = "supporthr-job-skill-dataset-v1"
COMPATIBILITY_BENCHMARK_SCHEMA_VERSION = "supporthr-compatibility-benchmark-v1"
DATASET_ROUTING_REPORT_SCHEMA_VERSION = "supporthr-dataset-routing-report-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(*parts: Any, length: int = 32) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
