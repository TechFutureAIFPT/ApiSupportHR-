from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_optional_current_user
from app.schemas.account import AuthenticatedUser
from app.schemas.salary import SalaryAnalysisRequest, SalaryAnalysisResponse
from app.services.account.persistence_service import save_ai_request
from app.services.salary_analysis_service import analyze_salary


router = APIRouter(prefix="/api/salary", tags=["salary"])


@router.post("/analyze", response_model=SalaryAnalysisResponse)
def salary_analyze(
    payload: SalaryAnalysisRequest,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
) -> SalaryAnalysisResponse:
    result = analyze_salary(
        payload.job_title,
        location=payload.location,
        years_of_experience=payload.years_of_experience,
        current_salary=payload.current_salary,
        jd_text=payload.jd_text or "",
        cv_text=payload.cv_text or "",
    )
    saved_record_id = save_ai_request(
        current_user,
        operation="salary_analyze",
        request_payload=payload.model_dump(),
        response_payload=result,
    )
    return SalaryAnalysisResponse(**result, saved_record_id=saved_record_id)
