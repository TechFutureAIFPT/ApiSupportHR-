from __future__ import annotations

import asyncio
import copy
import json
import re
import time
import unicodedata
from typing import Any

from app.core.ai_contract import PIPELINE_VERSION, rank_from_score
from app.core.config import get_settings
from app.schemas.account import AuthenticatedUser
from app.services.account.cache_service import (
    build_cv_jd_cache_key,
    get_cache_entry_async,
    maintain_user_cache_async,
    stable_hash,
    sync_cache_entry_async,
)
from app.services.account.history_service import sync_history_entry
from app.services.analysis_routing_service import build_routing_metadata_async, default_routing_metadata
from app.services.analysis_grounding_service import build_approved_grounding_context
from app.services.candidate_enrichment_service import enrich_candidates
from app.services.cv_analysis_service import (
    analyze_cv_entries_async,
    attach_advanced_score_breakdowns,
    build_rule_based_fallback_candidates,
    normalize_candidates_against_weights,
)
from app.services.language_service import build_analysis_text_bundle, normalize_cv_text_for_analysis_async
from app.services.gemini_service import embed_text
from app.services.local_classifier_service import classify_cv_text, get_classifier_status
from app.services.rubric_service import resolve_scoring_rubric
from app.utils.text_normalization import normalize_display_text


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
    normalized = unicodedata.normalize("NFD", normalize_display_text(value or ""))
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
    aliases = {_normalize_ascii(key) for key in ("Tong diem", "Tổng điểm")}
    for key, value in analysis.items():
        if _normalize_ascii(str(key)) not in aliases:
            continue
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
    candidate_raw = _normalize_ascii(candidate_location)
    required_raw = _normalize_ascii(required_location)
    if candidate_raw and required_raw and (candidate_raw == required_raw or required_raw in candidate_raw or candidate_raw in required_raw):
        return True
    candidate = _normalize_ascii(_canonical_location(candidate_location))
    required = _normalize_ascii(_canonical_location(required_location))
    if not candidate or not required:
        return None
    if candidate == required:
        return True
    if required in candidate or candidate in required:
        return True
    return False


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
            warning = f"Cảnh báo địa điểm: CV ghi {detected}, khác địa điểm làm việc yêu cầu ({required_location})."
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
    grade = rank_from_score(score)

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
        "- Local ML classification is a routing hint and a post-analysis industry-fit signal; never use it as sole evidence.\n"
        "- English CVs may include a Vietnamese normalized copy; preserve original technical terms.\n"
        "- Approved RAG exemplars are used only when the similarity gate passes.\n"
        "- Return strict JSON only, matching the configured scoring criteria."
    )


def _format_routing_metadata_note(metadata: dict[str, Any]) -> str:
    routing = metadata.get("routing_analysis") if isinstance(metadata.get("routing_analysis"), dict) else {}
    match = metadata.get("mathematical_match") if isinstance(metadata.get("mathematical_match"), dict) else {}
    vocab_sim = float(match.get("vocab_similarity_score") or 0.0)
    confidence = float(routing.get("confidence_score") or 0.0)
    # PKL score pre-computed server-side (max 20): vocab_sim 60% + confidence 40%
    pkl_computed_score = round(min(20.0, vocab_sim * 12.0 + confidence * 8.0), 2)
    found = ", ".join(str(item) for item in list(match.get("core_keywords_found") or [])[:8])
    missing = ", ".join(str(item) for item in list(match.get("missing_critical_keywords") or [])[:8])
    metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    return (
        "JSON metadata toán học từ hệ thống .pkl:\n"
        f"{metadata_json}\n"
        "Diễn giải nhanh cho bước phân tích:\n"
        f"- Ngành dự đoán: {routing.get('predicted_industry') or 'unknown'} "
        f"(độ tin cậy {confidence}).\n"
        f"- Độ tương đồng từ vựng TF-IDF giữa JD và CV: {vocab_sim}.\n"
        f"- Từ khóa lõi đã thấy: {found or 'không có'}.\n"
        f"- Từ khóa quan trọng còn thiếu: {missing or 'không có'}.\n"
        f"- ⚡ PKL COMPUTED SCORE (server đã tính): {pkl_computed_score}/20 "
        f"(công thức: {vocab_sim}×12 + {confidence}×8 = {pkl_computed_score}).\n"
        "  → Dùng con số này TRỰC TIẾP cho trường diemThuongTuTapMauHeThongPkl. "
        "Không tự tính lại. Không tăng/giảm tùy ý.\n"
        "- Chỉ dùng metadata này làm mốc định lượng hỗ trợ; các điểm khác vẫn phải "
        "dựa trên bằng chứng trong JD và CV."
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
    merged_metadata = {
        **(candidate.get("pipelineMetadata") or {}),
        **metadata,
    }
    # Candidates from the rule-based fallback path already set analysisMethod
    # explicitly; anything else came from a real Gemini response.
    merged_metadata.setdefault("analysisMethod", "llm")
    candidate["pipelineMetadata"] = merged_metadata
    return candidate


async def _read_cache_for_entry(
    *,
    user: AuthenticatedUser | None,
    entry: dict[str, Any],
    jd_text: str,
    weights: dict[str, Any],
    hard_filters: dict[str, Any],
    rubric_version: str,
    classifier_version: str,
) -> tuple[str, dict[str, Any] | None, str | None]:
    cache_key = build_cv_jd_cache_key(
        _entry_cv_id(entry),
        jd_text,
        cv_text=str(entry.get("text") or ""),
        weights=weights,
        hard_filters=hard_filters,
        rubric_version=rubric_version,
        classifier_version=classifier_version,
    )
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
    cv_source_texts: list[dict[str, str]] | None = None,
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
        "sourceTexts": {
            "jdText": jd_text,
            "cvTexts": cv_source_texts or [],
        },
    }
    try:
        return await asyncio.to_thread(sync_history_entry, user, payload)
    except Exception as error:
        pipeline.setdefault("warnings", []).append(f"history_sync_failed: {error}")
        return None


async def _prepare_entry_context(
    *,
    entry: dict[str, Any],
    jd_text: str,
    hard_filters: dict[str, Any],
    rubric_version: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    settings = get_settings()
    file_name = _entry_file_name(entry)
    raw_text = str(entry.get("text") or "")
    warnings: list[str] = []
    started_at = time.perf_counter()

    async with semaphore:
        try:
            normalized_payload = await normalize_cv_text_for_analysis_async(raw_text)
        except Exception as error:
            warnings.append(f"language_normalize_failed:{file_name}:{error}")
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

        normalized_text = str(normalized_payload.get("analysis_text") or raw_text)

        async def _classify() -> tuple[dict[str, Any] | None, str]:
            try:
                return await asyncio.to_thread(classify_cv_text, normalized_text, 5), ""
            except Exception as error:
                return None, str(error)

        async def _embed() -> tuple[list[float] | None, str]:
            try:
                return await asyncio.to_thread(
                    embed_text,
                    normalized_text[:6000],
                    settings.gemini_embedding_model,
                    task="semantic_similarity",
                ), ""
            except Exception as error:
                return None, str(error)

        (classifier_result, classifier_error), (query_vector, embedding_error) = await asyncio.gather(
            _classify(),
            _embed(),
        )
        if classifier_error:
            warnings.append(f"classifier_failed:{file_name}:{classifier_error}")
        if embedding_error:
            warnings.append(f"embedding_failed:{file_name}:{embedding_error}")

        try:
            routing_metadata = await build_routing_metadata_async(
                jd_text,
                normalized_text,
                classifier_result=classifier_result,
                translate=False,
            )
        except Exception as error:
            warnings.append(f"routing_metadata_failed:{file_name}:{error}")
            routing_metadata = default_routing_metadata()

        try:
            grounding_payload = await build_approved_grounding_context(
                cv_text=raw_text,
                analysis_text=normalized_text,
                file_name=file_name,
                hard_filters=hard_filters,
                jd_text=jd_text,
                rubric_version=rubric_version,
                classifier_result=classifier_result,
                query_vector=query_vector,
            )
        except Exception as error:
            warnings.append(f"rag_failed:{file_name}:{error}")
            grounding_payload = {
                "classifier": classifier_result,
                "collection_keys": [],
                "industry_hints": [],
                "entry_note": "RAG unavailable; continue zero-shot.",
                "few_shot_examples": "",
                "exemplars": [],
                "rag_status": "zero_shot",
                "similarity_gate": settings.rag_similarity_threshold,
                "embedding_model": settings.gemini_embedding_model,
                "embedding_dimension": settings.gemini_embedding_dimension,
                "vector_index_version": settings.vector_index_version,
                "query_vector": query_vector,
            }

    return {
        "file_name": file_name,
        "normalized_payload": normalized_payload,
        "routing_metadata": routing_metadata,
        "grounding_payload": grounding_payload,
        "analysis_text_bundle": build_analysis_text_bundle(normalized_payload),
        "query_vector": query_vector,
        "warnings": warnings,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }


async def run_smart_cv_analysis(
    jd_text: str,
    weights: dict[str, Any],
    hard_filters: dict[str, Any],
    cv_entries: list[dict[str, Any]],
    *,
    current_user: AuthenticatedUser | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    rubric = resolve_scoring_rubric(
        jd_text=jd_text,
        hard_filters=hard_filters,
        requested_weights=weights,
        rubric_version=settings.rubric_version,
    )
    weights = rubric["weights"]
    classifier_status = get_classifier_status()
    classifier_version = str(classifier_status.get("model_version") or "unknown")
    started_at = time.perf_counter()
    pipeline: dict[str, Any] = {
        "cacheEnabled": current_user is not None,
        "cacheHits": 0,
        "cacheMisses": 0,
        "geminiCalls": 0,
        "ragMode": {"fewShot": 0, "zeroShot": 0},
        "warnings": [],
        "model": {
            "pipelineVersion": PIPELINE_VERSION,
            "classifierVersion": classifier_version,
            "classifierThreshold": settings.local_classifier_confidence_threshold,
            "ragSimilarityThreshold": settings.rag_similarity_threshold,
            "rubricVersion": settings.rubric_version,
            "geminiCvAnalysisModel": settings.gemini_cv_analysis_model,
            "embeddingModel": settings.gemini_embedding_model,
            "embeddingDimension": settings.gemini_embedding_dimension,
            "vectorIndexVersion": settings.vector_index_version,
        },
        "rubric": {
            "version": rubric["rubricVersion"],
            "roleKey": rubric["roleKey"],
            "roleLabel": rubric["roleLabel"],
            "source": rubric["source"],
            "overrideDiff": rubric["overrideDiff"],
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
            weights=weights,
            hard_filters=hard_filters,
            rubric_version=settings.rubric_version,
            classifier_version=classifier_version,
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
        cv_vectors_by_file: dict[str, list[float]] = {}
        semaphore = asyncio.Semaphore(settings.ai_preprocess_concurrency)
        prepared_entries = await asyncio.gather(*[
            _prepare_entry_context(
                entry=entry,
                jd_text=jd_text,
                hard_filters=hard_filters,
                rubric_version=settings.rubric_version,
                semaphore=semaphore,
            )
            for entry in miss_entries
        ])
        pipeline["classifierCalls"] = len(miss_entries)
        pipeline["embeddingCalls"] = len(miss_entries)
        pipeline["preprocessConcurrency"] = settings.ai_preprocess_concurrency

        for prepared in prepared_entries:
            file_name = str(prepared["file_name"])
            file_key = _normalize_file_name(file_name)
            normalized_payload = prepared["normalized_payload"]
            routing_metadata = prepared["routing_metadata"]
            grounding_payload = prepared["grounding_payload"]
            analysis_text_bundle = str(prepared["analysis_text_bundle"])
            pipeline["warnings"].extend(prepared["warnings"])
            entry_note_parts = [
                _format_routing_metadata_note(routing_metadata),
                str(grounding_payload.get("entry_note") or ""),
            ]
            entry_contexts[file_name] = {
                "analysis_text": analysis_text_bundle,
                "entry_note": "\n\n".join(part for part in entry_note_parts if part.strip()),
                "few_shot_examples": grounding_payload.get("few_shot_examples") or "",
            }
            cv_text_map[file_name] = analysis_text_bundle
            if isinstance(prepared.get("query_vector"), list):
                cv_vectors_by_file[file_name] = prepared["query_vector"]

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
                "routingMetadata": routing_metadata,
                "industryHints": grounding_payload.get("industry_hints") or [],
                "collectionKeys": grounding_payload.get("collection_keys") or [],
                "ragStatus": rag_status,
                "groundingExampleCount": len(grounding_payload.get("exemplars") or []),
                "ragSimilarityGate": grounding_payload.get("similarity_gate"),
                "ragEmbeddingModel": grounding_payload.get("embedding_model"),
                "ragEmbeddingDimension": grounding_payload.get("embedding_dimension"),
                "vectorIndexVersion": grounding_payload.get("vector_index_version"),
                "preprocessDurationMs": prepared["duration_ms"],
                "detectedLocation": _infer_location_from_text(raw_text_by_file.get(file_key, "")),
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
            pipeline["aiFallback"] = True
            base_candidates = build_rule_based_fallback_candidates(
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
                failure_reason=str(error),
            )

        for candidate in base_candidates:
            if isinstance(candidate, dict):
                _attach_pipeline_metadata(candidate, metadata_by_file, cache_hit=False)

        try:
            generated_candidates = await asyncio.to_thread(
                enrich_candidates,
                base_candidates,
                cv_text_map,
                jd_text,
                hard_filters,
                current_user.uid if current_user else None,
                precomputed_cv_vectors=cv_vectors_by_file,
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
        generated_candidates = normalize_candidates_against_weights(generated_candidates, weights)

        if current_user:
            jd_hash = stable_hash(jd_text)
            weights_hash = stable_hash(weights)
            filters_hash = stable_hash(hard_filters)
            cache_write_tasks: list[asyncio.Task[None]] = []
            for candidate in generated_candidates:
                if str(candidate.get("status") or "SUCCESS").upper() == "FAILED":
                    continue
                file_key = _candidate_file_key(candidate)
                plan = cache_plan_by_file.get(file_key)
                if not plan:
                    continue
                cache_write_tasks.append(asyncio.create_task(sync_cache_entry_async(
                        current_user,
                        str(plan["cacheKey"]),
                        candidate,
                        jd_hash,
                        weights_hash,
                        filters_hash,
                        plan["fileInfo"],
                        rubric_version=settings.rubric_version,
                        pipeline_version=PIPELINE_VERSION,
                        maintain_views=False,
                    )))
            if cache_write_tasks:
                cache_write_results = await asyncio.gather(*cache_write_tasks, return_exceptions=True)
                for result in cache_write_results:
                    if isinstance(result, Exception):
                        pipeline["warnings"].append(f"cache_write_failed:{result}")
                try:
                    await maintain_user_cache_async(current_user)
                except Exception as error:
                    pipeline["warnings"].append(f"cache_maintenance_failed:{error}")

    candidates = [*cached_candidates, *generated_candidates]
    candidates = attach_advanced_score_breakdowns(candidates, cv_text_by_file_name, jd_text)
    candidates = normalize_candidates_against_weights(candidates, weights)
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
        user=current_user,
        jd_text=jd_text,
        weights=weights,
        hard_filters=hard_filters,
        candidates=candidates,
        pipeline=pipeline,
        cv_source_texts=[
            {"fileName": file_name, "text": text}
            for file_name, text in cv_text_by_file_name.items()
        ],
    )
    if history_id:
        pipeline["historyId"] = history_id

    pipeline["durationMs"] = round((time.perf_counter() - started_at) * 1000)
    return {
        "candidates": candidates,
        "pipeline": pipeline,
    }
