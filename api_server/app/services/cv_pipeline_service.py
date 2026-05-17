from __future__ import annotations

import re
from typing import Any

from app.schemas.account import AuthenticatedUser
from app.services.analysis_grounding_service import build_grounding_context
from app.services.cv_analysis_service import analyze_cv_entries
from app.services.language_service import build_analysis_text_bundle, normalize_cv_text_for_analysis


def _normalize_file_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _build_global_context_notes() -> str:
    return (
        "- Neu co section FEW-SHOT GROUNDING thi do la vi du lich su de tham khao cach lap luan.\n"
        "- Uu tien bang chung nam trong CV hien tai va JD hien tai.\n"
        "- Neu CV co ban goc va ban dich tieng Viet, uu tien ban dich de phan tich "
        "nhung van co the doi chieu thuat ngu ky thuat o ban goc.\n"
        "- Local classifier chi la goi y dinh huong, khong phai su that tuyet doi."
    )


def run_smart_cv_analysis(
    jd_text: str,
    weights: dict[str, Any],
    hard_filters: dict[str, Any],
    cv_entries: list[dict[str, str]],
    *,
    current_user: AuthenticatedUser | None = None,
) -> list[dict[str, Any]]:
    entry_contexts: dict[str, dict[str, Any]] = {}
    metadata_by_file: dict[str, dict[str, Any]] = {}
    current_file_names = [
        str(entry.get("file_name") or "").strip()
        for entry in cv_entries
        if str(entry.get("file_name") or "").strip()
    ]

    for entry in cv_entries:
        file_name = str(entry.get("file_name") or "").strip()
        raw_text = str(entry.get("text") or "")
        normalized_payload = normalize_cv_text_for_analysis(raw_text)
        grounding_payload = build_grounding_context(
            user=current_user,
            cv_text=raw_text,
            analysis_text=str(normalized_payload.get("analysis_text") or raw_text),
            file_name=file_name,
            exclude_file_names=current_file_names,
        )

        context_payload = {
            "analysis_text": build_analysis_text_bundle(normalized_payload),
            "entry_note": grounding_payload.get("entry_note") or "",
            "few_shot_examples": grounding_payload.get("few_shot_examples") or "",
        }
        entry_contexts[file_name] = context_payload
        metadata_by_file[_normalize_file_name(file_name)] = {
            "language": normalized_payload.get("language"),
            "languageConfidence": normalized_payload.get("language_confidence"),
            "wasTranslated": normalized_payload.get("was_translated"),
            "collectionKeys": grounding_payload.get("collection_keys") or [],
            "classifier": grounding_payload.get("classifier") or {},
            "groundingExampleCount": len(grounding_payload.get("exemplars") or []),
        }

    candidates = analyze_cv_entries(
        jd_text,
        weights,
        hard_filters,
        cv_entries,
        entry_contexts=entry_contexts,
        context_notes=_build_global_context_notes(),
    )

    for candidate in candidates:
        file_name = str(candidate.get("fileName") or candidate.get("file_name") or "").strip()
        metadata = metadata_by_file.get(_normalize_file_name(file_name))
        if metadata:
            candidate["pipelineMetadata"] = metadata

    return candidates
