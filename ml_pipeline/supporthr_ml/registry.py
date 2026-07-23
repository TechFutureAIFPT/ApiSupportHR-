from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALLOWED_SOURCE_STATUSES = {"approved", "evaluation_only", "quarantine", "rejected"}


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "configs" / "datasets.json"


def load_registry(path: Path | None = None) -> dict[str, dict[str, Any]]:
    registry_path = path or default_registry_path()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Dataset registry must contain a sources list.")
    result: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Every dataset registry item must be an object.")
        source_id = str(source.get("id") or "").strip()
        if not source_id or source_id in result:
            raise ValueError(f"Dataset registry contains a missing or duplicate id: {source_id!r}")
        status = str(source.get("status") or "").strip()
        if status not in ALLOWED_SOURCE_STATUSES:
            raise ValueError(f"Dataset {source_id} has unsupported status {status!r}.")
        if not str(source.get("license") or "").strip():
            raise ValueError(f"Dataset {source_id} is missing a license decision.")
        result[source_id] = source
    return result


def get_source(source_id: str, path: Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    try:
        return registry[source_id]
    except KeyError as error:
        raise KeyError(f"Dataset {source_id!r} is not registered.") from error


def ensure_use_allowed(source: dict[str, Any], intended_use: str) -> None:
    status = str(source.get("status") or "")
    if status in {"quarantine", "rejected"}:
        raise ValueError(f"Dataset {source.get('id')} is {status} and cannot be released.")
    allowed = {str(item) for item in source.get("intendedUses") or []}
    if intended_use not in allowed:
        raise ValueError(
            f"Dataset {source.get('id')} is not approved for {intended_use}; allowed uses: {sorted(allowed)}"
        )
