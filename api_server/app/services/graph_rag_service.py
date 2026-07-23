from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

from app.core.ai_contract import GRAPH_FACT_SCHEMA_VERSION
from app.core.config import Settings, get_settings


ALLOWED_PREDICATES = {
    "ASSOCIATED_WITH_SKILL",
    "REQUIRES_SKILL",
    "PREFERS_SKILL",
    "BELONGS_TO_SKILL_FAMILY",
    "VALIDATES_SKILL",
}
DEFAULT_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "graphrag" / "approved_graph_facts.jsonl"
)

_cache_lock = threading.Lock()
_cache_key: tuple[str, int, int] | None = None
_cache_facts: list[dict[str, Any]] = []
_cache_error = ""


def _lookup(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").casefold()
    return re.sub(r"[^a-z0-9+#.]+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    return {token for token in _lookup(value).split() if len(token) >= 2}


def _artifact_path(settings: Settings, override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    configured = str(settings.graph_rag_artifact_path or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ARTIFACT_PATH


def _is_runtime_fact(record: dict[str, Any]) -> bool:
    subject = record.get("subject")
    target = record.get("object")
    provenance = record.get("provenance")
    return (
        record.get("schemaVersion") == GRAPH_FACT_SCHEMA_VERSION
        and record.get("status") == "approved"
        and record.get("approved") is True
        and record.get("decisionImpact") == "none"
        and record.get("predicate") in ALLOWED_PREDICATES
        and isinstance(subject, dict)
        and bool(subject.get("id"))
        and bool(subject.get("label"))
        and isinstance(target, dict)
        and bool(target.get("id"))
        and bool(target.get("label"))
        and isinstance(provenance, dict)
        and bool(provenance.get("sourceChecksum"))
        and bool(provenance.get("reviewer"))
    )


def _read_facts(path: Path) -> tuple[list[dict[str, Any]], str]:
    global _cache_key, _cache_facts, _cache_error
    try:
        if not path.is_file():
            return [], f"artifact_not_found:{path}"
        stat = path.stat()
    except OSError as error:
        return [], f"artifact_stat_failed:{error}"
    key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    with _cache_lock:
        if _cache_key == key:
            return list(_cache_facts), _cache_error
        facts: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        errors.append(f"invalid_json_line:{line_number}")
                        continue
                    if isinstance(value, dict) and _is_runtime_fact(value):
                        facts.append(value)
        except OSError as error:
            errors.append(f"artifact_read_failed:{error}")
        _cache_key = key
        _cache_facts = facts
        _cache_error = ",".join(errors[:10])
        return list(facts), _cache_error


def _fact_terms(fact: dict[str, Any]) -> tuple[set[str], set[str]]:
    subject = fact.get("subject") or {}
    target = fact.get("object") or {}
    subject_terms = _tokens(subject.get("label"))
    object_values = [target.get("label"), *(target.get("aliases") or [])]
    object_terms: set[str] = set()
    for value in object_values:
        object_terms.update(_tokens(value))
    return subject_terms, object_terms


def _retrieval_score(
    fact: dict[str, Any],
    *,
    jd_tokens: set[str],
    cv_tokens: set[str],
    hint_tokens: set[str],
) -> float:
    subject_terms, object_terms = _fact_terms(fact)
    if not subject_terms or not object_terms:
        return 0.0
    subject_overlap = len(subject_terms & (jd_tokens | hint_tokens)) / len(subject_terms)
    skill_overlap = len(object_terms & (jd_tokens | cv_tokens)) / len(object_terms)
    if subject_overlap == 0 and skill_overlap == 0:
        return 0.0
    observation = fact.get("observation") or {}
    observed_rate = observation.get("rate")
    rate = float(observed_rate) if isinstance(observed_rate, (int, float)) else 0.0
    return round(min(1.0, subject_overlap * 0.55 + skill_overlap * 0.35 + min(rate, 1.0) * 0.10), 6)


def _public_fact(fact: dict[str, Any], score: float) -> dict[str, Any]:
    provenance = fact.get("provenance") or {}
    return {
        "id": fact.get("id"),
        "subject": fact.get("subject"),
        "predicate": fact.get("predicate"),
        "object": fact.get("object"),
        "observation": fact.get("observation") or {},
        "retrievalScore": score,
        "provenance": {
            "sourceArtifact": provenance.get("sourceArtifact"),
            "sourceChecksum": provenance.get("sourceChecksum"),
            "reviewer": provenance.get("reviewer"),
            "reviewedAt": provenance.get("reviewedAt"),
        },
    }


def build_graph_rag_context(
    *,
    jd_text: str,
    cv_text: str,
    industry_hints: list[str] | None = None,
    settings: Settings | None = None,
    artifact_path: Path | None = None,
    enabled: bool | None = None,
    shadow_mode: bool | None = None,
) -> dict[str, Any]:
    resolved_settings = settings or get_settings()
    resolved_enabled = resolved_settings.graph_rag_enabled if enabled is None else enabled
    resolved_shadow = resolved_settings.graph_rag_shadow_mode if shadow_mode is None else shadow_mode
    path = _artifact_path(resolved_settings, artifact_path)
    base = {
        "schemaVersion": GRAPH_FACT_SCHEMA_VERSION,
        "enabled": bool(resolved_enabled),
        "shadowMode": bool(resolved_shadow),
        "decisionImpact": "none",
        "artifactPath": str(path),
        "facts": [],
        "factCount": 0,
        "retrievalError": "",
    }
    if not resolved_enabled:
        return {**base, "status": "disabled"}

    facts, error = _read_facts(path)
    if not facts:
        return {
            **base,
            "status": "no_artifact" if error.startswith("artifact_not_found") else "no_approved_facts",
            "retrievalError": error,
        }

    jd_tokens = _tokens(jd_text)
    cv_tokens = _tokens(cv_text)
    hint_tokens = _tokens(" ".join(industry_hints or []))
    ranked = [
        (_retrieval_score(fact, jd_tokens=jd_tokens, cv_tokens=cv_tokens, hint_tokens=hint_tokens), fact)
        for fact in facts
    ]
    ranked = [(score, fact) for score, fact in ranked if score > 0]
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    selected = [
        _public_fact(fact, score)
        for score, fact in ranked[: int(resolved_settings.graph_rag_max_facts)]
    ]
    return {
        **base,
        "status": "shadow" if resolved_shadow else "advisory",
        "facts": selected,
        "factCount": len(selected),
        "loadedApprovedFactCount": len(facts),
        "retrievalError": error,
    }


def get_graph_rag_status(settings: Settings | None = None) -> dict[str, Any]:
    resolved_settings = settings or get_settings()
    path = _artifact_path(resolved_settings)
    facts, error = _read_facts(path) if resolved_settings.graph_rag_enabled else ([], "")
    return {
        "enabled": resolved_settings.graph_rag_enabled,
        "shadowMode": resolved_settings.graph_rag_shadow_mode,
        "decisionImpact": "none",
        "artifactPath": str(path),
        "approvedFactCount": len(facts),
        "error": error,
    }
