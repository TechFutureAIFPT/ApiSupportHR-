from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class CvTextEntry(BaseModel):
    file_name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    cv_id: str | None = None
    file_id: str | None = None
    id: str | None = None
    size: int | None = None
    last_modified: int | None = None


class CoreCvAnalysisRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    weights: Dict[str, Any]
    hard_filters: Dict[str, Any]
    cv_entries: List[CvTextEntry]


class CoreCvAnalysisResponse(BaseModel):
    candidates: List[Dict[str, Any]]
    pipeline: Dict[str, Any] = Field(default_factory=dict)


class CvProfileRefineRequest(BaseModel):
    cv_text: str = Field(min_length=1)
    current_education: str | None = None
    current_name: str | None = None


class CvProfileRefineResponse(BaseModel):
    standardized_education: str | None = None
    validation_note: str | None = None
    warnings: List[str] = Field(default_factory=list)
    refined_name: str | None = None


class IndustryPrediction(BaseModel):
    label: str
    score: float | None = None


class CvIndustryClassificationRequest(BaseModel):
    cv_text: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class CvIndustryClassificationResponse(BaseModel):
    predicted_label: str
    confidence: float | None = None
    top_predictions: List[IndustryPrediction] = Field(default_factory=list)
    model_source: str


class CvIndustryClassifierStatusResponse(BaseModel):
    ready: bool
    model_source: str
    label_count: int = 0
    labels: List[str] = Field(default_factory=list)
    error: str | None = None


class CandidateEnrichmentRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    hard_filters: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    cv_text_map: Dict[str, str]


class CandidateEnrichmentResponse(BaseModel):
    candidates: List[Dict[str, Any]]
