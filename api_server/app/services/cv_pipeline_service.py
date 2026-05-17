from __future__ import annotations

import asyncio
import copy
import re
import time
import unicodedata
from typing import Any

from app.core.config import get_settings
from app.schemas.account import AuthenticatedUser
from app.services.account.cache_service import (
    build_cv_jd_cache_key,
    get_cache_entry_async,
    stable_hash,
    sync_cache_entry_async,
)
from app.services.account.history_service import sync_history_entry
from app.services.analysis_grounding_service import build_approved_grounding_context
from app.services.candidate_enrichment_service import enrich_candidates
from app.services.cv_analysis_service import analyze_cv_entries_async, attach_advanced_score_breakdowns
from app.services.language_service import build_analysis_text_bundle, normalize_cv_text_for_analysis_async


TOTAL_SCORE_KEY = "T\u1ed5ng \u0111i\u1ec3m"
RANK_KEY = "H\u1ea1ng"
LOCATION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Remote", (r"\bremote\b", r"\bwork from home\b", r"\bwfh\b", "lam viec tu xa", "tu xa")),
    ("Ha Noi", ("ha noi", "hanoi")),
    ("Thanh pho Ho Chi Minh", ("ho chi minh", "hcm", "tp hcm", "tphcm", "sai gon", "saigon")),
    ("Da Nang", ("da nang", "danang")),
    ("Hai Phong", ("hai phong", "haiphong")),
)


def _normalize_file_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _normalize_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("\u0111", "d").replace("\u0110", "d")
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


def _entry_file_name(entry: dict[str, Any]) -> str:
    return str(entry.get("file_name") or entry.get("fileName") or "unknown-file").strip() or "unknown-file"


def _entry_cv_id(entry: dict[str, Any]) -> str:
    for key in ("cv_id", "cvId", "file_id", "fileId", "id"):
        value = entry.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return _entry_file_name(entry)


def _entry_file_info(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _entry_file_name(entry),
        "size": int(entry.get("size") or entry.get("fileSize") or 0),
        "lastModified": int(entry.get("last_modified") or entry.get("lastModified") or 0),
    }


def _candidate_file_key(candidate: dict[str, Any]) -> str:
    return _normalize_file_name(str(candidate.get("fileName") or candidate.get("file_name") or ""))


def _candidate_total_score(candidate: dict[str, Any]) -> float:
    analysis = candidate.get("analysis") or {}
    for key in ("Tong diem", "Tổng điểm", "Tá»•ng Ä‘iá»ƒm", "TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m"):
        value = analysis.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"[+-]?\d+(?:\.\d+)?", value)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    continue
    return -1.0


def _infer_location_from_text(text: str) -> str:
    normalized = _normalize_ascii(text)
    if not normalized:
        return ""

    for canonical, patterns in LOCATION_PATTERNS:
        for pattern in patterns:
            if pattern.startswith(r"\b"):
                if re.search(pattern, normalized):
                    return canonical
            elif pattern in normalized:
                return canonical
    return ""


def _canonical_location(value: str) -> str:
    normalized = _normalize_ascii(value)
    if not normalized:
        return ""
    for canonical, patterns in LOCATION_PATTERNS:
        canonical_normalized = _normalize_ascii(canonical)
        if normalized == canonical_normalized:
            return canonical
        if any(pattern.startswith(r"\b") and re.search(pattern, normalized) for pattern in patterns):
            return canonical
        if any(not pattern.startswith(r"\b") and pattern in normalized for pattern in patterns):
            return canonical
    return value.strip()


def _locations_match(candidate_location: str, required_location: str) -> bool | None:
    if not candidate_location or not required_location:
        return None
    return _canonical_location(candidate_location) == _canonical_location(required_location)


def _ensure_detected_location(
    candidate: dict[str, Any],
    *,
    cv_text: str,
    required_location: str,
) -> dict[str, Any]:
    detected = str(candidate.get("detectedLocation") or "").strip()
    if not detected:
        detected = _infer_location_from_text(cv_text)
        if detected:
            candidate["detectedLocation"] = detected
            candidate["detectedLocationSource"] = "cv_text_regex"

    location_match = _locations_match(detected, required_location)
    if location_match is not None:
        candidate["locationMatch"] = location_match
        if not location_match:
            warnings = candidate.get("softFilterWarnings")
            if not isinstance(warnings, list):
                warnings = []
            warning = f"Dia diem CV ({detected}) khong khop yeu cau JD ({required_location})."
            if warning not in warnings:
                warnings.append(warning)
            candidate["softFilterWarnings"] = warnings

    metadata = candidate.get("pipelineMetadata") if isinstance(candidate.get("pipelineMetadata"), dict) else {}
    candidate["pipelineMetadata"] = {
        **metadata,
        "detectedLocation": detected,
        "locationRequirement": required_location,
        "locationMatch": location_match,
    }
    return candidate


def _ensure_final_rank(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis = candidate.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
        candidate["analysis"] = analysis

    score = _candidate_total_score(candidate)
    if score < 0:
        score = 0.0
    score = max(0.0, min(100.0, round(score, 1)))
    grade = "A" if score >= 75 else "B" if score >= 50 else "C"

    analysis.setdefault("Tong diem", score)
    analysis.setdefault(TOTAL_SCORE_KEY, score)
    analysis.setdefault("Hang", grade)
    analysis.setdefault(RANK_KEY, grade)
    candidate["finalScore"] = score
    candidate["rankGrade"] = grade
    return candidate


def _build_global_context_notes() -> str:
    return (
        "Pipeline notes:\n"
        "- Cache was checked before any Gemini scoring call.\n"
        "- Local ML classification is a routing signal only.\n"
        "- English CVs may include a Vietnamese normalized copy; preserve original technical terms.\n"
        "- Approved RAG exemplars are used only when the similarity gate passes.\n"
        "- Return strict JSON only, matching the configured scoring criteria."
    )


def _failed_candidate(entry: dict[str, Any], error: Exception) -> dict[str, Any]:
    file_name = _entry_file_name(entry)
    return {
        "fileName": file_name,
        "candidateName": "",
        "status": "FAILED",
        "error": str(error),
        "analysis": {
            "Tong diem": 0,
            "Hang": "C",
            "Chi tiet": [],
            "Diem manh CV": [],
            "Diem yeu CV": [f"Pipeline error: {error}"],
        },
    }


def _build_job_payload(jd_text: str, hard_filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "position": str(
            hard_filters.get("jobTitle")
            or hard_filters.get("position")
            or hard_filters.get("role")
            or hard_filters.get("job_position")
            or ""
        ),
        "locationRequirement": str(hard_filters.get("location") or hard_filters.get("locationRequirement") or ""),
        "seniority": str(hard_filters.get("seniority") or hard_filters.get("level") or ""),
        "jdTextSnippet": jd_text[:300],
    }


def _attach_pipeline_metadata(
    candidate: dict[str, Any],
    metadata_by_file: dict[str, dict[str, Any]],
    *,
    cache_hit: bool,
) -> dict[str, Any]:
    key = _candidate_file_key(candidate)
    metadata = copy.deepcopy(metadata_by_file.get(key) or {})
    metadata["cacheHit"] = cache_hit
    candidate["pipelineMetadata"] = {
        **(candidate.get("pipelineMetadata") or {}),
        **metadata,
    }
    return candidate


async def _read_cache_for_entry(
    *,
    user: AuthenticatedUser | None,
    entry: dict[str, Any],
    jd_text: str,
) -> tuple[str, dict[str, Any] | None, str | None]:
    cache_key = build_cv_jd_cache_key(_entry_cv_id(entry), jd_text)
    if user is None:
        return cache_key, None, None

    try:
        cached = await get_cache_entry_async(user, cache_key)
        return cache_key, cached, None
    except Exception as error:
        return cache_key, None, str(error)


async def _sync_history_safe(
    *,
    user: AuthenticatedUser | None,
    jd_text: str,
    weights: dict[str, Any],
    hard_filters: dict[str, Any],
    candidates: list[dict[str, Any]],
    pipeline: dict[str, Any],
) -> str | None:
    if user is None:
        return None
    payload = {
        "job": _build_job_payload(jd_text, hard_filters),
        "jdText": jd_text,
        "weights": weights,
        "hardFilters": hard_filters,
        "candidates": candidates,
        "pipeline": pipeline,
    }
    try:
        return await asyncio.to_thread(sync_history_entry, user, payload)
    except Exception as error:
        pipeline.setdefault("warnings", []).append(f"history_sync_failed: {error}")
        return None


async def run_smart_cv_analysis(
    jd_text: str,
    weights: dict[str, Any],
    hard_filters: dict[str, Any],
    cv_entries: list[dict[str, Any]],
    *,
    current_user: AuthenticatedUser | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    started_at = time.perf_counter()
    pipeline: dict[str, Any] = {
        "cacheEnabled": current_user is not None,
        "cacheHits": 0,
        "cacheMisses": 0,
        "geminiCalls": 0,
        "ragMode": {"fewShot": 0, "zeroShot": 0},
        "warnings": [],
        "model": {
            "classifierThreshold": settings.local_classifier_confidence_threshold,
            "ragSimilarityThreshold": settings.rag_similarity_threshold,
            "rubricVersion": settings.rubric_version,
            "geminiCvAnalysisModel": settings.gemini_cv_analysis_model,
        },
    }

    cached_candidates: list[dict[str, Any]] = []
    miss_entries: list[dict[str, Any]] = []
    metadata_by_file: dict[str, dict[str, Any]] = {}
    cache_plan_by_file: dict[str, dict[str, Any]] = {}
    raw_text_by_file: dict[str, str] = {}
    cv_text_by_file_name: dict[str, str] = {}
    required_location = str(hard_filters.get("location") or hard_filters.get("locationRequirement") or "").strip()

    for entry in cv_entries:
        file_name = _entry_file_name(entry)
        file_key = _normalize_file_name(file_name)
        raw_text_by_file[file_key] = str(entry.get("text") or "")
        cv_text_by_file_name[file_name] = raw_text_by_file[file_key]
        cache_key, cached, cache_error = await _read_cache_for_entry(
            user=current_user,
            entry=entry,
            jd_text=jd_text,
        )
        cache_plan_by_file[file_key] = {
            "cacheKey": cache_key,
            "entry": entry,
            "fileInfo": _entry_file_info(entry),
        }
        if cache_error:
            pipeline["warnings"].append(f"cache_read_failed:{file_name}:{cache_error}")

        metadata_by_file[file_key] = {
            "cacheKey": cache_key,
            "cvId": _entry_cv_id(entry),
            "sourceFileName": file_name,
        }

        if isinstance(cached, dict) and cached:
            cached_candidate = copy.deepcopy(cached)
            if "fileName" not in cached_candidate:
                cached_candidate["fileName"] = file_name
            cached_candidates.append(
                _attach_pipeline_metadata(cached_candidate, metadata_by_file, cache_hit=True)
            )
            pipeline["cacheHits"] += 1
            continue

        miss_entries.append(entry)
        pipeline["cacheMisses"] += 1

    generated_candidates: list[dict[str, Any]] = []
    if miss_entries:
        entry_contexts: dict[str, dict[str, Any]] = {}
        cv_text_map: dict[str, str] = {}

        for entry in miss_entries:
            file_name = _entry_file_name(entry)
            file_key = _normalize_file_name(file_name)
            raw_text = str(entry.get("text") or "")

            try:
                normalized_payload = await normalize_cv_text_for_analysis_async(raw_text)
            except Exception as error:
                pipeline["warnings"].append(f"language_normalize_failed:{file_name}:{error}")
                normalized_payload = {
                    "original_text": raw_text,
                    "analysis_text": raw_text,
                    "translated_text": "",
                    "normalized_vi_text": raw_text,
                    "language": "unknown",
                    "language_confidence": 0,
                    "language_reason": "fallback",
                    "was_translated": False,
                }

            try:
                grounding_payload = await build_approved_grounding_context(
                    cv_text=raw_text,
                    analysis_text=str(normalized_payload.get("analysis_text") or raw_text),
                    file_name=file_name,
                    hard_filters=hard_filters,
                    jd_text=jd_text,
                    rubric_version=settings.rubric_version,
                )
            except Exception as error:
                pipeline["warnings"].append(f"rag_failed:{file_name}:{error}")
                grounding_payload = {
                    "classifier": None,
                    "collection_keys": [],
                    "industry_hints": [],
                    "entry_note": "RAG unavailable; continue zero-shot.",
                    "few_shot_examples": "",
                    "exemplars": [],
                    "rag_status": "zero_shot",
                    "similarity_gate": settings.rag_similarity_threshold,
                }

            analysis_text_bundle = build_analysis_text_bundle(normalized_payload)
            entry_contexts[file_name] = {
                "analysis_text": analysis_text_bundle,
                "entry_note": grounding_payload.get("entry_note") or "",
                "few_shot_examples": grounding_payload.get("few_shot_examples") or "",
            }
            cv_text_map[file_name] = analysis_text_bundle

            rag_status = str(grounding_payload.get("rag_status") or "zero_shot")
            if rag_status == "few_shot":
                pipeline["ragMode"]["fewShot"] += 1
            else:
                pipeline["ragMode"]["zeroShot"] += 1

            metadata_by_file[file_key] = {
                **metadata_by_file.get(file_key, {}),
                "language": normalized_payload.get("language"),
                "languageConfidence": normalized_payload.get("language_confidence"),
                "languageReason": normalized_payload.get("language_reason"),
                "wasTranslated": normalized_payload.get("was_translated"),
                "normalizedTextKey": "normalized_vi_text",
                "classifier": grounding_payload.get("classifier") or {},
                "industryHints": grounding_payload.get("industry_hints") or [],
                "collectionKeys": grounding_payload.get("collection_keys") or [],
                "ragStatus": rag_status,
                "groundingExampleCount": len(grounding_payload.get("exemplars") or []),
                "ragSimilarityGate": grounding_payload.get("similarity_gate"),
                "ragEmbeddingModel": grounding_payload.get("embedding_model"),
                "detectedLocation": _infer_location_from_text(raw_text),
            }

        try:
            pipeline["geminiCalls"] += 1
            base_candidates = await analyze_cv_entries_async(
                jd_text,
                weights,
                hard_filters,
                [
                    {
                        "file_name": _entry_file_name(entry),
                        "text": str(entry.get("text") or ""),
                    }
                    for entry in miss_entries
                ],
                entry_contexts=entry_contexts,
                context_notes=_build_global_context_notes(),
            )
        except Exception as error:
            pipeline["warnings"].append(f"gemini_analysis_failed:{error}")
            base_candidates = [_failed_candidate(entry, error) for entry in miss_entries]

        try:
            generated_candidates = await asyncio.to_thread(
                enrich_candidates,
                base_candidates,
                cv_text_map,
                jd_text,
                hard_filters,
                current_user.uid if current_user else None,
            )
        except Exception as error:
            pipeline["warnings"].append(f"candidate_enrichment_failed:{error}")
            generated_candidates = base_candidates

        for candidate in generated_candidates:
            file_key = _candidate_file_key(candidate)
            _attach_pipeline_metadata(candidate, metadata_by_file, cache_hit=False)
            _ensure_detected_location(
                candidate,
                cv_text=raw_text_by_file.get(file_key, ""),
                required_location=required_location,
            )
            _ensure_final_rank(candidate)

        generated_candidates = attach_advanced_score_breakdowns(generated_candidates, cv_text_by_file_name, jd_text)

        if current_user:
            jd_hash = stable_hash(jd_text)
            weights_hash = stable_hash(weights)
            filters_hash = stable_hash(hard_filters)
            for candidate in generated_candidates:
                if str(candidate.get("status") or "SUCCESS").upper() == "FAILED":
                    continue
                file_key = _candidate_file_key(candidate)
                plan = cache_plan_by_file.get(file_key)
                if not plan:
                    continue
                try:
                    await sync_cache_entry_async(
                        current_user,
                        str(plan["cacheKey"]),
                        candidate,
                        jd_hash,
                        weights_hash,
                        filters_hash,
                        plan["fileInfo"],
                    )
                except Exception as error:
                    pipeline["warnings"].append(
                        f"cache_write_failed:{candidate.get('fileName') or file_key}:{error}"
                    )

    candidates = [*cached_candidates, *generated_candidates]
    candidates = attach_advanced_score_breakdowns(candidates, cv_text_by_file_name, jd_text)
    for candidate in candidates:
        file_key = _candidate_file_key(candidate)
        _ensure_detected_location(
            candidate,
            cv_text=raw_text_by_file.get(file_key, ""),
            required_location=required_location,
        )
        _ensure_final_rank(candidate)
    candidates.sort(key=lambda candidate: (_candidate_total_score(candidate), str(candidate.get("fileName") or "")), reverse=True)

    history_id = await _sync_history_safe(
        user=current_user if miss_entries else None,
        jd_text=jd_text,
        weights=weights,
        hard_filters=hard_filters,
        candidates=candidates,
        pipeline=pipeline,
    )
    if history_id:
        pipeline["historyId"] = history_id

    pipeline["durationMs"] = round((time.perf_counter() - started_at) * 1000)
    return {
        "candidates": candidates,
        "pipeline": pipeline,
    }
