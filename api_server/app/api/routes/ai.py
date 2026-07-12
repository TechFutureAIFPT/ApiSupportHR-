from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_current_user, get_optional_current_user
from app.schemas.analysis import (
    AnalysisJobAcceptedResponse,
    AnalysisJobStatusResponse,
    CandidateChatRequest,
    CandidateChatResponse,
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
    CoreCvAnalysisRequest,
    CoreCvAnalysisResponse,
    CvIndustryClassificationRequest,
    CvIndustryClassificationResponse,
    CvIndustryClassifierStatusResponse,
    CvProfileRefineRequest,
    CvProfileRefineResponse,
    QuickCvScoreRequest,
    QuickCvScoreResponse,
)
from app.schemas.gemini import (
    GeminiEmbedRequest,
    GeminiEmbedResponse,
    GeminiGenerateRequest,
    GeminiGenerateResponse,
)
from app.schemas.workflows import (
    InterviewQuestionsRequest,
    InterviewQuestionsResponse,
    JdHardFiltersRequest,
    JdHardFiltersResponse,
    JdPositionRequest,
    JdPositionResponse,
    JdStructureRequest,
    JdStructureResponse,
)
from app.schemas.account import AuthenticatedUser
from app.services.account.persistence_service import save_ai_request, save_quick_cv_score
from app.services.analysis_job_service import get_analysis_job, start_analysis_job
from app.services.candidate_chat_service import reply_to_candidate_chat
from app.services.candidate_enrichment_service import enrich_candidates
from app.services.candidate_refinement_service import refine_cv_profile
from app.services.cv_pipeline_service import run_smart_cv_analysis
from app.services.file_extraction_service import extract_text_from_upload
from app.services.gemini_service import embed_text, generate_content
from app.services.local_classifier_service import classify_cv_text, get_classifier_status
from app.services.quick_cv_score_service import MAX_CV_COUNT, score_quick_cvs
from app.services.workflow_service import (
    extract_hard_filters,
    extract_job_position,
    generate_interview_questions,
    structure_jd,
)
from app.core.config import get_settings


router = APIRouter(prefix="/api", tags=["ai"])


def _parse_quick_cv_texts(raw_value: str | None) -> list[dict[str, str]]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="cv_texts_json must be valid JSON") from error

    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="cv_texts_json must be an array")

    entries: list[dict[str, str]] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        file_name = str(item.get("file_name") or item.get("fileName") or f"cv-{index}.txt")
        entries.append({"file_name": file_name, "text": text})
    return entries


@router.post("/gemini-chat", response_model=GeminiGenerateResponse)
def gemini_chat(
    payload: GeminiGenerateRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> GeminiGenerateResponse:
    text = generate_content(payload.model, payload.contents, payload.config)
    saved_record_id = save_ai_request(
        current_user,
        operation="gemini_chat",
        request_payload=payload.model_dump(),
        response_payload={"text": text},
        metadata={"model": payload.model},
    )
    return GeminiGenerateResponse(text=text, saved_record_id=saved_record_id)


@router.post("/gemini-embed", response_model=GeminiEmbedResponse)
def gemini_embed(
    payload: GeminiEmbedRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> GeminiEmbedResponse:
    vector = embed_text(payload.text, payload.model)
    saved_record_id = save_ai_request(
        current_user,
        operation="gemini_embed",
        request_payload=payload.model_dump(),
        response_payload={"vector": vector},
        metadata={"vectorLength": len(vector), "model": payload.model or ""},
    )
    return GeminiEmbedResponse(vector=vector, saved_record_id=saved_record_id)


@router.post("/jd/structure", response_model=JdStructureResponse)
def jd_structure(
    payload: JdStructureRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> JdStructureResponse:
    structured_text = structure_jd(payload.raw_text)
    saved_record_id = save_ai_request(
        current_user,
        operation="jd_structure",
        request_payload=payload.model_dump(),
        response_payload={"structured_text": structured_text},
    )
    return JdStructureResponse(structured_text=structured_text, saved_record_id=saved_record_id)


@router.post("/jd/position", response_model=JdPositionResponse)
def jd_position(
    payload: JdPositionRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> JdPositionResponse:
    job_position = extract_job_position(payload.jd_text)
    saved_record_id = save_ai_request(
        current_user,
        operation="jd_position",
        request_payload=payload.model_dump(),
        response_payload={"job_position": job_position},
    )
    return JdPositionResponse(job_position=job_position, saved_record_id=saved_record_id)


@router.post("/jd/hard-filters", response_model=JdHardFiltersResponse)
def jd_hard_filters(
    payload: JdHardFiltersRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> JdHardFiltersResponse:
    filters = extract_hard_filters(payload.jd_text)
    saved_record_id = save_ai_request(
        current_user,
        operation="jd_hard_filters",
        request_payload=payload.model_dump(),
        response_payload={"filters": filters},
    )
    return JdHardFiltersResponse(filters=filters, saved_record_id=saved_record_id)


@router.post("/interview/questions", response_model=InterviewQuestionsResponse)
def interview_questions(
    payload: InterviewQuestionsRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> InterviewQuestionsResponse:
    question_sets = generate_interview_questions(
        payload.analysis_data,
        payload.analysis_stats,
        payload.question_type,
        payload.candidate_data,
    )
    saved_record_id = save_ai_request(
        current_user,
        operation="interview_questions",
        request_payload=payload.model_dump(),
        response_payload={"question_sets": question_sets},
        metadata={"questionType": payload.question_type},
    )
    return InterviewQuestionsResponse(question_sets=question_sets, saved_record_id=saved_record_id)


@router.post("/cv/analyze-core", response_model=CoreCvAnalysisResponse)
async def cv_analyze_core(
    payload: CoreCvAnalysisRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> CoreCvAnalysisResponse:
    result = await run_smart_cv_analysis(
        payload.jd_text,
        payload.weights,
        payload.hard_filters,
        [entry.model_dump() for entry in payload.cv_entries],
        current_user=current_user,
    )
    return CoreCvAnalysisResponse(
        candidates=result.get("candidates") or [],
        pipeline=result.get("pipeline") or {},
        saved_history_id=(result.get("pipeline") or {}).get("historyId"),
    )


@router.post("/cv/quick-score-text", response_model=QuickCvScoreResponse)
def cv_quick_score_text(
    payload: QuickCvScoreRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> QuickCvScoreResponse:
    settings = get_settings()
    try:
        items = score_quick_cvs(
            [entry.model_dump() for entry in payload.cv_entries],
            jd_text=payload.jd_text,
            include_extracted_text=payload.include_extracted_text,
            api_keys=settings.quick_cv_gemini_api_keys,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response_payload = {
        "items": [item.model_dump() if hasattr(item, "model_dump") else item for item in items],
        "model": settings.quick_cv_gemini_model,
    }
    saved_score_id = save_quick_cv_score(
        current_user,
        request_payload=payload.model_dump(),
        response_payload=response_payload,
    )
    return QuickCvScoreResponse(items=items, model=settings.quick_cv_gemini_model, saved_score_id=saved_score_id)


@router.post("/cv/quick-score", response_model=QuickCvScoreResponse)
async def cv_quick_score(
    files: list[UploadFile] | None = File(default=None),
    cv_texts_json: str | None = Form(default=None),
    jd_text: str | None = Form(default=None),
    include_extracted_text: bool = Form(default=False),
    force_ocr: bool = Form(default=False),
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> QuickCvScoreResponse:
    settings = get_settings()
    entries = _parse_quick_cv_texts(cv_texts_json)
    uploaded_files = files or []
    source_files: list[dict[str, Any]] = []

    if len(entries) + len(uploaded_files) < 1:
        raise HTTPException(status_code=400, detail="Upload at least one CV file or provide cv_texts_json")
    if len(entries) + len(uploaded_files) > MAX_CV_COUNT:
        raise HTTPException(status_code=400, detail=f"Quick CV scoring supports at most {MAX_CV_COUNT} CVs")

    for file in uploaded_files:
        try:
            file_bytes = await file.read()
            source_files.append(
                {
                    "fileName": file.filename or "uploaded-cv",
                    "mimeType": file.content_type or "",
                    "fileSize": len(file_bytes),
                    "forceOcr": force_ocr,
                }
            )
            text = await asyncio.to_thread(
                extract_text_from_upload,
                file_bytes=file_bytes,
                filename=file.filename or "uploaded-cv",
                content_type=file.content_type or "",
                force_ocr=force_ocr,
                document_type="cv",
                api_keys=settings.quick_cv_gemini_api_keys,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        entries.append({"file_name": file.filename or "uploaded-cv", "text": text})

    try:
        items = score_quick_cvs(
            entries,
            jd_text=jd_text,
            include_extracted_text=include_extracted_text,
            api_keys=settings.quick_cv_gemini_api_keys,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    response_payload = {
        "items": [item.model_dump() if hasattr(item, "model_dump") else item for item in items],
        "model": settings.quick_cv_gemini_model,
    }
    saved_score_id = await asyncio.to_thread(
        save_quick_cv_score,
        current_user,
        request_payload={
            "cvTextsJson": cv_texts_json,
            "jdText": jd_text,
            "includeExtractedText": include_extracted_text,
            "forceOcr": force_ocr,
            "sourceFiles": source_files,
        },
        response_payload=response_payload,
    )
    return QuickCvScoreResponse(items=items, model=settings.quick_cv_gemini_model, saved_score_id=saved_score_id)


@router.post(
    "/cv/analyze-core-async",
    response_model=AnalysisJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cv_analyze_core_async(
    payload: CoreCvAnalysisRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> AnalysisJobAcceptedResponse:
    job = start_analysis_job(payload.model_dump(), current_user=current_user)
    return AnalysisJobAcceptedResponse(
        job_id=str(job["job_id"]),
        status="processing",
        status_url=f"/api/analysis/status/{job['job_id']}",
    )


@router.post(
    "/analysis/jobs",
    response_model=AnalysisJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis_job(
    payload: CoreCvAnalysisRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> AnalysisJobAcceptedResponse:
    job = start_analysis_job(payload.model_dump(), current_user=current_user)
    return AnalysisJobAcceptedResponse(
        job_id=str(job["job_id"]),
        status="processing",
        status_url=f"/api/analysis/status/{job['job_id']}",
    )


@router.get("/analysis/status/{job_id}", response_model=AnalysisJobStatusResponse)
async def analysis_job_status(
    job_id: str,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> AnalysisJobStatusResponse:
    job = get_analysis_job(job_id, current_user=current_user)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")
    return AnalysisJobStatusResponse(**job)


@router.post("/cv/refine-profile", response_model=CvProfileRefineResponse)
def cv_refine_profile(
    payload: CvProfileRefineRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> CvProfileRefineResponse:
    result = refine_cv_profile(payload.cv_text, payload.current_education, payload.current_name)
    saved_record_id = save_ai_request(
        current_user,
        operation="cv_refine_profile",
        request_payload=payload.model_dump(),
        response_payload=result,
    )
    return CvProfileRefineResponse(**result, saved_record_id=saved_record_id)


@router.post("/cv/candidate-chat", response_model=CandidateChatResponse)
def cv_candidate_chat(
    payload: CandidateChatRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> CandidateChatResponse:
    result = reply_to_candidate_chat(
        payload.candidate_snapshot,
        payload.message,
        job_position=payload.job_position,
        recruiter_context=payload.recruiter_context,
    )
    saved_record_id = save_ai_request(
        current_user,
        operation="candidate_chat",
        request_payload=payload.model_dump(),
        response_payload=result,
    )
    return CandidateChatResponse(**result, saved_record_id=saved_record_id)


@router.get("/cv/classifier-status", response_model=CvIndustryClassifierStatusResponse)
def cv_classifier_status() -> CvIndustryClassifierStatusResponse:
    return CvIndustryClassifierStatusResponse(**get_classifier_status())


@router.post("/cv/classify-industry", response_model=CvIndustryClassificationResponse)
def cv_classify_industry(
    payload: CvIndustryClassificationRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> CvIndustryClassificationResponse:
    try:
        result = classify_cv_text(payload.cv_text, top_k=payload.top_k)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error)) from error
    saved_record_id = save_ai_request(
        current_user,
        operation="cv_classify_industry",
        request_payload=payload.model_dump(),
        response_payload=result,
    )
    return CvIndustryClassificationResponse(**result, saved_record_id=saved_record_id)


@router.post("/cv/enrich", response_model=CandidateEnrichmentResponse)
def cv_enrich(
    payload: CandidateEnrichmentRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> CandidateEnrichmentResponse:
    candidates = enrich_candidates(
        payload.candidates,
        payload.cv_text_map,
        payload.jd_text,
        payload.hard_filters,
        owner_uid=current_user.uid,
    )
    saved_record_id = save_ai_request(
        current_user,
        operation="cv_enrich",
        request_payload=payload.model_dump(),
        response_payload={"candidates": candidates},
    )
    return CandidateEnrichmentResponse(candidates=candidates, saved_record_id=saved_record_id)
