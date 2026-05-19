from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class PointDeduction(BaseModel):
    reason: str = ""
    points_lost: float = 0.0


class KeywordAnalysis(BaseModel):
    keyword: str = ""
    status: Literal["matched", "missing"] = "missing"
    context_sentence: str = ""


class SkillKeywordMetrics(BaseModel):
    total_required_keywords: int = 0
    matched_keywords_count: int = 0
    match_percentage: float = 0.0
    keywords_list: List[KeywordAnalysis] = Field(default_factory=list)


ExplanationQuality = Literal["strong", "partial", "weak", "missing"]


class AdvancedScoreBreakdown(BaseModel):
    max_possible_score: float = 0.0
    raw_score_earned: float = 0.0
    mathematical_formula: str = ""
    deductions: List[PointDeduction] = Field(default_factory=list)
    bonuses_earned: List[str] = Field(default_factory=list)
    keyword_metrics: SkillKeywordMetrics = Field(default_factory=SkillKeywordMetrics)
    verdict: ExplanationQuality = "missing"
    evidence_quality: ExplanationQuality = "missing"
    matched_signals: List[str] = Field(default_factory=list)
    missing_requirements: List[str] = Field(default_factory=list)
    evidence_highlights: List[str] = Field(default_factory=list)
    improvement_suggestion: str = ""
    quality_flags: List[str] = Field(default_factory=list)


class StructuredDetailScore(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    criterion: str = Field(default="", alias="Tieu chi")
    score: str = Field(default="", alias="Diem")
    formula: str = Field(default="", alias="Cong thuc")
    evidence: str = Field(default="", alias="Dan chung")
    explanation: str = Field(default="", alias="Giai thich")
    advanced_breakdown: AdvancedScoreBreakdown = Field(
        default_factory=AdvancedScoreBreakdown,
        alias="advancedBreakdown",
    )


class StructuredCandidateAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    total_score: float = Field(default=0, alias="Tong diem")
    rank: Literal["A", "B", "C"] = Field(default="C", alias="Hang")
    details: List[StructuredDetailScore] = Field(default_factory=list, alias="Chi tiet")
    strengths: List[str] = Field(default_factory=list, alias="Diem manh CV")
    weaknesses: List[str] = Field(default_factory=list, alias="Diem yeu CV")
    education_validation: Dict[str, Any] = Field(default_factory=dict, alias="educationValidation")


class StructuredCandidateOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    candidateName: str = ""
    phone: str = ""
    email: str = ""
    fileName: str = ""
    jobTitle: str = ""
    industry: str = ""
    department: str = ""
    experienceLevel: str = ""
    hardFilterFailureReason: str = ""
    softFilterWarnings: List[str] = Field(default_factory=list)
    detectedLocation: str = ""
    analysis: StructuredCandidateAnalysis = Field(default_factory=StructuredCandidateAnalysis)


class StructuredCandidateOutputList(RootModel[List[StructuredCandidateOutput]]):
    pass


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
