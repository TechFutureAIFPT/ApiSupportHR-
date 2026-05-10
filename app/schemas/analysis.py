from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class CvTextEntry(BaseModel):
    file_name: str = Field(min_length=1)
    text: str = Field(min_length=1)


class CoreCvAnalysisRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    weights: Dict[str, Any]
    hard_filters: Dict[str, Any]
    cv_entries: List[CvTextEntry]


class CoreCvAnalysisResponse(BaseModel):
    candidates: List[Dict[str, Any]]


class CvProfileRefineRequest(BaseModel):
    cv_text: str = Field(min_length=1)
    current_education: str | None = None
    current_name: str | None = None


class CvProfileRefineResponse(BaseModel):
    standardized_education: str | None = None
    validation_note: str | None = None
    warnings: List[str] = Field(default_factory=list)
    refined_name: str | None = None


class CandidateEnrichmentRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    hard_filters: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    cv_text_map: Dict[str, str]


class CandidateEnrichmentResponse(BaseModel):
    candidates: List[Dict[str, Any]]
