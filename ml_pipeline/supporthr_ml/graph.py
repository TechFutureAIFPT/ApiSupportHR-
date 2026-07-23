from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .contracts import GRAPH_FACT_SCHEMA_VERSION, sha256_file, stable_id
from .privacy import detect_pii_types
from .text import normalized_lookup


def load_skill_aliases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    skills = payload.get("skills")
    if not isinstance(skills, list):
        raise ValueError("Skill alias catalog must contain a skills list.")
    return [skill for skill in skills if isinstance(skill, dict) and skill.get("id")]


def _build_alias_matcher(
    skills: list[dict[str, Any]],
) -> tuple[re.Pattern[str] | None, dict[str, set[str]]]:
    alias_to_ids: dict[str, set[str]] = defaultdict(set)
    for skill in skills:
        for value in [skill.get("label"), *(skill.get("aliases") or [])]:
            alias = normalized_lookup(value)
            if alias:
                alias_to_ids[alias].add(str(skill["id"]))
    if not alias_to_ids:
        return None, alias_to_ids
    choices = "|".join(re.escape(alias) for alias in sorted(alias_to_ids, key=lambda item: (-len(item), item)))
    return re.compile(rf"(?<!\w)(?:{choices})(?!\w)"), alias_to_ids


def _extract_with_matcher(
    text: str,
    matcher: re.Pattern[str] | None,
    alias_to_ids: dict[str, set[str]],
) -> list[str]:
    if matcher is None:
        return []
    normalized_text = normalized_lookup(text)
    matched: set[str] = set()
    for match in matcher.finditer(normalized_text):
        matched.update(alias_to_ids.get(match.group(0), set()))
    return sorted(matched)


def extract_skill_ids(text: str, skills: list[dict[str, Any]]) -> list[str]:
    matcher, alias_to_ids = _build_alias_matcher(skills)
    return _extract_with_matcher(text, matcher, alias_to_ids)


def build_pending_graph_facts(
    *,
    curated_jsonl: Path,
    skill_aliases_path: Path,
    min_document_count: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    skills = load_skill_aliases(skill_aliases_path)
    skills_by_id = {str(skill["id"]): skill for skill in skills}
    matcher, alias_to_ids = _build_alias_matcher(skills)
    observations: dict[tuple[str, str], set[str]] = defaultdict(set)
    label_totals: dict[str, set[str]] = defaultdict(set)
    with curated_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            label = str(record.get("label") or "").strip()
            document_id = str(record.get("documentId") or "")
            if not label or not document_id:
                continue
            label_totals[label].add(document_id)
            for skill_id in _extract_with_matcher(
                str(record.get("cleanText") or ""),
                matcher,
                alias_to_ids,
            ):
                observations[(label, skill_id)].add(document_id)

    source_checksum = sha256_file(curated_jsonl)
    facts: list[dict[str, Any]] = []
    for (label, skill_id), document_ids in sorted(observations.items()):
        if len(document_ids) < min_document_count:
            continue
        total = max(1, len(label_totals[label]))
        skill = skills_by_id[skill_id]
        fact_id = stable_id(label, "ASSOCIATED_WITH_SKILL", skill_id, source_checksum)
        facts.append({
            "schemaVersion": GRAPH_FACT_SCHEMA_VERSION,
            "id": fact_id,
            "status": "pending",
            "approved": False,
            "decisionImpact": "none",
            "subject": {
                "namespace": "supporthr-occupation-label",
                "id": normalized_lookup(label).replace(" ", "-"),
                "label": label,
            },
            "predicate": "ASSOCIATED_WITH_SKILL",
            "object": {
                "namespace": str(skill.get("namespace") or "supporthr-skill"),
                "id": skill_id,
                "label": skill.get("label"),
                "aliases": skill.get("aliases") or [],
            },
            "observation": {
                "documentCount": len(document_ids),
                "labelDocumentCount": total,
                "rate": round(len(document_ids) / total, 6),
            },
            "provenance": {
                "sourceArtifact": curated_jsonl.name,
                "sourceChecksum": source_checksum,
                "evidenceDocumentIds": sorted(document_ids)[:20],
                "evidenceTruncated": len(document_ids) > 20,
                "extractor": "supporthr-skill-alias-observer-v1",
            },
        })
    report = {
        "schemaVersion": GRAPH_FACT_SCHEMA_VERSION,
        "sourceArtifact": str(curated_jsonl),
        "sourceChecksum": source_checksum,
        "factCount": len(facts),
        "status": "pending",
        "decisionImpact": "none",
        "minDocumentCount": min_document_count,
    }
    return facts, report


def validate_release_facts(facts: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for index, fact in enumerate(facts):
        prefix = f"fact[{index}]"
        if fact.get("schemaVersion") != GRAPH_FACT_SCHEMA_VERSION:
            errors.append(f"{prefix}:unsupported_schema")
        if fact.get("status") != "approved" or fact.get("approved") is not True:
            errors.append(f"{prefix}:not_approved")
        if fact.get("decisionImpact") != "none":
            errors.append(f"{prefix}:decision_impact_must_be_none")
        subject_id = str((fact.get("subject") or {}).get("id") or "")
        predicate = str(fact.get("predicate") or "")
        object_id = str((fact.get("object") or {}).get("id") or "")
        key = (subject_id, predicate, object_id)
        if not all(key):
            errors.append(f"{prefix}:missing_graph_key")
        elif key in seen:
            errors.append(f"{prefix}:duplicate_graph_key")
        seen.add(key)
        provenance = fact.get("provenance") or {}
        if not provenance.get("sourceChecksum") or not provenance.get("reviewer"):
            errors.append(f"{prefix}:missing_provenance_or_reviewer")
        if detect_pii_types(json.dumps(fact, ensure_ascii=False)):
            errors.append(f"{prefix}:pii_detected")
    return errors
