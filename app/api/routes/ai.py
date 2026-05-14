from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.schemas.analysis import (
    CandidateEnrichmentRequest,
    CandidateEnrichmentResponse,
    CoreCvAnalysisRequest,
    CoreCvAnalysisResponse,
    CvProfileRefineRequest,
    CvProfileRefineResponse,
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
from app.services.candidate_enrichment_service import enrich_candidates
from app.services.candidate_refinement_service import refine_cv_profile
from app.services.cv_analysis_service import analyze_cv_entries
from app.services.gemini_service import embed_text, generate_content
from app.services.workflow_service import (
    extract_hard_filters,
    extract_job_position,
    generate_interview_questions,
    structure_jd,
)


router = APIRouter(prefix="/api", tags=["ai"])


@router.post("/gemini-chat", response_model=GeminiGenerateResponse)
def gemini_chat(payload: GeminiGenerateRequest) -> GeminiGenerateResponse:
    text = generate_content(payload.model, payload.contents, payload.config)
    return GeminiGenerateResponse(text=text)


@router.post("/gemini-embed", response_model=GeminiEmbedResponse)
def gemini_embed(payload: GeminiEmbedRequest) -> GeminiEmbedResponse:
    vector = embed_text(payload.text, payload.model)
    return GeminiEmbedResponse(vector=vector)


@router.post("/jd/structure", response_model=JdStructureResponse)
def jd_structure(payload: JdStructureRequest) -> JdStructureResponse:
    return JdStructureResponse(structured_text=structure_jd(payload.raw_text))


@router.post("/jd/position", response_model=JdPositionResponse)
def jd_position(payload: JdPositionRequest) -> JdPositionResponse:
    return JdPositionResponse(job_position=extract_job_position(payload.jd_text))


@router.post("/jd/hard-filters", response_model=JdHardFiltersResponse)
def jd_hard_filters(payload: JdHardFiltersRequest) -> JdHardFiltersResponse:
    return JdHardFiltersResponse(filters=extract_hard_filters(payload.jd_text))


@router.post("/interview/questions", response_model=InterviewQuestionsResponse)
def interview_questions(payload: InterviewQuestionsRequest) -> InterviewQuestionsResponse:
    question_sets = generate_interview_questions(
        payload.analysis_data,
        payload.analysis_stats,
        payload.question_type,
        payload.candidate_data,
    )
    return InterviewQuestionsResponse(question_sets=question_sets)


@router.post("/cv/analyze-core", response_model=CoreCvAnalysisResponse)
def cv_analyze_core(payload: CoreCvAnalysisRequest) -> CoreCvAnalysisResponse:
    candidates = analyze_cv_entries(
        payload.jd_text,
        payload.weights,
        payload.hard_filters,
        [entry.model_dump() for entry in payload.cv_entries],
    )
    return CoreCvAnalysisResponse(candidates=candidates)


@router.post("/cv/refine-profile", response_model=CvProfileRefineResponse)
def cv_refine_profile(payload: CvProfileRefineRequest) -> CvProfileRefineResponse:
    return CvProfileRefineResponse(
        **refine_cv_profile(payload.cv_text, payload.current_education, payload.current_name)
    )


@router.post("/cv/enrich", response_model=CandidateEnrichmentResponse)
def cv_enrich(
    payload: CandidateEnrichmentRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> CandidateEnrichmentResponse:
    return CandidateEnrichmentResponse(
        candidates=enrich_candidates(
            payload.candidates,
            payload.cv_text_map,
            payload.jd_text,
            payload.hard_filters,
            owner_uid=current_user.uid,
        )
    )
