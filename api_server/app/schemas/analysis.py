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
    review_basis: str = Field(default="", alias="Can cu tham dinh")
    direct_match_matrix: List[Dict[str, Any]] = Field(default_factory=list, alias="Ma tran doi sanh truc tiep")
    strict_score_breakdown: Dict[str, Any] = Field(default_factory=dict, alias="Phan ra diem so nghiem ngat")
    interview_questions: List[str] = Field(default_factory=list, alias="Cau hoi phong van")
    self_review: str = Field(default="", alias="Tu tham dinh")


class HrSummaryExperience(BaseModel):
    so_nam_yeu_cau: str = ""
    so_nam_thuc_te: str = ""
    ket_luan: str = ""


class HrSummarySkillAssessment(BaseModel):
    ten_ky_nang: str = ""
    muc_do_dap_ung: str = ""
    bang_chung_tu_cv: str = ""


class StructuredHrSummary(BaseModel):
    tong_diem_phu_hop: int = 0
    nhan_xet_tong_quan: str = ""
    canh_bao_red_flag: List[str] = Field(default_factory=list)
    kinh_nghiem: HrSummaryExperience = Field(default_factory=HrSummaryExperience)
    danh_gia_ky_nang: List[HrSummarySkillAssessment] = Field(default_factory=list)


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
    hrSummary: StructuredHrSummary = Field(default_factory=StructuredHrSummary)
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
    weights: Dict[str, Any] = Field(default_factory=dict)
    hard_filters: Dict[str, Any] = Field(default_factory=dict)
    cv_entries: List[CvTextEntry]


class CoreCvAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidates: List[Dict[str, Any]]
    pipeline: Dict[str, Any] = Field(default_factory=dict)
    saved_history_id: str | None = Field(default=None, alias="savedHistoryId")


class AnalysisJobAcceptedResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing"] = "processing"
    status_url: str


class AnalysisJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: float = 0.0
    message: str = ""
    result: Dict[str, Any] | None = None
    error: str | None = None
    created_at: str | int | None = None
    updated_at: str | int | None = None


class CvProfileRefineRequest(BaseModel):
    cv_text: str = Field(min_length=1)
    current_education: str | None = None
    current_name: str | None = None


class CvProfileRefineResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    standardized_education: str | None = None
    validation_note: str | None = None
    warnings: List[str] = Field(default_factory=list)
    refined_name: str | None = None
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")


class IndustryPrediction(BaseModel):
    label: str
    score: float | None = None


class CvIndustryClassificationRequest(BaseModel):
    cv_text: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class CvIndustryClassificationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    predicted_label: str
    confidence: float | None = None
    top_predictions: List[IndustryPrediction] = Field(default_factory=list)
    model_source: str
    model_version: str = "unknown"
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")


class CvIndustryClassifierStatusResponse(BaseModel):
    ready: bool
    model_source: str
    model_version: str = "unknown"
    artifact_sha256: str = ""
    label_count: int = 0
    labels: List[str] = Field(default_factory=list)
    error: str | None = None


class CandidateEnrichmentRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    hard_filters: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    cv_text_map: Dict[str, str]


class CandidateEnrichmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidates: List[Dict[str, Any]]
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")


class QuickCvTextEntry(BaseModel):
    file_name: str = Field(min_length=1)
    text: str = Field(min_length=1)


class QuickCvScoreRequest(BaseModel):
    cv_entries: List[QuickCvTextEntry] = Field(min_length=1, max_length=3)
    jd_text: str | None = None
    include_extracted_text: bool = False


class QuickCvScoreItem(BaseModel):
    file_name: str
    candidate_name: str = ""
    target_role: str = ""
    score: int = Field(default=0, ge=0, le=100)
    rank: Literal["A", "B", "C"] = "C"
    summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)
    matched_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    extracted_text: str | None = None


class QuickCvScoreResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: List[QuickCvScoreItem]
    model: str
    usage_note: str = "AI output is a screening aid and should be reviewed by a recruiter."
    saved_score_id: str | None = Field(default=None, alias="savedScoreId")


class CandidateChatRequest(BaseModel):
    candidate_snapshot: Dict[str, Any] = Field(default_factory=dict)
    message: str = Field(min_length=1)
    job_position: str = ""
    recruiter_context: str | None = None


class CandidateChatResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    response_text: str = Field(alias="responseText")
    cited_criteria: List[str] = Field(default_factory=list, alias="citedCriteria")
    confidence: str = "medium"
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")
