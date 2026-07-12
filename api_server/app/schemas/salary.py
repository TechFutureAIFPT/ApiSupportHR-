from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class SalaryAnalysisRequest(BaseModel):
    job_title: str = Field(min_length=1)
    location: str | None = None
    years_of_experience: float | None = None
    current_salary: float | None = None
    jd_text: str | None = None
    cv_text: str | None = None


class SalaryAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    market_salary: Dict[str, Any] | None = Field(default=None, alias="marketSalary")
    comparison: Dict[str, Any] | None = None
    recommendation: str
    negotiation_tips: List[str] = Field(default_factory=list, alias="negotiationTips")
    source: str
    confidence_note: str | None = Field(default=None, alias="confidenceNote")
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")
